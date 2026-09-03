"use client";
import { Check, Ban, Trophy, Swords, Shield, MessageSquareText, Zap } from "lucide-react";
import { safeFixed } from "@/lib/format";

export interface DispatcherCandidate {
  agent_type: string;
  channel: string;
  score: number;
  confidence?: number;
  discount_offered?: number;
  source?: string;
  reasoning?: string | null;
  delay_h?: number;
  llm_latency_s?: number | null;
  score_breakdown?: { est_revenue?: number; churn_risk?: number; discount_cost?: number; channel_cost?: number; channel_fit?: number };
}

export interface FullCycleDecision {
  id: string;
  customer_id: string;
  verdict: string;
  block_reason?: string | null;
  reasoning?: string;
  source?: string;
  trigger_event?: string | null;
  dispatcher_winner?: string | null;
  dispatcher?: { candidates: DispatcherCandidate[]; winner?: string | null } | null;
  action?: { agent_type?: string | null; channel?: string | null; amount_involved?: number | null; discount_offered?: number | null; message_preview?: string | null } | null;
  created_at?: string;
}

/** Shared full-cycle card: Event → Candidates → Winner → Guardrail → Message. */
export default function FullCycleCard({ d, compact }: { d: FullCycleDecision | null | undefined; compact?: boolean }) {
  if (!d) return null;
  const cands = d.dispatcher?.candidates || [];
  const winner = d.dispatcher?.winner || d.dispatcher_winner || d.action?.agent_type || null;
  const isBlocked = d.verdict === "blocked";
  const sorted = [...cands].sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
  const maxAbs = Math.max(0.01, ...sorted.map((c) => Math.abs(c.score ?? 0)));

  return (
    <div className="border rounded-xl overflow-hidden bg-white">
      {/* header: event → verdict */}
      <div className="px-4 py-3 bg-[#F9FAFB] border-b flex items-center gap-2 flex-wrap">
        <span className="rz-mono bg-slate-900 text-white px-2 py-0.5 rounded-full text-[11px]">{d.trigger_event || "event"}</span>
        <span className="text-xs text-slate-400">→</span>
        <span className={`rz-pill border text-[11px] ${isBlocked ? "bg-slate-100 text-slate-500 border-slate-200" : "bg-emerald-50 text-emerald-700 border-emerald-200"}`}>
          {isBlocked ? "blocked" : "approved"}
        </span>
        {winner && (
          <span className="inline-flex items-center gap-1 text-xs font-semibold text-slate-700">
            <Trophy size={12} className="text-amber-500" /> {winner}
            <span className="font-normal text-slate-500">via {d.action?.channel || "—"}</span>
          </span>
        )}
        <span className="ml-auto text-[11px] text-slate-400 rz-mono">{d.id?.slice(0, 12)} • {d.source || "live"}</span>
      </div>

      {/* candidates */}
      <div className="px-4 py-3">
        <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
          <Swords size={12} /> Dispatcher race {cands.length ? `— ${cands.length} scored` : "— single proposal"}
        </div>
        {sorted.length === 0 ? (
          <div className="text-xs text-slate-500 mt-2">No candidate trace stored (decision predates v4). Winner ran directly.</div>
        ) : (
          <div className="mt-2 space-y-1.5">
            {sorted.map((c) => {
              const isWin = c.agent_type === winner;
              const pct = Math.min(100, Math.max(6, (Math.abs(c.score ?? 0) / maxAbs) * 100));
              return (
                <div key={c.agent_type} className={`rounded-lg border px-2.5 py-2 ${isWin ? "border-amber-300 bg-amber-50/50" : "bg-white"}`}>
                  <div className="flex items-center gap-2 text-xs">
                    {isWin ? <Trophy size={12} className="text-amber-500 shrink-0" /> : <Zap size={12} className="text-slate-300 shrink-0" />}
                    <span className="font-semibold rz-mono">{c.agent_type}</span>
                    <span className="text-slate-500">{c.channel}</span>
                    {c.score_breakdown && (
                      <span className="hidden sm:inline text-[11px] text-slate-400">
                        rev {safeFixed(c.score_breakdown.est_revenue, 0)} • churn {safeFixed(c.score_breakdown.churn_risk, 0)} • disc {safeFixed(c.score_breakdown.discount_cost, 0)}
                      </span>
                    )}
                    <span className={`ml-auto rz-pill ${isWin ? "bg-amber-500 text-white" : (c.score ?? 0) > 0 ? "bg-slate-100 text-slate-700" : "bg-red-50 text-red-600 border border-red-200"}`}>
                      {safeFixed(c.score, 2)}
                    </span>
                  </div>
                  <div className="h-1 bg-slate-100 rounded-full mt-1.5 overflow-hidden">
                    <div className={`h-full rounded-full ${(c.score ?? 0) > 0 ? (isWin ? "bg-amber-500" : "bg-emerald-500") : "bg-red-400"}`} style={{ width: `${pct}%` }} />
                  </div>
                  {c.reasoning && (
                    <details className="mt-1.5 group" open={isWin}>
                      <summary className="text-[11px] text-slate-500 cursor-pointer hover:text-slate-700 list-none flex items-center gap-1">
                        <span className="group-open:hidden">▸ agent response</span>
                        <span className="hidden group-open:inline">▾ agent response</span>
                        {c.source === "llm" ? <span className="rz-pill bg-violet-600 text-white text-[10px]">LLM{c.llm_latency_s ? ` ${safeFixed(c.llm_latency_s, 2)}s` : ""}</span> : <span className="rz-pill bg-slate-100 text-slate-500 text-[10px]">built-in</span>}
                      </summary>
                      <div className="text-[11px] text-slate-600 leading-relaxed mt-1 pl-1 border-l-2 border-slate-200">
                        “{c.reasoning}”
                        <span className="block mt-1 text-slate-400 rz-mono">conf {safeFixed(c.confidence, 2)} • delay {(c.delay_h ?? 0)}h • disc ₹{safeFixed(c.discount_offered, 0)}</span>
                      </div>
                    </details>
                  )}
                </div>
              );
            })}
          </div>
        )}
        {!compact && (
          <>
            <div className="flex items-start gap-1.5 mt-3 text-xs leading-relaxed">
              {isBlocked ? <Ban size={13} className="text-slate-400 mt-0.5 shrink-0" /> : <Check size={13} className="text-emerald-600 mt-0.5 shrink-0" />}
              <span className="text-slate-700">
                <span className="inline-flex items-center gap-1 font-semibold"><Shield size={11} /> Guardrail:</span>{" "}
                {d.block_reason || d.reasoning || "Passed — executed"}
              </span>
            </div>
            {d.action?.message_preview && (
              <div className="mt-2.5 rounded-lg bg-slate-50 border p-2.5 flex gap-2">
                <MessageSquareText size={13} className="text-slate-400 mt-0.5 shrink-0" />
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Customer receives</div>
                  <div className="text-xs text-slate-700 leading-relaxed mt-0.5">“{d.action.message_preview}”</div>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
