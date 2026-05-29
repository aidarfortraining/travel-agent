import { useEffect, useState } from "react";
import {
  acceptPlan,
  adjustBudget,
  createSession,
  getSessionState,
  submitEdit,
  submitInput,
  type SessionState,
  type TripInput,
} from "@/api/client";
import { useGraphStream } from "@/hooks/useGraphStream";
import { TripForm } from "@/components/TripForm";
import { PhotoUpload } from "@/components/PhotoUpload";
import { GraphProgress } from "@/components/GraphProgress";
import { PlanView } from "@/components/PlanView";
import { EditBox } from "@/components/EditBox";
import { Stepper } from "@/components/Stepper";

export default function App() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [streamEnabled, setStreamEnabled] = useState(false);
  const [sessionState, setSessionState] = useState<SessionState | null>(null);
  const [streamKey, setStreamKey] = useState(0);
  const [lastInput, setLastInput] = useState<TripInput | null>(null);
  const [newBudget, setNewBudget] = useState("");

  useEffect(() => {
    (async () => {
      const s = await createSession();
      setSessionId(s.session_id);
    })().catch(console.error);
  }, []);

  const { events, lastInterrupt, closed } = useGraphStream(sessionId, streamEnabled, streamKey);

  // Refresh state when SSE closes (interrupt / done) — fast path.
  useEffect(() => {
    if (!sessionId) return;
    if (!closed) return;
    getSessionState(sessionId)
      .then(setSessionState)
      .catch(console.error);
  }, [sessionId, closed, streamKey]);

  // Resilient fallback: poll /state every 3s while the graph is running.
  // SSE delivers progress for free; this guarantees we eventually pick up the plan
  // even if SSE has connectivity / buffering issues we can't diagnose at runtime.
  useEffect(() => {
    if (!sessionId || !submitted) return;
    if (sessionState?.status === "finalized") return;
    const handle = setInterval(() => {
      getSessionState(sessionId)
        .then((s) => {
          setSessionState((prev) => {
            if (!prev) return s;
            // Don't downgrade plan_markdown to null due to a transient empty fetch
            if (!s.plan_markdown && prev.plan_markdown) {
              return { ...s, plan_markdown: prev.plan_markdown };
            }
            return s;
          });
        })
        .catch(() => {});
    }, 3000);
    return () => clearInterval(handle);
  }, [sessionId, submitted, sessionState?.status]);

  async function handleSubmit(payload: TripInput) {
    if (!sessionId) return;
    setLastInput(payload);
    setSubmitted(true);
    setStreamEnabled(true);
    setStreamKey((k) => k + 1);
    await submitInput(sessionId, payload);
  }

  // Navigate back to the parameters form. A new session is created so the fresh
  // run gets a clean checkpoint thread (re-running on the old thread would clash
  // with its persisted state). The form is prefilled with the last input.
  async function startOver() {
    setSubmitted(false);
    setStreamEnabled(false);
    setSessionState(null);
    setStreamKey((k) => k + 1);
    try {
      const s = await createSession();
      setSessionId(s.session_id);
    } catch (e) {
      console.error(e);
    }
  }

  async function handleAccept() {
    if (!sessionId) return;
    await acceptPlan(sessionId);
    setStreamEnabled(true);
    setStreamKey((k) => k + 1);
  }

  async function handleEdit(text: string) {
    if (!sessionId) return;
    await submitEdit(sessionId, text);
    setStreamEnabled(true);
    setStreamKey((k) => k + 1);
  }

  // Resume the graph after the budget HITL interrupt. Without this the graph stays
  // paused at explain_and_ask forever and the UI is stuck on "В работе…".
  async function handleAdjustBudget(newBudget?: number) {
    if (!sessionId) return;
    await adjustBudget(
      sessionId,
      newBudget ? { accept_reduced: false, new_budget_usd: newBudget } : { accept_reduced: true },
    );
    setStreamEnabled(true);
    setStreamKey((k) => k + 1);
  }

  const planMd = sessionState?.plan_markdown;
  const status = sessionState?.status || "draft";
  const finalized = status === "finalized";
  const awaitingEdit =
    sessionState?.awaiting_input?.type === "review_plan" || (closed && !!planMd && !finalized);
  const stillRunning = streamEnabled && !closed;

  // Budget HITL: derive from the persisted state (resilient if SSE dropped) or the
  // live interrupt event. When present, the graph is paused awaiting the user's call.
  const budgetInterrupt =
    sessionState?.awaiting_input?.type === "budget_explain"
      ? (sessionState.awaiting_input as { type: string; message?: string })
      : lastInterrupt?.type === "interrupt" && lastInterrupt.payload?.type === "budget_explain"
        ? (lastInterrupt.payload as { type: string; message?: string })
        : null;
  const budgetPaused = !!budgetInterrupt && !planMd && !stillRunning;

  const step = !submitted ? 0 : finalized ? 3 : planMd ? 2 : 1;

  return (
    <div className="min-h-screen bg-muted">
      <header className="bg-white border-b border-slate-200">
        <div className="max-w-5xl mx-auto px-6 py-4">
          <h1 className="text-2xl font-bold text-ink">Trip Planner</h1>
          <p className="text-sm text-slate-500">
            Персональный маршрут с учётом бюджета, интересов и пищевых ограничений.
          </p>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-6 space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Stepper current={step} onGoToParams={startOver} />
          {submitted && (
            <button
              type="button"
              onClick={startOver}
              className="text-sm font-medium text-slate-600 hover:text-ink border border-slate-300 rounded px-3 py-1.5 hover:bg-white transition"
            >
              ← Изменить параметры
            </button>
          )}
        </div>

        {!submitted && (
          <>
            <TripForm onSubmit={handleSubmit} initialValues={lastInput ?? undefined} />
            {sessionId && <PhotoUpload sessionId={sessionId} />}
          </>
        )}

        {submitted && <GraphProgress events={events} closed={closed} />}

        {budgetPaused && (
          <div className="bg-amber-50 border border-amber-300 rounded p-4 space-y-3">
            <p className="text-sm text-amber-900 font-medium">⚠ Бюджет</p>
            <p className="text-sm text-amber-900">{budgetInterrupt?.message}</p>
            <p className="text-xs text-amber-700">
              Выберите, как продолжить: оставить заявленный бюджет (план соберём с упором на бесплатные
              альтернативы) или задать новый.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => handleAdjustBudget()}
                className="text-sm font-medium text-white bg-amber-600 hover:bg-amber-700 rounded px-3 py-1.5 transition"
              >
                Продолжить с уменьшенным scope
              </button>
              <span className="text-amber-700 text-sm">или</span>
              <input
                type="number"
                min={0}
                value={newBudget}
                onChange={(e) => setNewBudget(e.target.value)}
                placeholder="новый бюджет, $"
                className="w-40 text-sm border border-amber-300 rounded px-2 py-1.5 bg-white"
              />
              <button
                type="button"
                disabled={!newBudget || Number(newBudget) <= 0}
                onClick={() => handleAdjustBudget(Number(newBudget))}
                className="text-sm font-medium text-amber-900 border border-amber-400 rounded px-3 py-1.5 hover:bg-amber-100 disabled:opacity-50 transition"
              >
                Пересчитать с новым бюджетом
              </button>
            </div>
          </div>
        )}

        {planMd && (
          <>
            <PlanView
              markdown={planMd}
              sessionId={sessionId!}
              finalized={finalized}
              onAccept={handleAccept}
            />
            {awaitingEdit && !finalized && (
              <EditBox onSubmit={handleEdit} disabled={stillRunning} />
            )}
          </>
        )}

        {finalized && (
          <p className="text-sm text-emerald-700">
            План финализирован. Вы можете скачать PDF и поделиться им.
          </p>
        )}
      </main>
    </div>
  );
}
