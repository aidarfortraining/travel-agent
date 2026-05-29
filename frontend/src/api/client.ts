const BASE = (import.meta.env.VITE_BACKEND_URL as string) || "/api";

export type TripInput = {
  city: string;
  days: number;
  budget_usd: number;
  interests: string[];
  dietary: string[];
};

export type SessionState = {
  session_id: string;
  status: string;
  plan_markdown: string | null;
  awaiting_input: { type: string; [k: string]: unknown } | null;
  city: string;
  days: number;
  budget_usd: number;
  interests: string[];
  dietary: string[];
};

async function jsonReq<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return (await res.json()) as T;
}

export async function createSession() {
  return jsonReq<{ session_id: string }>("/sessions", { method: "POST" });
}

export async function submitInput(sessionId: string, payload: TripInput) {
  return jsonReq<{ session_id: string; started: boolean }>(
    `/sessions/${sessionId}/input`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export async function uploadPhoto(sessionId: string, file: File) {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(`${BASE}/sessions/${sessionId}/photo`, { method: "POST", body: fd });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

export async function submitEdit(sessionId: string, text: string) {
  return jsonReq(`/sessions/${sessionId}/edit`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}

export async function acceptPlan(sessionId: string) {
  return jsonReq(`/sessions/${sessionId}/accept`, { method: "POST" });
}

export async function adjustBudget(
  sessionId: string,
  body: { accept_reduced?: boolean; new_budget_usd?: number },
) {
  return jsonReq(`/sessions/${sessionId}/adjust-budget`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function getSessionState(sessionId: string) {
  return jsonReq<SessionState>(`/sessions/${sessionId}/state`);
}

export function pdfUrl(sessionId: string) {
  return `${BASE}/sessions/${sessionId}/pdf`;
}

export function streamUrl(sessionId: string) {
  return `${BASE}/sessions/${sessionId}/stream`;
}
