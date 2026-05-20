import type { StreamEvent } from "@/hooks/useGraphStream";

const NODE_LABELS: Record<string, string> = {
  collect_input: "Проверяю ввод",
  vision_identify: "Распознаю место по фото",
  enrich_input: "Учитываю фото в плане",
  city_research: "Изучаю гайд по городу",
  candidate_places: "Ищу POI и рестораны",
  budget_check: "Проверяю бюджет",
  explain_and_ask: "Запрашиваю решение по бюджету",
  cluster_by_day: "Распределяю по дням",
  optimize_route: "Оптимизирую маршрут",
  generate_plan: "Генерирую план через OpenAI",
  present_plan: "Готово, передаю на ревью",
  parse_edit_intent: "Разбираю вашу правку",
  patch_plan: "Применяю патч к плану",
  finalize_and_export: "Финализирую",
};

export function GraphProgress({ events, closed }: { events: StreamEvent[]; closed: boolean }) {
  const nodes = events.filter((e) => e.type === "node") as Extract<StreamEvent, { type: "node" }>[];
  return (
    <div className="bg-white rounded-lg shadow p-4 border border-slate-200">
      <h3 className="text-sm font-semibold mb-2">Прогресс</h3>
      <ol className="text-sm space-y-1">
        {nodes.map((e, i) => (
          <li key={i} className="flex items-center gap-2">
            <span className="inline-block w-4 h-4 rounded-full bg-emerald-500" />
            <span className="font-medium">{NODE_LABELS[e.node] || e.node}</span>
            <span className="text-slate-400 text-xs">({e.node})</span>
          </li>
        ))}
        {!closed && (
          <li className="flex items-center gap-2 text-slate-500">
            <span className="inline-block w-4 h-4 rounded-full bg-slate-300 animate-pulse" />
            <span>В работе…</span>
          </li>
        )}
      </ol>
    </div>
  );
}
