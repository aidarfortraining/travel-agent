import { useEffect, useState } from "react";
import {
  acceptPlan,
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

export default function App() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [streamEnabled, setStreamEnabled] = useState(false);
  const [sessionState, setSessionState] = useState<SessionState | null>(null);
  const [streamKey, setStreamKey] = useState(0);

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
    setSubmitted(true);
    setStreamEnabled(true);
    setStreamKey((k) => k + 1);
    await submitInput(sessionId, payload);
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

  const planMd = sessionState?.plan_markdown;
  const status = sessionState?.status || "draft";
  const finalized = status === "finalized";
  const awaitingEdit =
    sessionState?.awaiting_input?.type === "review_plan" || (closed && !!planMd && !finalized);
  const stillRunning = streamEnabled && !closed;

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
        {!submitted && (
          <>
            <TripForm onSubmit={handleSubmit} />
            {sessionId && <PhotoUpload sessionId={sessionId} />}
          </>
        )}

        {submitted && <GraphProgress events={events} closed={closed} />}

        {lastInterrupt && lastInterrupt.type === "interrupt" && lastInterrupt.payload?.type === "budget_explain" && (
          <div className="bg-amber-50 border border-amber-300 rounded p-4">
            <p className="text-sm text-amber-900 font-medium">⚠ Бюджет</p>
            <p className="text-sm text-amber-900 mt-1">{(lastInterrupt.payload as any).message}</p>
            <p className="text-xs text-amber-700 mt-2">
              Граф автоматически продолжит с уменьшенным scope. Если хотите задать другой бюджет — измените форму и
              начните заново.
            </p>
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
