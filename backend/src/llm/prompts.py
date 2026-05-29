"""All LLM prompts as constants. Single place to tune wording."""
from __future__ import annotations

VISION_IDENTIFY_SYSTEM = """You analyze user-uploaded travel photos. Identify the landmark or place \
visible in the image. Be conservative — if uncertain, lower the confidence score.

Return STRICT JSON matching this schema, no commentary:
{
  "landmark": "<official name in English>",
  "city": "<city where this landmark is located>",
  "place_type": "religious|viewpoint|museum|park|historical|shopping|nightlife|other",
  "description": "<one-two sentence factual description>",
  "confidence": 0.0-1.0
}

Never invent names. If unsure, set landmark to a generic descriptor (e.g. "European old town square") \
and confidence ≤ 0.4."""

EDIT_INTENT_SYSTEM = """You parse a user's free-form edit request to a travel itinerary into a structured action.

Categories:
- "remove": user wants to remove a category or specific items ("убери музеи", "no nightlife")
- "add": user wants more of something ("больше еды", "add street food", "halal options")
- "replace": swap one thing for another ("вместо музея — парк", "replace dinner with brunch")
- "constrain": new global constraint ("only walking distance", "максимум $40 в день на еду")

Output STRICT JSON:
{
  "action": "remove|add|replace|constrain",
  "target": "<short noun phrase identifying what is affected>",
  "detail": "<optional clarifying detail, or null>",
  "raw_text": "<original user message>"
}"""

GENERATE_PLAN_SYSTEM_TEMPLATE = """You are an expert travel planner producing a day-by-day itinerary.

You MUST follow the formatting rules in the embedded SKILL below VERBATIM. Output ONLY the rendered \
markdown plan — no preamble, no JSON, no apology. Do NOT wrap the response in a ```markdown ... ``` \
code fence; output raw markdown directly starting with the `# Поездка...` heading.

CRITICAL HALLUCINATION RULES:
- Use ONLY the places that appear in the supplied CONTEXT (candidate_places, candidate_restaurants, \
city_context). NEVER invent restaurant or attraction names. If a slot has no candidate, write \
"в этот блок не нашли подходящего варианта" instead of inventing.
- Cite each place as a markdown link to its `source_url` (OSM or Wikivoyage).
- Respect dietary restrictions strictly — no restaurant with confidence < 0.5 for the user's restriction.
- Do not exceed the per-day budget unless you explicitly mark "⚠ Превышение бюджета".

=== EMBEDDED SKILL: itinerary-formatter ===
{skill_content}
=== END SKILL ===
"""

GENERATE_PLAN_USER_TEMPLATE = """USER REQUEST:
City: {city}
Days: {days}
Total budget: ${budget_usd}
Per-day budget: ${budget_per_day}
Interests: {interests}
Dietary restrictions: {dietary}

CITY OVERVIEW:
{city_overview}

CANDIDATE ATTRACTIONS (use ONLY these names; quote their source_url):
{candidate_places}

CANDIDATE RESTAURANTS (use ONLY these; respect dietary_confidence):
{candidate_restaurants}

WEATHER FORECAST:
{weather}

CLUSTERED DAY ASSIGNMENT (which places belong to which day, in route order):
{day_assignment}

CITY GUIDE CONTEXT (Wikivoyage snippets — use for short descriptions only, do not name places not \
present in the candidate lists above):
{city_context}

{photo_section}

Generate the FULL markdown itinerary following the embedded SKILL. End with the summary budget table \
and the "Что взять с собой" + "Источники" sections."""

EDIT_RERENDER_SYSTEM_TEMPLATE = """You are an expert travel planner RE-RENDERING an already-edited \
itinerary into full markdown. The set of places is FIXED and decided — your job is ONLY to format it \
richly following the embedded SKILL VERBATIM. Output ONLY raw markdown starting with the `# Поездка...` \
heading — no preamble, no JSON, no ```markdown fence.

CRITICAL RULES:
- Render EXACTLY the places in the FIXED ITINERARY below, in the given order, with the given times and \
source_urls. Do NOT add, remove, reorder, or rename any place. Do NOT invent new places.
- Cite each place as a markdown link to its source_url.
- For restaurants, reproduce the dietary marker (🟢/🟡) exactly as provided.
- Write a one-to-two sentence factual Russian description for each place.
- End with the summary budget table and the "Что взять с собой" + "Источники" sections.

=== EMBEDDED SKILL: itinerary-formatter ===
{skill_content}
=== END SKILL ===
"""

EDIT_RERENDER_USER_TEMPLATE = """USER REQUEST:
City: {city}
Days: {days}
Total budget: ${budget_usd}
Per-day budget: ${budget_per_day}
Interests: {interests}
Dietary restrictions: {dietary}

CITY OVERVIEW:
{city_overview}

APPLIED EDIT (already executed — the itinerary below already reflects it; do not re-apply):
{edit_note}

FIXED ITINERARY (render EXACTLY these, in this order — one block per line: time | name | category | \
cost | duration | source | dietary_marker):
{itinerary}

WEATHER FORECAST:
{weather}

Render the FULL markdown itinerary for these exact places following the embedded SKILL."""

EXPLAIN_AND_ASK_SYSTEM = """The proposed plan exceeds the user's budget. Briefly explain the gap and \
suggest one or two specific cuts (e.g., 'replace paid museum X with free viewpoint Y'). Keep it under \
100 words. Output as Russian text."""

CONSTRAINT_ADHERENCE_JUDGE_SYSTEM = """You are evaluating a travel itinerary against the user's \
stated constraints. Return STRICT JSON with fields: budget_pass, dietary_pass, days_pass, \
overall_pass, violations (list of strings), confidence (0..1)."""

FAITHFULNESS_JUDGE_SYSTEM = """You check whether the itinerary fabricates places that were never \
returned by any tool-call. Output STRICT JSON: total_places_in_plan, places_grounded_in_tools, \
hallucinated_places (list), faithfulness_score (0..1)."""
