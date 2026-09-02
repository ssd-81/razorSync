export function safeFixed(v: any, d = 1): string {
  const n = Number(v);
  if (!isFinite(n)) return "—";
  return n.toFixed(d);
}
export function safePercent(v: any, d = 1): string {
  const n = Number(v);
  if (!isFinite(n)) return "—";
  return `${n.toFixed(d)}%`;
}
export function safeCurrency(v: any): string {
  const n = Number(v);
  if (!isFinite(n)) return "—";
  return `₹${n.toLocaleString("en-IN")}`;
}
export function safeInt(v: any): string {
  const n = Number(v);
  if (!isFinite(n)) return "—";
  return Math.round(n).toLocaleString("en-IN");
}
export function sanitizeError(e: any): string {
  const msg = String(e?.message || e || "Unknown error");
  // strip stack, api keys, secrets if leaked
  return msg.replace(/gsk_[a-zA-Z0-9]+/g, "[redacted]").replace(/sk-[a-zA-Z0-9]+/g, "[redacted]").split("\n")[0].slice(0, 200);
}
