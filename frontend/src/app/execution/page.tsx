"use client";
import { useState, useEffect } from "react";
import { apiFetch } from "@/lib/api";
import { Inbox, Brain, Scale, Shield, UserCheck, CheckCircle2, Clock, GitBranch, RefreshCw } from "lucide-react";
import { safeFixed } from "@/lib/format";

interface TimelineNode { type: string; label: string; status: string; detail: string; agent_type?: string; channel?: string; score?: number; ticket_id?: string; decision?: string; override?: boolean; verdict?: string; source?: string; }
interface ExecutionChain { decision_id: string; customer_id: string; agent_type: string; channel: string; source: string; created_at: string; nodes: TimelineNode[]; }

const STATUS_COLORS: Record<string, string> = {
  completed: "bg-emerald-500", passed: "bg-emerald-500", approved: "bg-emerald-500",
  blocked: "bg-red-500", suspended: "bg-amber-500", pending: "bg-amber-500", rejected: "bg-red-500", expired: "bg-slate-400",
};
const NODE_ICONS: Record<string, any> = { event: Inbox, dispatcher: Brain, policy: Scale, guardrail: Shield, hitl: UserCheck, outcome: CheckCircle2 };

export default function ExecutionPage() {
  const [chains, setChains] = useState<ExecutionChain[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const fetchChains = async () => {
    try { const data = await apiFetch("/api/v1/execution/chain?limit=10"); setChains(data.chains || []); } catch (e: any) { setError(e?.message?.slice(0,200) || String(e).slice(0,200)); }
  };

  useEffect(() => {
    fetchChains();
    if (!autoRefresh) return;
    const tick = () => { if (!document.hidden) fetchChains(); };
    const interval = setInterval(tick, 4000);
    return () => clearInterval(interval);
  }, [autoRefresh]);

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="rz-page-title flex items-center gap-2"><GitBranch size={20} className="text-[#0B5CFF]" /> Execution Graph</h1>
          <p className="rz-page-desc mt-1">Event → Dispatcher → Policy → Guardrail → Outcome • live shared state, auto-refresh 4s</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <label className="flex items-center gap-2 text-xs font-medium border rounded-full px-3 py-2 bg-white cursor-pointer">
            <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} className="rounded text-[#0B5CFF]" />
            Auto
          </label>
          <button onClick={fetchChains} className="rz-btn-secondary h-9"><RefreshCw size={12} /> Refresh</button>
        </div>
      </div>

      {error && <div className="rz-card px-4 py-3 text-sm bg-red-50 border-red-200 text-red-700">{error}</div>}
      {chains.length === 0 && (
        <div className="rz-card p-12 text-center">
          <div className="w-12 h-12 rounded-xl bg-[#F2F4F7] border flex items-center justify-center mx-auto"><GitBranch size={18} className="text-slate-400" /></div>
          <div className="text-sm font-semibold text-slate-700 mt-3">No chains yet</div>
          <div className="text-xs text-slate-500 mt-1">Create an order or trigger webhook — DAG appears in 2–4s.</div>
        </div>
      )}

      <div className="space-y-4">
        {chains.map((chain) => {
          const last = chain.nodes[chain.nodes.length - 1];
          const isApproved = last?.status === "approved" || last?.status === "completed" || last?.status === "passed";
          const isSuspended = last?.status === "suspended" || last?.status === "pending";
          return (
            <div key={chain.decision_id} className="rz-card overflow-hidden">
              <div className="px-5 py-4 border-b bg-[#F9FAFB] flex items-center justify-between gap-3">
                <div className="flex items-center gap-2 min-w-0">
                  <span className={`rz-pill text-white text-[11px] ${isApproved ? "bg-emerald-600" : isSuspended ? "bg-amber-500" : "bg-red-500"}`}>{(last?.status || "pending").toUpperCase()}</span>
                  <span className="text-sm font-semibold truncate">{chain.agent_type} → {chain.channel}</span>
                  <span className="rz-mono bg-white border px-2 py-0.5 rounded-full text-slate-500 hidden sm:inline-flex">{chain.customer_id.slice(0,12)}</span>
                </div>
                <div className="flex items-center gap-2 text-xs text-slate-500 shrink-0">
                  <Clock size={12} /> {chain.created_at ? new Date(chain.created_at).toLocaleTimeString() : "—"}
                  <span className="rz-pill bg-white border text-slate-500">{chain.source || "—"}</span>
                </div>
              </div>

              <div className="p-5">
                <div className="relative ml-2">
                  {chain.nodes.map((node, idx) => {
                    const Icon = NODE_ICONS[node.type] || Clock;
                    const isLast = idx === chain.nodes.length - 1;
                    return (
                      <div key={idx} className="flex gap-4">
                        <div className="flex flex-col items-center">
                          <div className={`w-8 h-8 rounded-full flex items-center justify-center text-white shadow-sm ${STATUS_COLORS[node.status] || "bg-slate-300"}`}>
                            <Icon size={14} />
                          </div>
                          {!isLast && <div className="w-0.5 flex-1 bg-[#EAECF0] mt-1 mb-1 min-h-[24px]" />}
                        </div>
                        <div className={`flex-1 ${!isLast ? "pb-4" : ""}`}>
                          <div className="flex items-center gap-2">
                            <span className="font-semibold text-[13px]">{node.label}</span>
                            <span className={`rz-pill border text-[10px] ${node.status === "blocked" || node.status === "rejected" ? "bg-red-50 text-red-700 border-red-200" : node.status === "suspended" || node.status === "pending" ? "bg-amber-50 text-amber-700 border-amber-200" : "bg-emerald-50 text-emerald-700 border-emerald-200"}`}>{node.status}</span>
                          </div>
                          <p className="text-xs text-slate-600 mt-1 leading-relaxed">{node.detail || "—"}</p>
                          {node.type === "policy" && node.score != null && (
                            <div className="mt-2 flex items-center gap-2 max-w-[260px]">
                              <div className="flex-1 h-1.5 bg-[#EAECF0] rounded-full overflow-hidden"><div className={`h-full rounded-full ${Number(node.score) > 0 ? "bg-emerald-500" : "bg-red-500"}`} style={{ width: `${Math.min(100, Math.max(6, Math.abs(Number(node.score)) * 10))}%` }} /></div>
                              <span className="rz-mono text-slate-700">{safeFixed(node.score, 4)}</span>
                            </div>
                          )}
                          {node.type === "hitl" && (
                            <div className="mt-2 flex gap-1.5">
                              {node.ticket_id && <span className="rz-pill bg-amber-50 border-amber-200 text-amber-700">{node.ticket_id.slice(0,12)}</span>}
                              {node.override && <span className="rz-pill bg-red-50 border-red-200 text-red-700">OVERRIDE</span>}
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
