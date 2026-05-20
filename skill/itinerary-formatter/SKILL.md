---
name: itinerary-formatter
description: Formats a structured day-by-day trip plan into a consistent, readable markdown output suitable for both UI display and PDF export. Use this skill whenever a multi-day travel itinerary needs to be rendered from a structured Plan object, when re-rendering after user edits, or when preparing the plan for final PDF export. The skill enforces consistent time blocking (Morning / Afternoon / Evening), transitions between places, a budget summary table, dietary annotations, weather hints, and source citations.
triggers:
  - generating a day-by-day travel itinerary
  - re-rendering an itinerary after user edits
  - preparing plan content for PDF export
  - converting a Plan pydantic object into user-facing markdown
---

# itinerary-formatter

## Purpose

Превратить структурированный `Plan` объект (см. `backend/src/schemas/plan.py`) в консистентный, читаемый markdown с фиксированным форматированием. Один формат для UI и для PDF — никаких разветвлений.

## When this skill applies

Skill вызывается в двух нодах LangGraph:
1. `generate_plan` — первая генерация плана из RAG-контекста и tool-результатов.
2. `finalize_and_export` — финальная подготовка к PDF (тот же формат, но без интерактивных элементов).

## Hard rules (несоблюдение = провал)

1. **Никогда не упоминай место, которого нет в переданном контексте.** Контекст — это:
   - `state.candidate_places` (из MCP `travel-tools.find_places`)
   - `state.candidate_restaurants` (из MCP `travel-tools.find_restaurants`)
   - `state.city_context` (из MCP `city-knowledge.search_city_guide`)
   
   Если нужно место, которого нет в контексте — НЕ выдумывай его, скажи "в этот блок не нашли подходящего варианта".

2. **Каждое упомянутое место содержит ссылку на источник** в формате `[название](source_url)`. Источник берётся из `osm_id` (для POI/restaurants — ссылка на OpenStreetMap node) или `source_url` (для guide-chunks — ссылка на Wikivoyage).

3. **Никогда не выдумывай цены, часы работы, рейтинги.** Только из tool-output. Если данных нет — пиши "цена: не указана" или "часы: проверьте на сайте".

4. **Соблюдай dietary restrictions буквально.** Если в state есть `dietary=["halal"]`, ни один ресторан без `dietary_confidence >= 0.5` для halal не должен попасть в план.

5. **Не превышай суточный бюджет.** Суточный бюджет = `state.budget_usd / state.days`. Если сумма по дню > бюджета — заменяй на более дешёвые альтернативы из `candidate_places` или явно помечай "превышение бюджета: $X" в конце дня.

## Output structure (строго следовать)

### Шапка плана

```markdown
# Поездка в {city}, {days} дней

**Бюджет:** ${budget_usd} ({budget_per_day} в день)  
**Интересы:** {interests joined by ", "}  
**Пищевые ограничения:** {dietary joined by ", " or "нет"}  
**Лучший сезон для посещения:** {city_overview.best_season}  
**Валюта на месте:** {city_overview.currency}

> {city_overview.transport_summary краткий пересказ в 1-2 предложения}
```

### Блок дня

Один заголовок на день. Внутри — три тайм-блока: Утро (09:00–13:00), День (13:00–18:00), Вечер (18:00+).

**Маппинг погоды:** `state.weather` — это `WeatherDaily` со списком `entries`. Для Дня N бери `state.weather.entries[N-1]`. Если `entries` короче чем `state.days` (Open-Meteo не дал прогноз на этот день, или `is_forecast=False`) — пропусти строку с погодой для этого дня.

```markdown
## День {N}{ — date if available}

> {погода: entries[N-1].weather_desc, {temp_min_c}°—{temp_max_c}°C, {precipitation_mm}мм осадков}

### Утро (09:00–13:00)

**{HH:MM} — [{place_name}]({source_url})**  
{Категория: тип места, например "Музей" / "Смотровая" / "Парк"}  
{1-2 предложения почему стоит посетить — на основе текста из city_context, не выдумывать}  
*Длительность визита:* {estimated_visit_minutes} мин  
*Стоимость:* ${estimated_cost_usd} {если 0 — писать "бесплатно"}

→ {способ перехода и время в пути до следующей точки, например "10 мин пешком" / "15 мин на метро"}

**{HH:MM} — [{next place}]({source_url})**  
... (структура повторяется)

### День (13:00–18:00)

(тот же формат)

### Вечер (18:00–)

(тот же формат)

---

**Итого за день:** ${day_total_usd} {из бюджета ${budget_per_day}}  
{Если превышение бюджета — добавить: "⚠ Превышение бюджета на $X. Можно заменить {место} на {альтернативу}." }
```

### Сводная таблица бюджета (один раз, в конце)

```markdown
## Сводный бюджет

| День | Достопримечательности | Рестораны | Транспорт | Итого |
|------|----------------------|-----------|-----------|-------|
| День 1 | $X | $Y | $Z | $T |
| День 2 | ... | ... | ... | ... |
| **Всего** | **$X** | **$Y** | **$Z** | **$T** |

Из заложенного бюджета **${budget_usd}** — {use_percentage}% использовано.
```

### Финальная секция

```markdown
## Что взять с собой

{1-3 пункта на основе weather и interests, например: "зонт", "удобная обувь для прогулок", "наличные TRY для уличной еды"}

## Источники

План собран на основе:
- Wikivoyage: {list of unique source_urls from city_context}
- OpenStreetMap: {place names with osm_id links}
- Open-Meteo для прогноза погоды
```

## Dietary annotations

Когда ресторан включён в план и `state.dietary` непустой:

- Если `dietary_confidence == 1.0` (явный тег OSM) → `🟢 халяль (подтверждено)`
- Если `0.5 <= dietary_confidence < 1.0` (soft match по кухне) → `🟡 халяль (вероятно — кухня {cuisine})`
- Никогда не добавляй ресторан без хотя бы 0.5 confidence.

(Эмодзи здесь оправданы — это маркеры для быстрого сканирования пользователем, не декорация.)

## Edge cases

### Город не в индексе

Если `city_context` пустой (город не индексирован):
1. В шапке добавить: `> ⚠ Для этого города у нас нет детального гайда. План построен только на POI из OpenStreetMap и общем туристическом контексте.`
2. Не выдумывать факты про культуру/историю города.

### Бюджет недостижим

Если даже с самыми дешёвыми вариантами `day_total > budget_per_day` всегда:
1. Построить план "как есть" с самыми дешёвыми опциями.
2. В конце добавить:
   ```markdown
   ## ⚠ Бюджет
   Реалистичный минимум для этой поездки — **${actual_min}** ($Δ выше заявленного бюджета).
   Возможные решения: сократить дни / убрать некоторые достопримечательности / выбрать другой город.
   ```

### Нет фото-инфы (vision не использовалась)

Просто не упоминать landmark из фото. Никаких "ваше фото показало...".

### Vision определила место, но его нет в OSM

В шапке после интересов добавить:
```markdown
**Особое место в плане:** вы загрузили фото — мы определили это как **{landmark}**. Включили его в День {N}.
```

## Example output (fragment)

Для запроса "Стамбул, 3 дня, $300, history+food, halal":

```markdown
# Поездка в Istanbul, 3 дня

**Бюджет:** $300 ($100 в день)  
**Интересы:** history, food  
**Пищевые ограничения:** halal  
**Лучший сезон для посещения:** Apr–Jun, Sep–Oct  
**Валюта на месте:** TRY

> Стамбул компактен в туристической зоне Султанахмет; метро и трамвай покрывают основные точки, такси доступны.

## День 1

> погода: Sunny, 18°–24°C, 0мм осадков

### Утро (09:00–13:00)

**09:00 — [Hagia Sophia](https://www.openstreetmap.org/node/123456789)**  
Музей / историческая мечеть  
Бывший византийский собор, перестроенный в мечеть; сочетание христианской и исламской архитектуры в одном здании.  
*Длительность визита:* 120 мин  
*Стоимость:* $25

→ 5 мин пешком до Голубой мечети

**11:15 — [Blue Mosque](https://www.openstreetmap.org/node/987654321)**  
Религиозный объект  
Действующая мечеть с шестью минаретами, известна синей плиткой Изник.  
*Длительность визита:* 60 мин  
*Стоимость:* бесплатно

### День (13:00–18:00)

**13:30 — [Hamdi Restaurant](https://www.openstreetmap.org/node/...)**  🟢 халяль (подтверждено)  
Турецкая кухня, средний ценник  
Известен кебабами и видом на Золотой Рог.  
*Стоимость обеда:* $20

→ 8 мин пешком

**15:00 — [Grand Bazaar](https://www.openstreetmap.org/node/...)**  
Исторический рынок  
Один из старейших крытых рынков мира.  
*Длительность визита:* 90 мин  
*Стоимость:* бесплатно (вход)

### Вечер (18:00–)

**19:30 — [Ciya Sofrasi](https://www.openstreetmap.org/node/...)**  🟡 халяль (вероятно — кухня turkish)  
Региональная турецкая кухня  
Известен анатолийскими блюдами.  
*Стоимость ужина:* $25

---

**Итого за день:** $70 (из бюджета $100)

## День 2
...
```

## Verification checklist (агент проверяет себя перед возвратом)

- [ ] Каждое название места — кликабельная ссылка на источник.
- [ ] Все цены — из tool-output, не выдуманы.
- [ ] Все рестораны имеют dietary-маркер.
- [ ] Суммы за день добавлены, итоговая таблица бюджета есть.
- [ ] Погода упомянута в каждом дне.
- [ ] Структура утро/день/вечер соблюдена везде.
- [ ] Источники перечислены в конце.

Если хоть один пункт не выполнен — переделать перед возвратом из ноды.
