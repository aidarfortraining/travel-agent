# IMPLEMENTATION_PLAN.md

## Дедлайн и бюджет времени

- **Дедлайн:** среда 20 мая 2026, EOD.
- **Сегодня:** 18 мая (понедельник), вечер.
- **Реальное продуктивное время:** ~27–30 часов.

## Принцип: vertical slice сначала

К концу Дня 1 (19 мая, 23:00) у вас должен быть работающий end-to-end сценарий для **одного города (Стамбул), без vision, без правок** — форма → план → принятие → PDF.

Только после этого расширяем: vision, правки, второй и третий MCP-сервер, остальные города.

Это критично: если потратить понедельник на "продумывание архитектуры" вместо рабочего hello world — рискуете не успеть.

---

## День 0 — Понедельник 18 мая, вечер (5 часов)

### Цель
К концу вечера: рабочий скелет с hello-world LangGraph через FastAPI, трейс в LangSmith.

### План

| Время | Задача | Definition of done |
|---|---|---|
| 18:00–18:30 | GitHub repo, базовая структура папок согласно `ARCHITECTURE.md`, `.gitignore`, README-заглушка | `git push` прошёл |
| 18:30–19:00 | Получить ключи: OpenAI Platform, LangSmith. `.env.example` заполнен. Qdrant: либо Qdrant Cloud free tier, либо локально через docker-compose | `scripts/verify_setup.py` печатает "OK" по всем сервисам |
| 19:00–20:00 | `backend/`: FastAPI minimal (`main.py` + `/health`), `pyproject.toml` (uv preferred), `graph/builder.py` с тривиальным 2-нодным графом, `llm/client.py` с вызовом `gpt-4.1-mini`, проверить LangSmith trace | `curl /health` → 200; в LangSmith дашборде виден trace вызова mini |
| 20:00–21:00 | `frontend/`: Vite + React 19 + TS + Tailwind + shadcn init, одна страница с формой через react-hook-form (поля: city, days, budget, interests-multiselect, dietary-multiselect) | `npm run dev` показывает форму, валидация работает |
| 21:00–22:00 | `mcp_servers/travel-tools/`: скелет MCP-сервера, один tool `find_places(city, category)` через Overpass API (без ключа). Smoke test через CLI: `mcp dev server.py` | Можно вызвать tool из CLI и получить список POI Стамбула |
| 22:00–22:30 | `docker-compose.yml`: backend + qdrant + travel-tools server. Проверить `docker compose up` | Все три контейнера up, healthcheck'и зелёные |

### Чекпойнт 18 мая 22:30

Должно работать:
- [ ] `git push` на public/private репо
- [ ] `docker compose up` поднимает backend + qdrant + один MCP-сервер
- [ ] Форма на фронте отрисовывается и валидируется
- [ ] Hello-world LangGraph виден в LangSmith
- [ ] Один MCP tool вызывается и возвращает данные

Если хоть что-то не работает — **фиксить сейчас, не оставлять на завтра**.

---

## День 1 — Вторник 19 мая (12 часов продуктивно)

### Цель
К концу дня: работающий vertical slice для Стамбула. Форма → план → правка → принятие. Без vision, можно без PDF.

### Утро 09:00–13:00 (4 ч): RAG + 2 MCP-сервера

| Время | Задача | DoD |
|---|---|---|
| 09:00–10:30 | **RAG pipeline.** `scripts/ingest_wikivoyage.py`: скрейпит Wikivoyage страницу Стамбула, чанкует по секциям (`See`/`Do`/`Eat`/`Drink`/`Sleep`/`Get around`), embedded через `text-embedding-3-small`, upsert в Qdrant с метаданным `city="Istanbul"` | `python -c "from rag.qdrant_client import search; print(search('Istanbul', 'best mosque', k=5))"` возвращает 5 релевантных чанков |
| 10:30–11:30 | **MCP сервер 1 (`travel-tools`):** дописать 4 tool'а: `find_places`, `find_restaurants`, `get_weather` (Open-Meteo), `compute_route` (OSRM). См. `MCP_SERVERS.md` для сигнатур | `pytest mcp_servers/travel-tools/tests/` зелёный |
| 11:30–13:00 | **MCP сервер 2 (`city-knowledge`):** обернуть Qdrant как MCP. Tools: `search_city_guide`, `get_city_overview`, `list_indexed_cities`. Подключить оба сервера в LangGraph через `MultiServerMCPClient` | LangGraph-нода может вызвать оба сервера и получить результат |

### День 14:00–18:00 (4 ч): LangGraph + vision

| Время | Задача | DoD |
|---|---|---|
| 14:00–16:00 | **LangGraph: основной граф.** Реализовать ноды 1, 5–11 (без vision и правок пока): `collect_input`, `city_research`, `candidate_places`, `cluster_by_day` (sklearn KMeans), `optimize_route`, `generate_plan`. SqliteSaver checkpointing. State по схеме из ARCHITECTURE.md | Запрос "Стамбул, 3 дня, $300, history+food, halal" возвращает структурированный план через `await graph.ainvoke(...)` |
| 16:00–17:00 | **Vision-нода.** Эндпойнт `/sessions/{id}/photo` принимает multipart (≤5MB), декодирует в base64, вызывает `gpt-4.1-mini` с image content. Нода `vision_identify` интегрируется условно: если в state есть `photo_b64`, идём через неё | Загрузка фото Голубой Мечети возвращает `{landmark: "Blue Mosque", city: "Istanbul"}` |
| 17:00–18:00 | **MCP сервер 3 (`trip-utilities`):** `convert_currency`, `estimate_plan_cost`, `validate_dietary_match`. Если время поджимает — мерджить в `travel-tools` и фиксировать как "решение по упрощению" в ARCHITECTURE.md | Все 3 tool'а вызываются из графа |

### Вечер 19:00–23:00 (4 ч): фронт + Skill + edit loop

| Время | Задача | DoD |
|---|---|---|
| 19:00–20:30 | **React: live-прогресс.** `useGraphStream.ts` (EventSource), компонент `GraphProgress.tsx` показывает список нод со статусами. `PlanView.tsx` — карточки дней | Открыть форму → submit → видно прогресс по нодам → отрисован план |
| 20:30–21:30 | **Skill `itinerary-formatter`:** скопировать содержимое из `skill/itinerary-formatter/SKILL.md` (уже готов). Реализовать `llm/skill_loader.py` — читает SKILL.md и подставляет в system prompt ноды `generate_plan` | Сгенерированный план соответствует структуре из SKILL.md (Утро/День/Вечер, бюджет-таблица, dietary-теги) |
| 21:30–22:30 | **Edit loop.** Компонент `EditBox.tsx`. Backend: `/sessions/{id}/edit` → нода `parse_edit_intent` (Flash, structured output в `EditIntent` pydantic) → `patch_plan` (точечный апдейт state без полной регенерации) → возврат к interrupt | Запрос "убери музеи" удаляет только музеи, остальное остаётся. "Добавь халяль" увеличивает долю halal-ресторанов |
| 22:30–23:00 | **Commit, push, чекпойнт.** Обновить README со скриншотом текущего состояния | На GitHub в README виден скриншот |

### Чекпойнт 19 мая 23:00

Должно работать end-to-end для Стамбула:
- [ ] Форма → план собирается за разумное время (≤4 мин)
- [ ] План соответствует структуре из SKILL.md
- [ ] Текстовая правка применяется точечно
- [ ] LangSmith показывает полный trace с tool-calls
- [ ] Все 3 MCP-сервера живы и используются

**Если что-то критично сломано — План Дня 2 сдвигается на починку, не на расширение.** См. секцию "Если отстаём" ниже.

---

## День 2 — Среда 20 мая (10–12 часов до сдачи)

### Цель
Evals, расширение до 5 городов, документация, презентация, сдача. **Никакого нового функционала после 13:00.**

### Утро 09:00–13:00 (4 ч): evals + расширение

| Время | Задача | DoD |
|---|---|---|
| 09:00–10:00 | **Golden dataset 10 примеров.** `evals/dataset.jsonl` ровно по таблице из EVALS_PLAN.md (распределение готово). Использовать `gpt-4.1-mini` для черновика, ручная вычитка обязательна | Файл существует, ровно 10 строк, все поля валидны |
| 10:00–11:00 | **Evals автопрогон.** `evals/run.py` через `langsmith.evaluate`. Две метрики из `evals/judges/`. Запуск, фикс багов | Команда `python evals/run.py` прогоняет 10 примеров, выводит таблицу метрик |
| 11:00–13:00 | **A/B эксперимент.** Тот же датасет, два arms: Pro в `generate_plan`+`parse_edit_intent` (temp 0.7) vs Flash в тех же двух нодах (temp 0.7). Остальные ноды одинаковые Pro. Результаты в `evals/results/ab_pro_vs_flash.md`. Stretch — третий arm Qwen | Файл с таблицей метрик по обоим arms и текстовым выводом |

### Обед-день 13:00–16:00 (3 ч): polish

| Время | Задача | DoD |
|---|---|---|
| 13:00–14:00 | **Расширение RAG до 5 городов:** Barcelona, Lisbon, Tokyo, Mexico City. Запустить `python scripts/ingest_wikivoyage.py --cities Barcelona Lisbon Tokyo "Mexico City"` (argparse `nargs="+"`, города через пробел; "Mexico City" в кавычках) | В Qdrant 5 индексированных городов, `list_indexed_cities` возвращает 5 |
| 14:00–15:00 | **PDF-экспорт.** `export/pdf.py` через weasyprint от итогового маркдауна. Эндпойнт `GET /sessions/{id}/pdf`. Кнопка "Скачать план" на фронте | Принятый план скачивается PDF-файлом, выглядит читаемо |
| 15:00–16:00 | **Polish.** Try/except на rate-limit `gpt-4.1-mini` → fallback на `gpt-4o-mini`. Обработка edge case'ов (нет данных по городу → внятное сообщение). E2E прогон ещё раз | Запись 2-минутного screencast'a демо |

### Вечер 16:00–22:00 (6 ч): docs + презентация + сдача

| Время | Задача | DoD |
|---|---|---|
| 16:00–17:30 | **README.md:** описание, 3–4 скриншота, архитектурная картинка (PNG из Excalidraw), команда запуска, ссылка на screencast | README просматривается, скриншоты загружены в репо |
| 17:30–18:30 | **ARCHITECTURE.md** в репо: финальная диаграмма (из этого файла), обоснование OpenAI mini (из PROJECT_SPEC.md), обоснование гиперпараметров | Файл в `docs/` репо |
| 18:30–19:30 | **EVALS.md** в репо: структура датасета, описание метрик, таблица A/B результатов с выводами в стиле "Pro выигрывает на faithfulness на 12%, Flash в 8× дешевле, рекомендация — Pro для генерации, Flash для intent parsing" | Файл в `docs/` репо |
| 19:30–21:30 | **Презентация 10–15 слайдов:** проблема → решение → user flow (3 скриншота) → архитектурная картинка → MCP-серверы (1 слайд на каждый) → Skill (1 слайд) → evals + A/B (2 слайда) → обоснование выбора LLM → что бы сделал дальше. Google Slides → экспорт в PDF | PDF презентации в репо `docs/presentation.pdf` |
| 21:30–22:00 | **Финальный чек-лист самопроверки** (из спеки курса, п. 8). `git push`. Скриншот LangSmith дашборда в репо. **Сдача артефактов менторам** | Все галочки в чек-листе зелёные |
| 22:00 | Черновик LinkedIn-поста (опубликовать после защиты) | Текст готов |

---

## Что выбрасываем, если отстаём

Заранее проговорённые планы B по каждой точке отставания. **Решение принимать СРАЗУ**, не "ещё час и доделаю".

| Точка отставания | План B |
|---|---|
| Конец Дня 0 — нет рабочего hello-world LangGraph | Отдых 4 часа, до 02:00 фиксить. Дальше сдвиг фатален. |
| Утро Дня 1 — RAG не работает | "Stuff context": целая страница Wikivoyage в промпт (gpt-4.1 держит 1M токенов; mini-вариант 128K — достаточно для одного города). Qdrant остаётся с минимальным city-overview документом. В EVALS.md явно прописать: "RAG деградировал до stuff-context из-за времени". |
| День 1 вечер — фронт React не готов | **Переключиться на Streamlit** для записи демо. Принять штраф по чек-листу. Указать в README как known limitation. Это плохо, но не блокирует допуск. |
| День 2 утром — vision не работает | "Mock vision": загруженное фото → `gpt-4.1-mini` смотрит → возвращает текстовое описание (не landmark identification). Требование мультимодальности формально закрыто. |
| День 2 после обеда — evals не доделаны | Базовый план уже на 10 примерах (минимум по чек-листу). Дальше срезать нельзя — это блокер допуска. Вариант: уменьшить **глубину** оценки (одна метрика вместо двух) или **одно arm A/B** вместо двух, но это серьёзный риск. **Согласовать с менторами обязательно.** |
| День 2 вечер — презентация не готова | Жертвовать PDF-экспортом и расширением до 5 городов. Презентация важнее. |
| Любая стадия — кто-то требует "ещё одну фичу" | Отказать. Дедлайн фиксированный, scope замороженный. |

---

## Definition of Done всего проекта

**Текущий статус (на 20 мая 2026):** проект работает end-to-end, evals прогнаны, готов к сдаче. Verified e2e через Playwright: форма → SSE-прогресс по нодам → план с реальными местами из OSM + halal-маркерами + погодой → правка → accept → PDF. A/B evals прогнан, отчёт в `evals/results/ab_mini_41_vs_4o.md`.

Чек-лист финальной самопроверки:

### Допуск к защите (обязательное)

- [ ] GitHub-репо доступен менторам, последний commit ≤ дедлайна
- [x] README с инструкцией запуска (`docker compose up`)
- [x] `docker compose up` действительно работает (qdrant + backend + frontend; MCP-серверы — stdio-subprocess'ы backend'а)
- [x] LangGraph workflow с ≥ 1 ветвлением, ≥ 1 циклом, ≥ 1 HITL — у нас 3 ветвления (`has_photo`, `budget_feasible`, `edit_or_accept`), 2 цикла (`explain_and_ask`↔`budget_check`, `parse_edit_intent`↔`present_plan`), 2 HITL (`explain_and_ask`, `present_plan`)
- [x] ≥ 1 свой MCP-сервер с ≥ 2 содержательными tools — у нас 3 сервера: `travel-tools` (4 tools), `city-knowledge` (3), `trip-utilities` (3) = 10 tools
- [x] SKILL.md по стандарту в `skill/itinerary-formatter/`
- [x] RAG с обоснованным выбором (chunking, embedding, Qdrant) — обоснование в ARCHITECTURE.md
- [x] Скрапинг документов (Wikivoyage через `scripts/ingest_wikivoyage.py`)
- [x] Мультимодальность (vision на фото через `vision_identify`)
- [x] LangSmith трейсы — projects `mini-41-8980574a`, `mini-4o-ebf8458a`, dataset `trip-planner-golden-v1`
- [x] Golden dataset 10 примеров (по чек-листу спеки курса п. 8; противоречие с п. 3.3 "не менее 30" зафиксировано в EVALS_PLAN.md как известное ограничение)
- [x] ≥ 2 метрики (`constraint_adherence`, `faithfulness`), автопрогон через `evals/run.py`
- [x] A/B эксперимент с выводами — `evals/results/ab_mini_41_vs_4o.md`
- [x] Обоснование выбора LLM и гиперпараметров (PROJECT_SPEC.md)
- [x] Веб-фронтенд (React 19 + Vite + Tailwind + shadcn/ui)
- [ ] Презентация 10–15 слайдов (PDF в репо) — финальный артефакт

### Рекомендуемое (бонус к оценке)

- [x] Docker-контейнеризация (`docker compose up` поднимает qdrant + backend + frontend)
- [x] PDF-экспорт плана (weasyprint, проверено через Playwright — 53KB валидный PDF 1.7)
- [x] Resilience: retry/backoff для Overpass (5 попыток × 3 зеркала); SSE polling-fallback на `/state` каждые 3с
- [x] Tests: 10 backend tests + 5 MCP tests (3 network-skipped) = 15 passed
- [ ] Fallback `gpt-4.1-mini` → `gpt-4o-mini` при rate-limit (не реализован — evals показали что `gpt-4o-mini` тонет на faithfulness, fallback нежелателен)
- [ ] Render deploy
- [ ] LinkedIn-пост (после защиты)

### После защиты

- [ ] LinkedIn-пост опубликован с тегом курса
