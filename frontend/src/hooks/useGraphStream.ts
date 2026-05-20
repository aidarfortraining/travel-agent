import { useEffect, useRef, useState } from "react";
import { streamUrl } from "@/api/client";

export type StreamEvent =
  | { type: "node"; node: string; update_keys: string[] }
  | { type: "interrupt"; payload: { type: string; [k: string]: unknown } }
  | { type: "done"; status: string }
  | { type: "error"; message: string }
  | { type: "ping" };

/**
 * `streamKey` is a parent-controlled counter used to force a fresh EventSource
 * after the user submits an edit / accept (which restarts the backend graph).
 * Bumping the key triggers a teardown + reconnect.
 */
export function useGraphStream(sessionId: string | null, enabled: boolean, streamKey: number) {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [lastInterrupt, setLastInterrupt] = useState<StreamEvent | null>(null);
  const [closed, setClosed] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!sessionId || !enabled) return;
    setEvents([]);
    setLastInterrupt(null);
    setClosed(false);
    const es = new EventSource(streamUrl(sessionId));
    esRef.current = es;

    function handle(ev: MessageEvent) {
      try {
        const data = JSON.parse(ev.data) as StreamEvent;
        if (data.type === "ping") return;
        setEvents((prev) => [...prev, data]);
        if (data.type === "interrupt") setLastInterrupt(data);
        if (data.type === "done" || data.type === "error" || data.type === "interrupt") {
          es.close();
          setClosed(true);
        }
      } catch (e) {
        console.warn("bad SSE event", e);
      }
    }

    ["message", "node", "interrupt", "done", "error", "ping"].forEach((ev) =>
      es.addEventListener(ev, handle as EventListener),
    );

    // Don't immediately give up on transient SSE errors — the parent does its own
    // /state polling fallback. Only flip `closed` when the server explicitly sends
    // a `done` / `error` / `interrupt` event (handled above).
    es.onerror = () => {
      // No-op: let the EventSource auto-reconnect attempt run; cleanup will close
      // it when the parent unmounts or `streamKey` bumps.
    };

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [sessionId, enabled, streamKey]);

  return { events, lastInterrupt, closed };
}
