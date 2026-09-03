const BASE = process.env.NEXT_PUBLIC_API_URL || "";

export async function apiFetch(path: string, init?: RequestInit, timeoutMs = 10000) {
  const url = path.startsWith("http") ? path : `${BASE}${path}`;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...init, signal: ctrl.signal, headers: { "Content-Type": "application/json", ...(init?.headers || {}) } });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`API ${res.status}: ${text}`);
    }
    return res.json();
  } catch (e: any) {
    if (e?.name === "AbortError") throw new Error(`API timeout after ${timeoutMs}ms: ${path}`);
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  getRules: () => apiFetch("/api/v1/rules"),
  createRule: (body: unknown) => apiFetch("/api/v1/rules", { method: "POST", body: JSON.stringify(body) }),
  updateRule: (id: string, body: unknown) => apiFetch(`/api/v1/rules/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteRule: (id: string) => apiFetch(`/api/v1/rules/${id}`, { method: "DELETE" }),
  toggleRule: (id: string) => apiFetch(`/api/v1/rules/${id}/toggle`, { method: "PATCH" }),
  listCustomers: (params: string = "") => apiFetch(`/api/v1/customers${params}`),
  getCustomer: (id: string) => apiFetch(`/api/v1/customers/${id}/context`),
  getAudit: (params: string = "") => apiFetch(`/api/v1/audit${params}`),
  getMetrics: () => apiFetch("/api/v1/metrics"),
  runSimulation: (body: unknown) => apiFetch("/api/v1/simulation/run", { method: "POST", body: JSON.stringify(body) }),
  runScorecard: (body: unknown) => apiFetch("/api/v1/simulation/scorecard", { method: "POST", body: JSON.stringify(body) }),
  createOrder: (body: unknown) => apiFetch("/api/v1/orders", { method: "POST", body: JSON.stringify(body) }),
  getDecisions: (since?: string) => apiFetch(`/api/v1/decisions/recent${since ? `?since=${encodeURIComponent(since)}` : ""}`),
  getOpsState: () => apiFetch("/api/v1/ops/state"),
  toggleFailure: (enabled: boolean) => apiFetch("/api/v1/ops/failure-toggle", { method: "POST", body: JSON.stringify({ enabled }) }),
  resetOps: () => apiFetch("/api/v1/ops/reset", { method: "POST" }),
  getFailureStatus: () => apiFetch("/api/v1/ops/failure-status"),
  getInbox: (limit = 10) => apiFetch(`/api/v1/webhook/inbox?limit=${limit}`),
  getAgents: () => apiFetch("/api/v1/agents"),
  getAgent: (type: string) => apiFetch(`/api/v1/agents/${type}`),
  getLLMStatus: () => apiFetch("/api/v1/agents/llm/status"),
  getLLMModels: () => apiFetch("/api/v1/agents/llm/models"),
  getHitlPending: () => apiFetch("/api/v1/hitl/pending"),
};
