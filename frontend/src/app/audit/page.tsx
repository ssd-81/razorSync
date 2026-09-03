"use client";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { Check, X, AlertTriangle, MessageCircle, Mail, Smartphone, Bell, RefreshCw, ShoppingCart, TrendingUp, Wallet, ClipboardList, Filter } from "lucide-react";

interface AuditEntry {
  id: string;
  timestamp: string;
  merchant_id: string;
  customer_id: string;
  event_type: string;
  action_type: string;
  decision: "allow" | "block" | "modify";
  reasoning: string;
  rules_applied: string[];
  latency_ms: number;
}

const decisionMeta: Record<string, { Icon: any; color: string; label: string }> = {
  allow: { Icon: Check, color: "bg-emerald-50 text-emerald-700 border-emerald-200", label: "Allow" },
  block: { Icon: X, color: "bg-red-50 text-red-700 border-red-200", label: "Block" },
  modify: { Icon: AlertTriangle, color: "bg-amber-50 text-amber-700 border-amber-200", label: "Modify" },
};
const actionMeta: Record<string, any> = {
  whatsapp: MessageCircle,
  email: Mail,
  sms: Smartphone,
  push: Bell,
  subscription_retry: RefreshCw,
  cart_recovery: ShoppingCart,
  upsell: TrendingUp,
  dunning: Wallet,
};

function formatTime(ts: string) {
  try { return new Date(ts).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }); } catch { return ts; }
}

export default function AuditPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [filter, setFilter] = useState("all");
  useEffect(() => { apiFetch("/api/v1/audit?limit=50").then((r) => setEntries(r.entries || r.items || r || [])).catch(() => {}); }, []);
  const filtered = filter === "all" ? entries : entries.filter((e) => e.decision === filter);
  const stats = entries.reduce((acc: any, e) => { acc[e.decision] = (acc[e.decision] || 0) + 1; return acc; }, {} as Record<string, number>);

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="rz-page-title flex items-center gap-2"><ClipboardList size={20} className="text-[#0B5CFF]" /> Audit Trail</h1>
          <p className="rz-page-desc mt-1">Every coordination decision — verifiable, filterable, IST-aware</p>
        </div>
        <div className="flex items-center gap-1.5 p-1 rounded-full bg-[#EAECF0] border">
          {["all", "allow", "block", "modify"].map((f) => (
            <button key={f} onClick={() => setFilter(f)} className={`px-3.5 py-1.5 rounded-full text-xs font-semibold capitalize transition-all ${filter === f ? "bg-[#0B1020] text-white shadow-sm" : "text-slate-600 hover:text-slate-900"}`}>
              {f}{f !== "all" && stats[f] ? ` · ${stats[f]}` : ""}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        {(["allow", "block", "modify"] as const).map((type) => {
          const m = decisionMeta[type]; const Icon = m.Icon;
          return (
            <div key={type} className="rz-card p-4 flex items-center gap-3">
              <span className={`w-10 h-10 rounded-xl flex items-center justify-center border ${m.color}`}><Icon size={18} /></span>
              <div>
                <div className="text-[22px] font-bold tracking-tight leading-none">{stats[type] || 0}</div>
                <div className="text-xs font-medium text-slate-500 capitalize mt-1">{type} decisions</div>
              </div>
              <span className={`ml-auto rz-pill border ${m.color} hidden sm:inline-flex`}>{m.label}</span>
            </div>
          );
        })}
      </div>

      <div className="rz-card overflow-hidden">
        <div className="px-5 py-4 border-b flex items-center gap-3 bg-[#F9FAFB]">
          <span className="w-7 h-7 rounded-lg bg-white border flex items-center justify-center"><Filter size={14} className="text-slate-500" /></span>
          <h2 className="rz-section-title">Timeline</h2>
          <span className="rz-pill bg-white border text-slate-500 ml-auto">{filtered.length} entries</span>
        </div>
        <div className="relative">
          <div className="absolute left-[32px] top-0 bottom-0 w-px bg-[#EAECF0]" />
          {filtered.length === 0 ? (
            <div className="p-12 text-center">
              <div className="w-12 h-12 rounded-xl bg-slate-50 border flex items-center justify-center mx-auto"><ClipboardList size={18} className="text-slate-400" /></div>
              <div className="text-sm font-medium text-slate-600 mt-3">No entries yet</div>
              <div className="text-xs text-slate-400 mt-1">Create an order to see decisions appear here.</div>
            </div>
          ) : (
            <div className="divide-y divide-[#F2F4F7]">
              {filtered.map((entry, idx) => {
                const dMeta = decisionMeta[entry.decision] || decisionMeta.allow;
                const DIcon = dMeta.Icon;
                const AIcon = actionMeta[entry.action_type] || ClipboardList;
                return (
                  <div key={entry.id || idx} className="flex gap-4 p-5 hover:bg-[#F9FAFB] transition-colors">
                    <span className={`w-8 h-8 rounded-full flex items-center justify-center border-2 bg-white shrink-0 z-10 ${dMeta.color}`} style={{ borderWidth: 1.5 }}><DIcon size={14} /></span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-[#0B1020]"><AIcon size={14} className="text-slate-400" />{entry.action_type?.replaceAll("_", " ")}</span>
                        <span className={`rz-pill border text-[11px] ${dMeta.color}`}>{entry.decision}</span>
                        <span className="ml-auto rz-mono bg-white border px-2 py-0.5 rounded-full text-slate-500">{formatTime(entry.timestamp)}</span>
                      </div>
                      <p className="text-[13px] leading-relaxed text-slate-600 mt-2">{entry.reasoning || "No reasoning provided."}</p>
                      <div className="flex flex-wrap gap-1.5 mt-3">
                        {entry.rules_applied?.map((r, i) => <span key={i} className="rz-pill bg-[#F2F4F7] border border-[#EAECF0] text-slate-600 text-[11px]">{r}</span>)}
                        {entry.latency_ms != null && <span className="rz-pill bg-white border text-slate-400 text-[11px]">{entry.latency_ms}ms</span>}
                        {entry.customer_id && <span className="rz-mono bg-slate-900 text-white px-2 py-1 rounded-full">{entry.customer_id.slice(0,14)}</span>}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
