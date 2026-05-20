# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Этот файл Claude Code читает в начале каждой сессии. Здесь — только то, что нужно знать сразу. Детали в `docs/`.

## Проект — Trip Planner

**Trip Planner** — веб-приложение, которое собирает персонализированный day-by-day план поездки. Пользователь вводит город, дни, бюджет, интересы, dietary restrictions; опционально загружает фото места. LLM-агент собирает черновик, принимает текстовые правки ("убери музеи", "добавь халяль"), экспортирует PDF.

**Это учебный проект.** Дедлайн: **20 мая 2026, EOD**. Цель — научиться использовать LLM-стек (LangGraph, MCP, RAG, evals), а не построить продакшен-сервис.

**Статус кода:** проект **реализован, протестирован и готов к сдаче** на 20 мая 2026. Stack поднимается через `docker compose up`, e2e-флоу (форма → план → правка → accept → PDF) проверен через Playwright, evals A/B прогнан (`evals/results/ab_mini_41_vs_4o.md`). Список фиксов из последнего цикла отладки — в "Известных ловушках" ниже.

## Архитектура (краткий снимок)

Три процессных границы, поднимаются одним `docker compose up`:

- **Backend** (`backend/`, FastAPI + LangGraph) — оркестрация графа из 14 нод (3 ветвления, 2 цикла, 2 HITL-прерывания через `interrupt()` в `explain_and_ask` и `present_plan`), AsyncSqliteSaver checkpointing, SSE для live-прогресса в UI.
- **3 MCP-сервера** (`mcp_servers/`, stdio-subprocess'ы backend'а, НЕ отдельные docker-сервисы): `travel-tools` (Overpass/Open-Meteo/OSRM, 4 tools), `city-knowledge` (Qdrant wrapper, 3 tools), `trip-utilities` (currency/cost/dietary, 3 tools). Подключаются через `MultiServerMCPClient` из `langchain-mcp-adapters`. `docker-compose.yml` определяет только qdrant + backend + frontend; MCP-серверы спавнятся как subprocess'ы backend'а при первом запросе (см. `mcp_clients/client.py`).
- **Frontend** (`frontend/`, Vite + React 19) — форма (react-hook-form + zod), SSE-прогресс по нодам, view плана, PDF download.

**LLM-роли (OpenAI-only):**
- Primary: **`gpt-4.1-mini`** (env `OPENAI_MODEL`) — используется ВЕЗДЕ: `generate_plan`, `vision_identify`, `parse_edit_intent` (через `with_structured_output`), LLM-as-judge, HITL `explain_and_ask`, `finalize_and_export`. Single-model подход — проще и дешевле, чем Pro/Flash split.
- Secondary: **`gpt-4o-mini`** (env `OPENAI_MODEL_B`) — используется ТОЛЬКО как второй arm в A/B-evals.

**RAG:** Wikivoyage → chunking по секциям (See/Do/Eat/Drink/Sleep/Get around) → `text-embedding-3-small` (1536-dim) → Qdrant. **Одна коллекция на все города**, фильтр по metadata-полю `city` — НЕ по коллекции на город.

**Pydantic-границы:** все state-модели в `backend/src/schemas/`. MCP-серверы — отдельные процессы и **не импортируют** этот пакет; они дублируют pydantic-классы локально в `mcp_servers/<name>/schemas.py`. На границе MCP передаётся JSON, идентичность Python-классов не нужна.

**LangSmith** трассирует всё автоматически через env (`LANGSMITH_TRACING=true`) — изменения в коде графа не требуются.

**`EVAL_MODE=true`** обходит HITL-прерывания в `explain_and_ask` и `present_plan` — критично для автопрогона evals, иначе `langsmith.evaluate` зависнет на `interrupt()`. В EVAL_MODE `explain_and_ask` дополнительно ставит `state.budget_acknowledged=True` чтобы `budget_check` на следующем проходе не выставил предупреждение повторно (иначе бесконечный цикл `explain_and_ask → city_research → candidate_places → budget_check → explain_and_ask`).

## Команды

Все команды — из корня репо.

```bash
# Setup
cp .env.example .env                  # заполнить OPENAI_API_KEY, LANGSMITH_API_KEY, QDRANT_URL/QDRANT_API_KEY
python scripts/verify_setup.py        # sanity-check OpenAI/LangSmith/Qdrant/MCP-серверов;
                                      # Qdrant должен быть доступен (либо docker compose up qdrant, либо managed)

# RAG: первичное наполнение индекса (один раз). Города через пробел, multi-word — в кавычках.
docker compose run --rm backend python scripts/ingest_wikivoyage.py \
  --cities Istanbul Barcelona Lisbon Tokyo "Mexico City"

# Запуск всего стека
docker compose up                     # qdrant + backend (спавнит 3 MCP-stdio-subprocess'а) + frontend

# Локальные итерации (без docker)
cd backend && uv run uvicorn src.main:app --reload
cd frontend && npm run dev

# Тесты
pytest backend/tests/                 # граф smoke + patch_plan + PDF + RAG (10 тестов)
pytest mcp_servers/                   # все 3 MCP-сервера; сетевые тесты skipped по умолчанию —
                                      # SKIP_NETWORK_TESTS=0 pytest mcp_servers/travel-tools/tests/
pytest backend/tests/test_graph_smoke.py::test_state_imports   # одиночный тест

# Lint / type-check
ruff check backend/ scripts/ evals/ mcp_servers/      # backend lint (ruff в dev deps)
cd frontend && npm run build                          # tsc -b + vite build (type-check входит)

# Eval mode: обходит HITL `interrupt()` в `explain_and_ask` и `present_plan`
# — обязателен для evals и любого автопрогона графа end-to-end без UI.
EVAL_MODE=true python evals/run.py

# Evals (A/B: gpt-4.1-mini vs gpt-4o-mini)
python evals/upload_dataset.py                                                    # one-time push dataset.jsonl в LangSmith
EVAL_MODE=true OPENAI_MODEL=gpt-4.1-mini python evals/run.py --experiment-prefix mini-41
EVAL_MODE=true OPENAI_MODEL=gpt-4o-mini  python evals/run.py --experiment-prefix mini-4o
python evals/compare_experiments.py --a mini-41 --b mini-4o \
  --out evals/results/ab_mini_41_vs_4o.md
```

После `docker compose up`: frontend → http://localhost:5173, backend → http://localhost:8000, Qdrant dashboard → http://localhost:6333/dashboard.

## Документы (читать в этом порядке)

1. `docs/PROJECT_SPEC.md` — что строим, требования, tech stack
2. `docs/ARCHITECTURE.md` — компоненты, LangGraph-граф, структура репо
3. `docs/IMPLEMENTATION_PLAN.md` — почасовой 48-часовой план
4. `docs/MCP_SERVERS.md` — спеки трёх MCP-серверов
5. `docs/EVALS_PLAN.md` — golden dataset и метрики
6. `skill/itinerary-formatter/SKILL.md` — готовый Skill проекта

## Жёсткие ограничения (не отклоняться без явного разрешения)

- **Backend:** Python 3.11+, FastAPI, LangGraph, LangSmith, Qdrant
- **Frontend:** Vite + React 19 + TypeScript + Tailwind + shadcn/ui
- **LLM провайдер:** ТОЛЬКО OpenAI. Primary — `gpt-4.1-mini` (env `OPENAI_MODEL`). Secondary mini `gpt-4o-mini` — только для A/B-evals (`OPENAI_MODEL_B`).
- **Никаких других LLM-провайдеров** (Anthropic, Google Gemini, Qwen и т.д.) без явного запроса.
- **Out of scope для v1:** auth, CI/CD, semantic cache, voice. Не реализовывать, даже если есть время.
- **Деплой:** `docker compose up` должен запускать весь стек одной командой. Render — опционально.

## Соглашения

- Код: английские идентификаторы, комментарии на английском.
- Документы и commit messages: русский или английский (выбирайте по контексту).
- Пользовательские строки в UI: русский.
- Все pydantic-модели для данных, пересекающих границы процессов.
- Все вызовы LLM — через единый `backend/src/llm/client.py`: он содержит retry/backoff (tenacity, 3 попытки) и LangSmith-обёртку. Не инстанцируйте `ChatOpenAI` напрямую в нодах.
- Ошибки возвращаются как структурированный ответ, а не сырое исключение.
- Никаких эмодзи в коде или документах. Единственное исключение — SKILL.md `itinerary-formatter`: 🟢/🟡 для dietary-маркеров ресторанов и ⚠ для предупреждений (превышение бюджета, отсутствие гайда). Эти эмодзи функциональны — пользователь сканирует план по ним.

## Когда спрашивать пользователя

Спросить перед:
- Добавлением любой зависимости, не упомянутой в `docs/PROJECT_SPEC.md`.
- Пропуском обязательного требования из спеки курса (см. `docs/PROJECT_SPEC.md`, секция "Mandatory requirements mapping").
- Принципиальным изменением архитектуры (другая БД, другая модель, перенос ответственности между сервисами).
- Тратой больше 1 часа на один pending шаг без прогресса.

В остальных случаях — действовать. Дедлайн жёсткий, рабочий код > обсуждения.

## Verification gate

После реализации любого модуля:
1. Запустить тесты в `backend/tests/` (если затронут backend).
2. Проверить, что трейс появляется в LangSmith.
3. Прогнать e2e-сценарий из `IMPLEMENTATION_PLAN.md` (Checkpoint того дня).

Не помечать задачу completed без всех трёх проверок.

## Известные ловушки

- **`qdrant-client.search()` удалён в ≥1.18:** старый код в `city-knowledge/server.py` падал на `AttributeError`. Используем `query_points(query=vector, query_filter=..., limit=...)` и итерируем по `res.points` (а не по `res`).
- **Overpass нестабилен:** main endpoint регулярно отдаёт 504. `mcp_servers/travel-tools/_overpass_query` крутит 5 попыток через 3 зеркала (`overpass-api.de`, `overpass.kumi.systems`, `overpass.private.coffee`) с экспоненциальным backoff. НЕ ходить в Overpass без этой обёртки.
- **`patch_plan` сохраняет rich-markdown на no-op:** если правка не удалила ни одного блока (например `target="музеи"` для дня без музеев), `_render_markdown` НЕ перезаписывает `state.plan_markdown` — иначе богатый LLM-вывод (погода/halal-маркеры/таблица/источники) теряется. Контролируется счётчиком `changed` из `_apply_remove`/`_apply_constrain`.
- **`patch_plan` matcher по `TimeBlock.notes`, не по `place_type`:** generate_plan кладёт `p.category` ("museum"/"historical"/"park"...) в `TimeBlock.notes`. `_apply_remove` берёт cat из notes (а не из `place_type="attraction"`) — иначе тюркские/иностранные названия типа "Müzesi" не матчатся. Ключи `REMOVE_KEYWORDS` — стемы ("музе", "истори"), а не точные слова — покрывает плюрали и инфлекции.
- **EVAL_MODE бесконечный цикл (исправлено):** `explain_and_ask` в `EVAL_MODE` должен ставить `state.budget_acknowledged=True` (а не только `budget_warning=None`), иначе следующий `budget_check` повторит warning, и граф уйдёт в цикл `explain_and_ask → city_research → candidate_places → budget_check → explain_and_ask`. Production-ветки `explain_and_ask` тоже ставят флаг.
- **`langsmith.evaluate()` не поддерживает async evaluators:** запускает их в `ThreadPoolExecutor` без event loop → `RuntimeError: no current event loop`. Sync-обёртки в `evals/judges/__init__.py` оборачивают `asyncio.run()`. НЕ передавать async-judge в `evaluate()` напрямую.
- **`graph.ainvoke()` возвращает dict-of-mixed-types, не plain dict:** top-level — dict, но nested pydantic-модели (`plan_cost_breakdown: CostBreakdown`, `tool_calls_aggregated[i]`) остаются как pydantic-объекты. `evals/run.py` дампит их через `model_dump()` вручную; `.get()` на CostBreakdown падает.
- **`evaluate(experiment_prefix=X)` создаёт проект с суффиксом `X-<8 chars>`:** `compare_experiments._resolve_project` ищет последний LangSmith-проект, чьё имя начинается с префикса (через `startswith`). Точный lookup по `prefix` упадёт `LangSmithNotFoundError`.
- **Hallucinated places:** LLM выдумывает рестораны. Все названия мест/заведений — ТОЛЬКО из RAG-контекста или tool-output. Жёсткий запрет в system prompt.
- **OpenAI rate limits:** на платном tier mini-модели имеют 30k+ RPM, evals на 10 примерах укладываются без проблем. Exponential backoff (3 попытки, base 1s) встроен в `llm/client.py` — на случай TPM-пиков и 5xx.
- **OpenAI cost:** mini-модели дешёвые, но не бесплатные. Evals на 10 примерах × 2 метрики × 2 arms ≈ $0.5–2 в зависимости от длины планов.
- **`OPENAI_BASE_URL=""` ломает SDK:** пустая строка читается openai SDK как URL → `httpx.UnsupportedProtocol`. В `config.py` пустая переменная удаляется из `os.environ` до импорта SDK; в `.env.example` строка закомментирована. То же для env, передаваемого в MCP-subprocess (`mcp_clients/client.py` пропускает пустые значения).
- **`langchain-mcp-adapters` оборачивает результат tool'а** в `[{"type":"text","text":"<json>"}]`. В `mcp_clients/client.py` хелперы `call_tool` (single result) и `call_tool_list` (list result) делают `_unwrap_mcp_result` и парсят JSON. Ноды НЕ должны вызывать `tool.ainvoke()` напрямую.
- **LLM иногда оборачивает план в ` ```markdown ... ``` `** — `_strip_outer_fence` в `generate_plan.py` снимает обёртку, иначе ReactMarkdown рендерит весь план как code-block.
- **`#` в URL EventSource — фрагмент**, обрезается браузером перед HTTP. Не использовать `${sessionId}#${streamKey}` как идентификатор стрима — передавайте `streamKey` отдельным параметром в `useGraphStream`, добавлять в deps useEffect.
- **`onerror` у EventSource не сигнал об окончании** — может срабатывать на промежуточные сбои. В `useGraphStream` обработчик `onerror` теперь no-op; `closed=true` выставляется ТОЛЬКО при явном `done`/`error`/`interrupt` событии от сервера. Дополнительно — фронт поллит `/state` каждые 3с как resilient fallback.
- **`X-Accel-Buffering: no`** обязательно на SSE-ответе (`api/stream.py`) — без него nginx/cloud-LB могут буферизовать стрим и удерживать события.
- **React StrictMode удалён** из `frontend/src/main.tsx` — в dev-режиме он дважды mount'ит компоненты, что создавало two parallel EventSource connections. В production это no-op, но удаление гарантирует одинаковое поведение.
- **LangGraph + async:** граф запускается асинхронно (`await graph.ainvoke(...)`). Все I/O (LLM-вызовы, MCP-tool calls, HTTP) — async. Чистые CPU-bound функции (KMeans-кластеризация, patch_plan) могут быть sync — LangGraph поддерживает обе формы в одном графе.
- **Qdrant collections:** одна коллекция на все города с metadata-фильтром по `city`. НЕ создавать по коллекции на город. Vector dim = 1536 (`text-embedding-3-small`) — если меняете embedding-модель, коллекцию нужно пересоздать с новой размерностью.
- **Path в скриптах:** `scripts/` и `evals/` используют auto-detect двух layout'ов: docker (`/app/src/...`) и local (`PROJECT_ROOT/backend/src/...`). НЕ хардкодить `PROJECT_ROOT / "backend"`.
- **`verify_setup.py` использует `settings.mcp_servers_root` и `settings.skill_root`** для поиска файлов — это правильный путь для обоих layout'ов (в docker `/mcp_servers` смонтирован в корень, не в `/app/`).
- **pytest MCP-tests коллизия имён `server`/`schemas`:** три MCP-сервера имеют одноимённые модули. `pytest mcp_servers/` без обхода тащит первый загруженный и ломается на чужих символах. Тесты грузят свой `server.py` через `importlib.util.spec_from_file_location` под уникальным именем (`travel_tools_server`, `trip_utilities_server`, `city_knowledge_server`); перед загрузкой `sys.modules.pop("server"/"schemas")` и поднимают _SERVER_DIR в `sys.path[0]`.
- **pandas обязателен для evals:** `evals/run.py` дампит результаты через `result.to_pandas().to_csv()`. Образ backend ставит `pandas` через `pip install pandas` (см. README → Tests/evals); не в `backend/pyproject.toml` — только под eval-workflow.
