const STEPS = ["Параметры", "Генерация", "Просмотр и правки", "Готово"];

/**
 * Step indicator for the linear trip-planning flow. Step 0 ("Параметры") is
 * clickable once the user has moved past it — it triggers `onGoToParams` to
 * return to the form (start a fresh session). Future steps are not clickable:
 * the graph is a forward pipeline, you can't jump into a running/not-yet-reached stage.
 */
export function Stepper({
  current,
  onGoToParams,
}: {
  current: number;
  onGoToParams?: () => void;
}) {
  return (
    <nav aria-label="Шаги" className="flex flex-wrap items-center gap-x-2 gap-y-2 text-sm">
      {STEPS.map((label, i) => {
        const done = i < current;
        const active = i === current;
        const clickable = i === 0 && current > 0 && !!onGoToParams;

        const circle =
          "inline-flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold " +
          (active
            ? "bg-ink text-white"
            : done
              ? "bg-emerald-500 text-white"
              : "bg-slate-200 text-slate-500");
        const text =
          active ? "font-semibold text-ink" : done ? "text-slate-600" : "text-slate-400";

        const inner = (
          <span className="inline-flex items-center gap-2">
            <span className={circle}>{done ? "✓" : i + 1}</span>
            <span className={text}>{label}</span>
          </span>
        );

        return (
          <div key={label} className="flex items-center gap-2">
            {i > 0 && <span className="text-slate-300" aria-hidden>→</span>}
            {clickable ? (
              <button
                type="button"
                onClick={onGoToParams}
                className="rounded px-1 hover:bg-slate-100 transition"
                title="Вернуться к параметрам"
              >
                {inner}
              </button>
            ) : (
              inner
            )}
          </div>
        );
      })}
    </nav>
  );
}
