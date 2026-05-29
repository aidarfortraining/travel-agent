# MCP_SERVERS.md

Три MCP-сервера, разделение по bounded contexts. Все на Python, mcp SDK, stdio transport. Запускаются как subprocess'ы из бэка через `MultiServerMCPClient`.

## Общие принципы

- Все tools возвращают **JSON-сериализуемые pydantic-модели**, не raw dicts.
- Все внешние HTTP-запросы — через `httpx.AsyncClient` с timeout 10s.
- Ошибки внешних API → возвращать `ToolErrorResponse(error_code, message, retryable)`, не raise.
- Минимум 1 unit-test на tool в `tests/test_<server_name>.py`.
- Все tools принимают `city: str` в нормализованном виде (например, "Istanbul" не "istanbul" не "İstanbul" — нормализация в самом сервере на входе).

### MCP test layout

Каждый MCP-сервер имеет файл `server.py` и `schemas.py` с одним и тем же именем модуля. При `pytest mcp_servers/` без обхода Python кеширует первый загруженный модуль и тесты соседних серверов падают на чужих классах (`cannot import name 'CityMeta' from 'schemas'`).

**Решение:** все три `tests/test_<server>.py` грузят свой `server.py` через `importlib.util.spec_from_file_location` под уникальным именем модуля (`travel_tools_server`, `trip_utilities_server`, `city_knowledge_server`). Перед загрузкой `_load()`:
1. `sys.modules.pop("server", None); sys.modules.pop("schemas", None)` — сбрасывает кеш.
2. Нормализует `sys.path`: убирает дубликаты `_SERVER_DIR` и кладёт его в `sys.path[0]`, чтобы `from schemas import ...` внутри `server.py` нашёл локальный, а не соседский.

### Schemas dublication

MCP-серверы — отдельные процессы (запускаются как subprocess из backend через stdio). Они **не импортируют** код из `backend/src/schemas/`. Pydantic-классы (Place, Restaurant, Plan, CostBreakdown, GuideChunk, CityOverview, WeatherDaily и т.д.) **дублируются локально** в каждом MCP-сервере, в `mcp_servers/<name>/schemas.py`.

Это намеренный trade-off для учебного проекта (избегаем shared-package сложности). На границе MCP передаётся JSON; mcp SDK + langchain-mcp-adapters автоматически конвертируют pydantic ↔ JSON, поэтому идентичность Python-классов не требуется — важна только структура.

### Type signatures и ToolErrorResponse

Сигнатуры tools в этом документе декларируют **happy-path тип** (например, `-> list[Place]`). При ошибке tool возвращает `ToolErrorResponse` — на уровне JSON оба варианта валидны (mcp SDK прокидывает любой JSON-сериализуемый объект). Реальная Python-сигнатура — `Union[list[Place], ToolErrorResponse]`, но мы её упрощаем для читаемости.

Caller (нода LangGraph, обернутая через `langchain-mcp-adapters`) после `await tool.ainvoke(...)` проверяет наличие поля `is_error`. Если есть — это error response; обрабатывает по `retryable`.

**Важно (langchain-mcp-adapters wrapper format):** `tool.ainvoke()` возвращает результат в формате `[{"type": "text", "text": "<json-string>"}]` — список text-content объектов, в `text` лежит JSON-сериализованный реальный результат. Ноды НЕ должны парсить это вручную; используйте хелперы `backend/src/mcp_clients/client.py`:
- `call_tool(name, **kwargs)` — для tools с return type `dict` (например `get_city_overview`, `get_weather_forecast`, `estimate_plan_cost`). Возвращает первый распарсенный JSON-объект или `{}`.
- `call_tool_list(name, **kwargs)` — для tools с return type `list[...]` (например `find_places`, `find_restaurants`, `search_city_guide`, `list_indexed_cities`).

Под капотом `_unwrap_mcp_result` парсит `text` поле каждого item в реальный Python-объект.

## Сервер 1: `travel-tools`

**Расположение:** `mcp_servers/travel-tools/server.py`

**Назначение:** доступ к внешнему миру — POI, рестораны, погода, маршруты. Никакой LLM-логики.

**Зависимости:** `httpx`, `mcp`, `pydantic`. Нет API-ключей (Overpass, Open-Meteo, OSRM — бесплатные публичные).

### Tools

#### 1. `find_places`

```python
@mcp.tool()
async def find_places(
    city: str,
    category: Literal["museum", "park", "viewpoint", "historical", "religious", "nightlife", "shopping"],
    budget_tier: Literal["free", "low", "mid", "high"] = "mid",
    limit: int = 10,
) -> list[Place]:
    """
    Search Points of Interest (POI) in a city by category and budget tier.
    Uses OpenStreetMap Overpass API.
    
    Returns up to `limit` places matching the criteria, sorted by relevance
    (descending importance tag in OSM).
    """
```

`Place` schema:
```python
class Place(BaseModel):
    osm_id: str               # OSM node/way ID for traceability
    name: str
    category: str             # OSM tag
    lat: float
    lon: float
    address: str | None
    opening_hours: str | None  # OSM opening_hours format
    website: str | None
    wikipedia: str | None      # Wikipedia article slug if available
    estimated_visit_minutes: int  # heuristic: museum=120, viewpoint=30, etc.
    estimated_cost_usd: float  # 0 for "free", heuristic for others
```

**Data source:** Overpass API query like:
```overpass
[out:json][timeout:25];
area["name:en"="Istanbul"]->.searchArea;
(
  node["tourism"="museum"](area.searchArea);
  way["tourism"="museum"](area.searchArea);
);
out center 30;
```

**Resilience — `_overpass_query`:** main endpoint (`overpass-api.de`) регулярно отдаёт 504/502. Запросы крутятся в 5 попыток через 3 зеркала с экспоненциальным backoff (per-request timeout — 15s: деградировавшее зеркало отваливается быстро, чтобы следующая попытка укладывалась в общий тайм-бюджет ноды `candidate_places`):

```python
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

# Per attempt:
#   url = OVERPASS_MIRRORS[attempt % 3]
#   on 429/502/503/504 or TimeoutException/RemoteProtocolError/ConnectError:
#     log + sleep(min(2**attempt, 8))
#     continue
#   else: r.raise_for_status() + return JSON
```

После 5 неудачных попыток `_overpass_query` re-raise'ит последнюю ошибку, и `find_places`/`find_restaurants` оборачивают её в `ToolErrorResponse(error_code="EXTERNAL_API_ERROR", retryable=True)`.

**Mapping category → OSM tags:**
- `museum` → `tourism=museum`
- `park` → `leisure=park OR leisure=garden`
- `viewpoint` → `tourism=viewpoint`
- `historical` → `historic=*`
- `religious` → `amenity=place_of_worship`
- `nightlife` → `amenity=bar OR amenity=nightclub`
- `shopping` → `shop=mall OR shop=market`

#### 2. `find_restaurants`

```python
@mcp.tool()
async def find_restaurants(
    city: str,
    dietary: list[Literal["halal", "vegan", "vegetarian", "gluten-free", "kosher"]],
    cuisine: str | None = None,
    price_tier: Literal["$", "$$", "$$$", "$$$$"] = "$$",
    limit: int = 10,
) -> list[Restaurant]:
    """
    Search restaurants matching dietary restrictions and price tier.
    Uses OpenStreetMap Overpass API with diet:* tag filtering.
    
    Note: OSM diet tags are incomplete; for "halal" we also include
    restaurants tagged cuisine=turkish, cuisine=middle_eastern, etc.
    as soft matches with confidence_score < 1.0.
    """
```

`Restaurant` schema:
```python
class Restaurant(BaseModel):
    osm_id: str
    name: str
    cuisine: str | None
    lat: float
    lon: float
    address: str | None
    dietary_tags: list[str]   # Confirmed dietary support from OSM diet:* tags
    dietary_confidence: float  # 0.0–1.0; soft matches < 1.0
    price_tier: str            # Mapped from OSM price tag
    opening_hours: str | None
    phone: str | None
    estimated_meal_cost_usd: float
```

**Overpass filter:**
```overpass
node["amenity"="restaurant"]["diet:halal"="yes"](area.searchArea);
```

Если найдено мало (< 3) — расширить запрос на soft matches без `diet:*`, проставить `dietary_confidence=0.5`.

#### 3. `get_weather_forecast`

```python
@mcp.tool()
async def get_weather_forecast(
    city: str,
    start_date: str | None = None,  # ISO YYYY-MM-DD; if None — defaults to today
    end_date: str | None = None,    # ISO YYYY-MM-DD; if None — defaults to start_date + 14d
) -> WeatherDaily:
    """
    Daily weather forecast for a city.
    Uses Open-Meteo (free, no API key).
    
    Date handling:
    - Both None → use today as start, today+14d as end (typical "I want to go soon" case).
    - Only start_date set → end_date = start_date + 14d.
    - If end_date is > 16 days from today → returns climate average for those
      months with `is_forecast=False` flag (Open-Meteo only forecasts 16 days ahead).
    
    The TripState in backend always passes today's date if user didn't specify trip dates.
    """
```

`WeatherDaily` schema:
```python
class WeatherDailyEntry(BaseModel):
    date: str  # ISO YYYY-MM-DD
    temp_min_c: float
    temp_max_c: float
    precipitation_mm: float
    weather_code: int  # WMO code
    weather_desc: str  # Human-readable: "Sunny", "Light rain", etc.

class WeatherDaily(BaseModel):
    city: str
    is_forecast: bool   # False if climate average
    entries: list[WeatherDailyEntry]
```

**Endpoint:** `https://api.open-meteo.com/v1/forecast?latitude=...&longitude=...&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code`

Геокодинг города → lat/lon через Open-Meteo Geocoding API (`https://geocoding-api.open-meteo.com/v1/search?name=Istanbul&count=1`).

#### 4. `compute_route`

```python
@mcp.tool()
async def compute_route(
    points: list[LatLon],
    mode: Literal["walk", "transit", "drive"] = "walk",
) -> RouteResult:
    """
    Compute travel time and distance for an ordered sequence of points.
    Uses OSRM public instance for walk/drive. Transit returns walking time × 0.7 
    as a rough estimate (real transit routing requires a paid API).
    
    Returns matrix of pairwise times + total path metrics.
    """
```

`RouteResult` schema:
```python
class LatLon(BaseModel):
    lat: float
    lon: float

class RouteSegment(BaseModel):
    from_idx: int
    to_idx: int
    distance_m: float
    duration_seconds: float

class RouteResult(BaseModel):
    mode: str
    segments: list[RouteSegment]
    total_distance_m: float
    total_duration_seconds: float
    warning: str | None  # e.g., "Transit times are approximate"
```

**Endpoint:** `https://router.project-osrm.org/route/v1/{profile}/{coords}?overview=false`

---

## Сервер 2: `city-knowledge`

**Расположение:** `mcp_servers/city-knowledge/server.py`

**Назначение:** оборачивает Qdrant как MCP — даёт агенту structured-доступ к проиндексированной базе travel-гайдов. Это важный паттерн: MCP не только для внешних API, но и для собственных данных.

**Зависимости:** `qdrant-client`, `openai` (для query-embeddings через `text-embedding-3-small`), `mcp`, `pydantic`.

### Tools

#### 1. `search_city_guide`

```python
@mcp.tool()
async def search_city_guide(
    city: str,
    query: str,
    k: int = 5,
    section: Literal["see", "do", "eat", "drink", "sleep", "get-around"] | None = None,
) -> list[GuideChunk]:
    """
    Semantic search over Wikivoyage-indexed content for a specific city.
    Optionally filter by section (See / Do / Eat / Drink / Sleep / Get around).
    
    Returns top-k chunks with text and source metadata for traceability.
    """
```

`GuideChunk` schema:
```python
class GuideChunk(BaseModel):
    chunk_id: str
    city: str
    section: str
    text: str  # 200–800 tokens
    source_url: str  # Wikivoyage URL with anchor
    score: float  # Qdrant cosine similarity, 0.0–1.0
```

**Implementation:**
- Embed `query` via `text-embedding-3-small` (OpenAI, 1536-dim).
- Qdrant search через `client.query_points(query=vector, query_filter=Filter(must=[city=..., kind="guide", section=...]), limit=k, with_payload=True)`. Возвращает `QueryResponse` — итерируем по `res.points` (НЕ по самому `res`).
- **Не использовать legacy `.search()`** — метод удалён в qdrant-client ≥1.18 и поднимает `AttributeError`.

**Qdrant layout:** **одна коллекция (`trip_planner_v1`)** на все города. Фильтрация по metadata-полю `city` — НЕ создавать коллекцию на город. Vector dim = 1536 фиксирован выбранной embedding-моделью.

#### 2. `get_city_overview`

```python
@mcp.tool()
async def get_city_overview(city: str) -> CityOverview:
    """
    Return pre-computed structured overview of a city:
    best season to visit, currency, language, safety notes, transport summary.
    
    These are computed once at ingestion time and stored as a dedicated
    "overview" chunk in Qdrant.
    """
```

`CityOverview` schema:
```python
class CityOverview(BaseModel):
    city: str
    country: str
    currency: str  # ISO 4217
    languages: list[str]
    best_season: str  # "Apr-Jun, Sep-Oct"
    safety_level: Literal["low_risk", "moderate_risk", "high_risk"]
    safety_notes: str
    transport_summary: str
    timezone: str  # IANA tz, e.g., "Europe/Istanbul"
```

#### 3. `list_indexed_cities`

```python
@mcp.tool()
async def list_indexed_cities() -> list[CityMeta]:
    """
    Return all cities that have been ingested into the RAG index.
    Used by the planning agent to fall back gracefully when the user
    requests a city not in the index.
    """
```

`CityMeta` schema:
```python
class CityMeta(BaseModel):
    city: str
    country: str
    chunk_count: int
    ingested_at: str  # ISO datetime
```

---

## Сервер 3: `trip-utilities`

**Расположение:** `mcp_servers/trip-utilities/server.py`

**Назначение:** доменные утилиты — конвертация валют, оценка стоимости плана, валидация dietary совместимости.

**Зависимости:** `httpx`, `mcp`, `pydantic`.

### Tools

#### 1. `convert_currency`

```python
@mcp.tool()
async def convert_currency(
    amount: float,
    from_ccy: str,  # ISO 4217: USD, EUR, TRY, JPY, ...
    to_ccy: str,
) -> CurrencyConversion:
    """
    Convert amount between currencies using current exchange rate.
    Uses the Frankfurter API (free, ECB-sourced rates, no API key).
    NB: frankfurter.app сейчас 301-редиректит на frankfurter.dev, поэтому
    httpx-клиент создаётся с follow_redirects=True (иначе r.json() падает на
    HTML-теле редиректа и tool всегда возвращает EXTERNAL_API_ERROR).

    Cached in-memory for 1 hour to reduce API calls.
    """
```

`CurrencyConversion` schema:
```python
class CurrencyConversion(BaseModel):
    amount: float
    from_ccy: str
    to_ccy: str
    converted: float
    rate: float
    rate_date: str  # ISO date when rate was fetched
```

#### 2. `estimate_plan_cost`

```python
@mcp.tool()
async def estimate_plan_cost(plan: Plan) -> CostBreakdown:
    """
    Sum up estimated costs in the proposed plan across categories:
    attractions, restaurants, transport, accommodation (if included).
    
    Returns breakdown per day and total, in USD.
    """
```

`Plan` schema (упрощённая, полная в `backend/src/schemas/plan.py`):
```python
class TimeBlock(BaseModel):
    period: Literal["morning", "afternoon", "evening"]
    start_time: str  # "HH:MM"
    place_id: str    # references Place or Restaurant
    place_type: Literal["attraction", "restaurant", "transition"]
    estimated_cost_usd: float
    notes: str

class DayPlan(BaseModel):
    day_number: int
    date: str | None  # ISO YYYY-MM-DD if user provided dates
    blocks: list[TimeBlock]

class Plan(BaseModel):
    city: str
    days: list[DayPlan]
    accommodation_per_night_usd: float | None
```

`CostBreakdown`:
```python
class CostBreakdownDay(BaseModel):
    day_number: int
    attractions_usd: float
    restaurants_usd: float
    transport_usd: float
    total_usd: float

class CostBreakdown(BaseModel):
    per_day: list[CostBreakdownDay]
    grand_total_usd: float
    accommodation_total_usd: float
    grand_total_with_accommodation_usd: float
```

#### 3. `validate_dietary_match`

```python
@mcp.tool()
async def validate_dietary_match(
    place_name: str,
    place_cuisine: str | None,
    place_tags: list[str],
    restrictions: list[Literal["halal", "vegan", "vegetarian", "gluten-free", "kosher"]],
) -> DietaryCheckResult:
    """
    Cross-check whether a place accommodates given dietary restrictions.
    Uses heuristic rules (cuisine type, OSM tags, name hints) — does NOT
    call LLM.
    
    Returns verdict + reasoning. Used by the planning agent as a sanity check
    before adding a restaurant to the plan.
    """
```

`DietaryCheckResult` schema:
```python
class DietaryCheckResult(BaseModel):
    place_name: str
    verdict: Literal["accommodates", "partial", "does_not_accommodate", "unknown"]
    confidence: float  # 0.0–1.0
    reasoning: str
    accommodated_restrictions: list[str]
    unaccommodated_restrictions: list[str]
```

**Rules** (внутри сервера, hard-coded). Возвращаемый `verdict` + `confidence`:

`halal`:
- `verdict="accommodates"`, `confidence=1.0` — если `diet:halal=yes` ∈ tags
- `verdict="partial"`, `confidence=0.6` — если cuisine ∈ {turkish, middle_eastern, lebanese, arab, persian, pakistani, malaysian, indian} AND cuisine NOT IN {bbq, german, american_southern} (мягкое соответствие по типу кухни)
- `verdict="does_not_accommodate"`, `confidence=0.9` — если cuisine ∈ {bbq, german, american_southern, japanese} (последние часто содержат свинину) без явного `diet:halal=yes`
- `verdict="unknown"`, `confidence=0.0` — в остальных случаях

`vegan`:
- `accommodates`, 1.0 — `diet:vegan=yes` OR `cuisine=vegan`
- `partial`, 0.5 — `cuisine=vegetarian`
- `unknown`, 0.0 — иначе

`vegetarian`:
- `accommodates`, 1.0 — `diet:vegetarian=yes`, `cuisine=vegetarian`, `cuisine=vegan`
- `partial`, 0.7 — cuisine ∈ {indian, mediterranean} (обычно есть вегетарианские опции)
- `unknown`, 0.0 — иначе

`gluten-free`:
- `accommodates`, 1.0 — `diet:gluten_free=yes`
- `unknown`, 0.0 — иначе (без явного тега судить нельзя)

`kosher`:
- `accommodates`, 1.0 — `diet:kosher=yes`
- `unknown`, 0.0 — иначе (kosher строго сертифицируется, никаких эвристик)

**Связь с `Restaurant.dietary_confidence`:** поле `dietary_confidence` в результатах `find_restaurants` вычисляется по этим же правилам — фактически `find_restaurants` внутри себя гоняет ту же логику и заполняет числовой confidence. `validate_dietary_match` существует отдельно как **sanity-check для произвольного места по запросу агента** (например, когда агент применяет правку плана и ему нужно проверить новый кандидат). Семантика согласована: `dietary_confidence >= 0.5` ↔ `verdict ∈ {accommodates, partial}`.

---

## Конфигурация MCP клиента в LangGraph

```python
# backend/src/mcp_clients/client.py
from langchain_mcp_adapters.client import MultiServerMCPClient

mcp_client = MultiServerMCPClient(
    {
        "travel-tools": {
            "command": "python",
            "args": ["mcp_servers/travel-tools/server.py"],
            "transport": "stdio",
        },
        "city-knowledge": {
            "command": "python",
            "args": ["mcp_servers/city-knowledge/server.py"],
            "transport": "stdio",
            "env": {"QDRANT_URL": "...", "OPENAI_API_KEY": "...", "OPENAI_EMBEDDING_MODEL": "text-embedding-3-small"},
        },
        "trip-utilities": {
            "command": "python",
            "args": ["mcp_servers/trip-utilities/server.py"],
            "transport": "stdio",
        },
    }
)

tools = await mcp_client.get_tools()
# Pass `tools` to LangGraph nodes that need them via bind_tools()
```

В docker-compose каждый MCP-сервер — отдельный сервис, но stdio-подключение делается из backend-контейнера через subprocess. Для production это не сработает; для нашего MVP — нормально.

## Error handling — общий контракт

Все tools в случае ошибки возвращают:
```python
class ToolErrorResponse(BaseModel):
    is_error: bool = True
    error_code: Literal["EXTERNAL_API_ERROR", "INVALID_INPUT", "NOT_FOUND", "TIMEOUT", "RATE_LIMIT"]
    message: str  # Human-readable
    retryable: bool
```

LangGraph-нода видит `is_error=True` и решает:
- `retryable=True` → retry до 2 раз с backoff
- `retryable=False` → продолжать с пустым результатом, пометить в plan что данных нет

## Тестирование

Каждый сервер имеет `mcp_servers/<name>/tests/test_<name>.py` с минимум:
- Smoke test: tool вызывается, возвращает ожидаемую pydantic-модель.
- Edge case: пустой результат, невалидный город, таймаут.

Запуск: `pytest mcp_servers/`.
