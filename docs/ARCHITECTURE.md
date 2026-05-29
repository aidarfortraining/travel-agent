# ARCHITECTURE.md

## Высокоуровневая диаграмма

```
┌──────────────────────────────────────────────────────────────────┐
│                        React (Vite + TS)                         │
│   Form → Photo Upload → SSE Progress → Plan View → Edit → PDF    │
└─────────────────────────────┬────────────────────────────────────┘
                              │ HTTP + Server-Sent Events
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                            FastAPI                               │
│   POST /sessions            → create session_id                  │
│   POST /sessions/{id}/input → submit form                        │
│   POST /sessions/{id}/photo → multipart photo upload             │
│   GET  /sessions/{id}/stream → SSE: graph node state events      │
│   POST /sessions/{id}/edit  → text edit command                  │
│   POST /sessions/{id}/accept → finalize plan                     │
│   GET  /sessions/{id}/pdf   → download PDF                       │
└─────────────────────────────┬────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│         LangGraph (AsyncSqliteSaver checkpointer)                │
│        14 user nodes (+ __start__), 3 branches, 2 loops, 2 HITL  │
└──┬───────────────┬──────────────────┬───────────────────┬────────┘
   │               │                  │                   │
   ▼               ▼                  ▼                   ▼
┌────────┐  ┌─────────────┐    ┌──────────────┐    ┌────────────┐
│OpenAI  │  │ MCP server: │    │ MCP server:  │    │ MCP server:│
│gpt-4.1 │  │ travel-     │    │ city-        │    │ trip-      │
│-mini   │  │ tools       │    │ knowledge    │    │ utilities  │
│+Skill  │  │ (4 tools)   │    │ (3 tools)    │    │ (3 tools)  │
└────────┘  └──────┬──────┘    └──────┬───────┘    └────┬───────┘
                   │                  │                 │
                   ▼                  ▼                 ▼
            OpenStreetMap      ┌──────────────┐   frankfurter.app (FX)
            (Overpass API)     │   Qdrant     │   internal logic
            Open-Meteo         │  (Wikivoyage │
            OSRM               │   embeddings)│
                               └──────────────┘
                                      ▲
                                      │
                            scripts/ingest_wikivoyage.py
                            (scrape → chunk → embed → upsert)
```

LangSmith подключается через env-переменные (`LANGSMITH_TRACING=true`), трассирует ВСЁ автоматически — изменения в коде графа не требуются.

## LangGraph workflow — детальная схема

```
                            START
                              │
                              ▼
                  [1] collect_input
                     (Pydantic-валидация формы)
                              │
                              ▼
                  [2] {has_photo?}
                ┌───── YES ───┴── NO ─────┐
                ▼                          │
       [3] vision_identify                 │
          (gpt-4.1-mini vision)             │
          out: {landmark, city, type}      │
                │                          │
                ▼                          │
       [4] enrich_input                    │
          (мерж фото-инфы в state)         │
                │                          │
                └──────────┬───────────────┘
                           ▼
                  [5] city_research
                     MCP: city-knowledge.search_city_guide()
                          city-knowledge.get_city_overview()
                     (RAG чанки + overview города в state)
                           │
                           ▼
                  [6] candidate_places
                     MCP: travel-tools.find_places()
                          travel-tools.find_restaurants()
                          travel-tools.get_weather()
                           │
                           ▼
                  [7] {budget_feasible?}
              ┌────── NO ──┴── YES ──────┐
              ▼                           ▼
   [8] explain_and_ask             [9] cluster_by_day
       (HITL interrupt():              (геокластеризация
        предлагаем урезать              k-means по lat/lon,
        бюджет/scope)                   1 кластер на день)
              │                           │
              └─────► back to [5]         ▼
                                  [10] optimize_route
                                       MCP: travel-tools.compute_route()
                                       (упорядочить точки внутри дня
                                        по nearest-neighbor)
                                          │
                                          ▼
                                  [11] generate_plan
                                       (gpt-4.1-mini + Skill:
                                        itinerary-formatter)
                                       MCP: trip-utilities.estimate_plan_cost()
                                          │
                                          ▼
                                  [12] HITL: interrupt()
                                       показываем план юзеру
                                          │
                              ┌─ EDIT ───┴── ACCEPT ─┐
                              ▼                       ▼
                  [13] parse_edit_intent       [15] finalize_and_export
                     (gpt-4.1-mini, structured)      (Skill: формат для PDF,
                              │                      weasyprint → bytes)
                              ▼                            │
                  [14] patch_plan                          ▼
                     (точечный апдейт state              END
                      без полной регенерации)              
                              │
                              └────► back to [12]
```

### Узлы — описание и ответственности

| ID | Нода | Тип | LLM | MCP tools | Side effects |
|---|---|---|---|---|---|
| 1 | `collect_input` | sync | — | — | Pydantic-валидация |
| 2 | `has_photo` branch | conditional | — | — | — |
| 3 | `vision_identify` | async | gpt-4.1-mini (vision) | — | — |
| 4 | `enrich_input` | sync | — | — | state merge |
| 5 | `city_research` | async | — | city-knowledge.search_city_guide + city-knowledge.get_city_overview | Qdrant queries |
| 6 | `candidate_places` | async | — | travel-tools | External APIs |
| 7 | `budget_feasible` branch | sync | — | trip-utilities.estimate_plan_cost | — |
| 8 | `explain_and_ask` | async + HITL | gpt-4.1-mini | — | `interrupt()` |
| 9 | `cluster_by_day` | sync | — | — | sklearn KMeans |
| 10 | `optimize_route` | async | — | travel-tools.compute_route | — |
| 11 | `generate_plan` | async | gpt-4.1-mini + Skill | trip-utilities.estimate_plan_cost | — |
| 12 | `present_plan` | HITL | — | — | `interrupt()` |
| 13 | `parse_edit_intent` | async | gpt-4.1-mini | — | structured output |
| 14 | `patch_plan` | async | gpt-4.1-mini + Skill | trip-utilities.estimate_plan_cost, travel-tools.find_places | state patch + LLM rerender |
| 15 | `finalize_and_export` | async | gpt-4.1-mini + Skill | — | PDF generation |

### State schema (pydantic)

Все вспомогательные модели — в `backend/src/schemas/`. `Place`, `Restaurant`, `WeatherDaily`, `GuideChunk`, `CityOverview`, `Plan`, `CostBreakdown` определены в `MCP_SERVERS.md`.

Дополнительные схемы, специфичные для графа:

```python
class PhotoAnalysis(BaseModel):
    """Output of vision_identify node."""
    landmark: str            # Identified landmark name, e.g. "Blue Mosque"
    city: str                # Detected/confirmed city
    place_type: str          # "religious", "viewpoint", "museum", ...
    description: str         # Short LLM-generated description (1–2 sentences)
    confidence: float        # 0.0–1.0

class EditIntent(BaseModel):
    """Structured output of parse_edit_intent node (gpt-4.1-mini, structured output)."""
    action: Literal["remove", "add", "replace", "constrain"]
    target: str              # what is affected; for "replace" — the thing being removed
    detail: str | None       # for "replace" — the replacement; for "constrain" — the "$N" cap
    raw_text: str            # Original user message verbatim

class EditRecord(BaseModel):
    """One entry in TripState.edit_history."""
    timestamp: str           # ISO datetime
    intent: EditIntent
    applied: bool
    notes: str               # Human-readable summary of what changed
```

Главная state-модель:

```python
class TripState(BaseModel):
    # User input
    city: str
    days: int
    budget_usd: float
    interests: list[str]
    dietary: list[Literal["halal","vegan","vegetarian","gluten-free","kosher"]]
    photo_b64: str | None = None
    
    # Derived during graph execution
    photo_analysis: PhotoAnalysis | None = None
    city_overview: CityOverview | None = None   # From city-knowledge.get_city_overview
    city_context: list[GuideChunk] = []         # From city-knowledge.search_city_guide
    candidate_places: list[Place] = []
    candidate_restaurants: list[Restaurant] = []
    weather: WeatherDaily | None = None
    
    # Plan artifacts
    plan: Plan | None = None                    # Structured plan (Plan schema in MCP_SERVERS.md)
    plan_markdown: str | None = None            # Rendered via itinerary-formatter Skill, used by UI and PDF
    plan_cost_breakdown: CostBreakdown | None = None
    
    # Edit loop
    pending_edit_text: str | None = None
    edit_history: list[EditRecord] = []
    
    # Evals support (required by faithfulness judge in EVALS_PLAN.md)
    tool_calls_aggregated: list[dict] = []      # Appended by every node that calls an MCP tool;
                                                # each entry: {"tool": str, "args": dict, "result_summary": dict}
    
    # Budget HITL loop control
    budget_warning: str | None = None
    budget_acknowledged: bool = False           # Set True after explain_and_ask runs once (user OR
                                                # EVAL_MODE accept); budget_check skips warning thereafter
                                                # to prevent infinite explain_and_ask ↔ budget_check loop.

    # Meta
    session_id: str
    status: Literal["draft","awaiting_review","finalized"] = "draft"
    last_node: str = ""
    accept_signal: bool = False
```

**`TimeBlock.notes` contract:** `generate_plan._build_structured_plan` пишет `Place.category` ("museum"/"historical"/"park"/etc.) в `notes`. `patch_plan._apply_remove` читает это поле для определения категории блока — `place_type` всегда `"attraction"`/`"restaurant"` и не различает museum vs historical site. Это позволяет правкам типа "убери музеи" работать даже на тюркских/иностранных названиях ("Müzesi" не содержит ASCII "museum").

## Структура репозитория

```
trip-planner/
├── CLAUDE.md
├── README.md
├── docker-compose.yml
├── .env.example
├── .gitignore
│
├── docs/
│   ├── PROJECT_SPEC.md
│   ├── ARCHITECTURE.md
│   ├── MCP_SERVERS.md
│   └── EVALS_PLAN.md
│
├── backend/
│   ├── pyproject.toml
│   ├── Dockerfile
│   ├── src/
│   │   ├── __init__.py
│   │   ├── main.py                  # FastAPI app entry
│   │   ├── config.py                # Pydantic Settings (env vars)
│   │   │
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── sessions.py          # session CRUD
│   │   │   ├── stream.py            # SSE endpoint
│   │   │   └── export.py            # PDF endpoint
│   │   │
│   │   ├── graph/
│   │   │   ├── __init__.py
│   │   │   ├── state.py             # TripState pydantic
│   │   │   ├── builder.py           # build_graph() function
│   │   │   ├── nodes/
│   │   │   │   ├── collect_input.py
│   │   │   │   ├── vision_identify.py
│   │   │   │   ├── enrich_input.py
│   │   │   │   ├── city_research.py
│   │   │   │   ├── candidate_places.py
│   │   │   │   ├── explain_and_ask.py
│   │   │   │   ├── cluster_by_day.py
│   │   │   │   ├── optimize_route.py
│   │   │   │   ├── generate_plan.py
│   │   │   │   ├── present_plan.py
│   │   │   │   ├── parse_edit_intent.py
│   │   │   │   ├── patch_plan.py
│   │   │   │   └── finalize_and_export.py
│   │   │   └── branches.py          # conditional edge functions (has_photo, budget_feasible, edit_or_accept)
│   │   │
│   │   ├── llm/
│   │   │   ├── __init__.py
│   │   │   ├── client.py            # Single LLM wrapper, LangSmith decorators
│   │   │   ├── prompts.py           # All prompts as constants
│   │   │   └── skill_loader.py      # Loads SKILL.md content as system prompt
│   │   │
│   │   ├── rag/
│   │   │   ├── __init__.py
│   │   │   ├── qdrant_client.py
│   │   │   ├── embeddings.py        # text-embedding-3-small wrapper
│   │   │   └── chunking.py          # Wikivoyage section-based chunker
│   │   │
│   │   ├── mcp_clients/
│   │   │   ├── __init__.py
│   │   │   └── client.py            # MultiServerMCPClient setup
│   │   │
│   │   ├── schemas/             # Pydantic models. Sources of truth for Place, Restaurant, Plan,
│   │   │   │                    # CostBreakdown, WeatherDaily, GuideChunk, CityOverview, etc.
│   │   │   │                    # MCP-серверы НЕ импортируют этот пакет (отдельные процессы) —
│   │   │   │                    # они дублируют те же pydantic-классы у себя локально.
│   │   │   │                    # На границе передаётся JSON, MCP-клиент в backend
│   │   │   │                    # парсит обратно в эти классы.
│   │   │   ├── __init__.py
│   │   │   ├── place.py
│   │   │   ├── restaurant.py
│   │   │   ├── weather.py
│   │   │   ├── guide.py         # GuideChunk, CityOverview, CityMeta
│   │   │   ├── plan.py          # Plan, DayPlan, TimeBlock, CostBreakdown
│   │   │   ├── edit.py          # EditIntent, EditRecord
│   │   │   └── photo.py         # PhotoAnalysis
│   │   │
│   │   └── export/
│   │       ├── __init__.py
│   │       └── pdf.py               # weasyprint wrapper
│   │
│   └── tests/
│       ├── test_graph_smoke.py      # e2e graph test on 1 sample input
│       ├── test_mcp_clients.py      # MCP client wiring (not server logic — that lives in mcp_servers/*)
│       └── test_rag.py              # Qdrant search smoke test
│
├── frontend/
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── Dockerfile
│   ├── nginx.conf
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── components/
│       │   ├── Stepper.tsx          # step nav: Параметры→Генерация→Просмотр→Готово
│       │   ├── TripForm.tsx         # accepts initialValues for prefill on "back"
│       │   ├── PhotoUpload.tsx
│       │   ├── GraphProgress.tsx    # SSE-driven progress
│       │   ├── PlanView.tsx
│       │   ├── EditBox.tsx
│       │   └── ui/                  # shadcn primitives
│       ├── hooks/
│       │   ├── useSession.ts
│       │   └── useGraphStream.ts    # EventSource wrapper
│       └── api/
│           └── client.ts            # fetch wrapper
│
├── mcp_servers/
│   ├── travel-tools/
│   │   ├── pyproject.toml
│   │   ├── Dockerfile
│   │   ├── server.py
│   │   └── tests/
│   │       └── test_travel_tools.py
│   ├── city-knowledge/
│   │   ├── pyproject.toml
│   │   ├── Dockerfile
│   │   ├── server.py
│   │   └── tests/
│   │       └── test_city_knowledge.py
│   └── trip-utilities/
│       ├── pyproject.toml
│       ├── Dockerfile
│       ├── server.py
│       └── tests/
│           └── test_trip_utilities.py
│
├── skill/
│   └── itinerary-formatter/
│       └── SKILL.md
│
├── scripts/
│   ├── ingest_wikivoyage.py         # Initial RAG population
│   └── verify_setup.py              # Sanity check: env vars, Qdrant, LangSmith
│
└── evals/
    ├── dataset.jsonl
    ├── upload_dataset.py             # one-time push of dataset.jsonl to LangSmith
    ├── run.py                        # run evaluation for one experiment
    ├── compare_experiments.py        # generate ab_pro_vs_flash.md from two LangSmith experiments
    ├── judges/
    │   ├── __init__.py
    │   ├── constraint_adherence.py
    │   └── faithfulness.py
    └── results/
        ├── ab_pro_vs_flash.md
        └── traces/                   # screenshots, exported LangSmith run IDs
```

## Поток данных через систему

### 1. Запрос (без фото)

```
React form → POST /sessions/{id}/input
  → FastAPI validates, persists to graph state
  → Triggers graph: collect_input → city_research → candidate_places 
    → cluster → route → generate_plan → interrupt at present_plan
  → SSE emits node-by-node events to React
  → React renders plan when interrupt reached
```

### 2. Запрос с фото

Тот же поток, но между `collect_input` и `city_research` — `vision_identify` → `enrich_input` (добавляет landmark в interests).

### 3. Правка

```
React edit input → POST /sessions/{id}/edit
  → FastAPI resumes graph from present_plan interrupt (Command(resume={accept:false, edit}))
  → parse_edit_intent (gpt-4.1-mini, structured) → patch_plan → loop back to present_plan
  → SSE emits events
  → React re-renders patched plan
```

`parse_edit_intent` превращает свободный текст в `EditIntent{action, target, detail}`.
`patch_plan` применяет правку к структурному `Plan`, затем **пере-рендерит rich-markdown через LLM**
(`_rich_rerender`, промпты `EDIT_RERENDER_*` + тот же skill `itinerary-formatter`), чтобы сохранить
halal-маркеры, описания, погоду, источники и таблицу бюджета. После правки пересчитывается
`plan_cost_breakdown` через `estimate_plan_cost`.

Действия:
- `remove` — `_apply_remove`: выкидывает блоки, чья категория (`TimeBlock.notes`) матчит `target`
  по стемам `REMOVE_KEYWORDS` («музе», «истори», …).
- `constrain` — `_apply_constrain`: парсит лимит `$N` из `target`/`detail`, сбрасывает блоки сверх
  дневного кэпа.
- `add` — `_apply_add`: вставляет неиспользованного кандидата нужной категории; если в кандидатах
  нет — фоллбэк на MCP `find_places`. Рестораны берутся только из уже загруженного набора.
- `replace` — remove(`target`) + add(`detail`): убирает названное, добавляет замену.

Если правка ничего не изменила (`changed==0`), исходный rich-markdown сохраняется, но сверху
добавляется явная пометка «правка не нашла совпадений» (`_prepend_noop_notice`) — чтобы no-op не
выглядел как сбой. На пустой LLM-ответ — детерминированный fallback `_render_markdown` (bare).

### 4. Принятие

```
React accept button → POST /sessions/{id}/accept
  → Graph proceeds: finalize_and_export → END
  → PDF generated, stored in session
  → React redirects to GET /sessions/{id}/pdf for download
```

### 5. Навигация (frontend)

`App.tsx` показывает `Stepper` (Параметры → Генерация → Просмотр и правки → Готово) и кнопку
«← Изменить параметры». Шаг выводится из состояния: `!submitted→0`, `finalized→3`, `plan_markdown→2`,
иначе `1`. «Назад» (`startOver`) создаёт **новую сессию** (чистый checkpoint-thread — повторный запуск
на старом thread конфликтовал бы с сохранённым состоянием), сбрасывает прогресс/план и возвращает к
форме, предзаполненной последним вводом (`TripForm initialValues`). Это единственный способ начать
заново — граф вперёд-направленный, прыгать в запущенный/недостигнутый шаг нельзя.

## Зависимости между модулями (что от чего блокируется)

```
config.py (env)
    │
    ├──► llm/client.py
    ├──► rag/qdrant_client.py ◄── scripts/ingest_wikivoyage.py
    └──► mcp_clients/client.py ◄── mcp_servers/*/server.py
              │
              ▼
        graph/nodes/*  ──► graph/builder.py
                                  │
                                  ▼
                            api/sessions.py ──► main.py
                            api/stream.py
                            api/export.py
```

**Порядок имплементации** (исторический — проект уже собран):
1. config + llm/client (hello world)
2. Один MCP-сервер + один MCP-клиент
3. RAG ingestion + qdrant_client
4. Один полный путь графа (без HITL, без vision)
5. HITL + edit loop
6. Vision
7. PDF export

## Принципы устойчивости

- **Retries:** LLM-вызовы с экспоненциальным backoff (3 попытки, base 1s) через `tenacity` в `llm/client.py`.
- **Fallback:** mini → full (`gpt-4.1` / `gpt-4o`) при rate-limit/5xx (опционально, stretch goal).
- **Timeouts:** MCP tool-calls — 15s, LLM-вызовы — 60s.
- **Idempotency:** session_id — UUID, каждое действие графа checkpoint'ится в SQLite через LangGraph `AsyncSqliteSaver`.
- **SSE resilience (frontend):** EventSource — primary канал для прогресс-нодов, но `App.tsx` параллельно поллит `/state` каждые 3с пока сессия не finalized. Это страхует от транзиентных SSE-сбоев (прокси-буферизация, разрыв соединения), при которых план в backend готов, но event до клиента не дошёл.
- **SSE headers:** `api/stream.py` отправляет `X-Accel-Buffering: no` + `Cache-Control: no-cache, no-transform` чтобы запретить буферизацию у nginx и cloud-LB.
- **Event-queue drain:** при `start_run`/`resume_run` старые события вычищаются из `session.events` — новый SSE-клиент получает только свежие.

## Режим evals (EVAL_MODE)

Граф собран с HITL-прерываниями (`interrupt()` в `explain_and_ask` и `present_plan`). Во время автопрогона evals прерывания **должны автоматически приниматься**, иначе автопрогон зависнет.

Реализация (см. соответствующие nodes напрямую — не в builder):
- `config.py` объявляет флаг `EVAL_MODE: bool = False` (читается из env `EVAL_MODE=true`).
- `explain_and_ask.py` проверяет `settings.eval_mode` и при `True` возвращает `{budget_warning: None, budget_acknowledged: True}` вместо вызова `interrupt()`.
- `present_plan.py` аналогично — при `EVAL_MODE` сразу возвращает `accept`.
- `evals/run.py` устанавливает `os.environ["EVAL_MODE"]="true"` ДО импорта графа (важен порядок: настройки кэшируются через `@lru_cache`).

**Важно про `budget_acknowledged`:** без этого флага EVAL_MODE уходит в бесконечный цикл. Цепочка `explain_and_ask → city_research → candidate_places → budget_check → (warning снова) → explain_and_ask` повторяется бесконечно, потому что `candidate_places` детерминированно возвращает те же дорогие места. Флаг разрывает цикл: `budget_check` на втором проходе видит `budget_acknowledged=True` и сразу возвращает `budget_warning=None`, что заставляет `budget_feasible` уйти в `cluster_by_day`.

В production режиме (`EVAL_MODE=false`) — нормальные HITL прерывания, граф ждёт пользователя через `aresume`. Production-ветка `explain_and_ask` тоже ставит `budget_acknowledged=True` после `decision` от пользователя, чтобы logical behavior был одинаковый в обоих режимах.

## Что осознанно НЕ делаем

- **Auth.** Sessions хранятся анонимно по UUID. Нет логинов.
- **Persistence планов между сессиями.** Старые sessions можно периодически чистить cron'ом (не обязательно).
- **Multi-tenancy.** Один пользователь = один процесс работы.
- **Высокая нагрузка.** Один FastAPI-воркер, один экземпляр LangGraph. Дальнейшее масштабирование — out of scope.
