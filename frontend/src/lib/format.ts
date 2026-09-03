/**
 * Time display — single source of truth for event timestamps.
 *
 * Backend stores UTC (SQLite CURRENT_TIMESTAMP) and now always emits
 * offset-aware ISO-8601 (e.g. "...+00:00"). Older rows / naive strings
 * ("2026-09-03T20:18:30" with no offset) are assumed UTC — this matches
 * what the DB stores. JS `new Date(naive)` would otherwise parse as
 * browser-local time, showing 5.5h behind in IST.
 *
 * All UI times are pinned to Asia/Kolkata via `timeZone` so the display
 * is identical regardless of the viewer's browser timezone.
 */
const IST = "Asia/Kolkata";

/** Normalize any backend timestamp to a Date. Naive strings → UTC. */
export function parseBackendTime(ts: string | null | undefined): Date | null {
  if (!ts) return null;
  const s = String(ts).trim();
  // Already offset-aware (Z or ±hh:mm / ±hhmm / ±hh)? parse directly.
  if (/[zZ]$/.test(s) || /[+-]\d{2}:?\d{2}$/.test(s)) {
    const d = new Date(s);
    return isNaN(d.getTime()) ? null : d;
  }
  // Naive "YYYY-MM-DD HH:mm:ss" (SQLite) → convert to ISO + treat as UTC.
  const iso = s.includes("T") ? s : s.replace(" ", "T");
  const d = new Date(iso + "Z");
  return isNaN(d.getTime()) ? null : d;
}

/** "01:48:30 AM IST" — time-only, IST-pinned. */
export function formatISTTime(ts: string | null | undefined): string {
  const d = parseBackendTime(ts);
  if (!d) return "—";
  try {
    return d.toLocaleTimeString("en-IN", { timeZone: IST, hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch { return String(ts); }
}

/** "04 Sep, 01:48 AM IST" — date+time, IST-pinned (tooltip/full display). */
export function formatISTDateTime(ts: string | null | undefined): string {
  const d = parseBackendTime(ts);
  if (!d) return "—";
  try {
    return d.toLocaleString("en-IN", { timeZone: IST, day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: true }) + " IST";
  } catch { return String(ts); }
}

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
