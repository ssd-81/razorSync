"use client";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { Hash, Clock, Hourglass, IndianRupee, Radio, Zap, SlidersHorizontal, Shield } from "lucide-react";

interface Rule {
  id: string;
  name: string;
  rule_type: string;
  description: string;
  rule_config: Record<string, unknown> | string;
  is_active: boolean;
  priority?: number;
}

const ruleMeta: Record<string, { Icon: any; color: string; dot: string }> = {
  frequency_cap: { Icon: Hash, color: "bg-blue-50 text-blue-700 border-blue-200", dot: "bg-blue-500" },
  time_window: { Icon: Clock, color: "bg-violet-50 text-violet-700 border-violet-200", dot: "bg-violet-500" },
  cooldown: { Icon: Hourglass, color: "bg-amber-50 text-amber-700 border-amber-200", dot: "bg-amber-500" },
  budget_limit: { Icon: IndianRupee, color: "bg-emerald-50 text-emerald-700 border-emerald-200", dot: "bg-emerald-500" },
  spend_limit: { Icon: IndianRupee, color: "bg-emerald-50 text-emerald-700 border-emerald-200", dot: "bg-emerald-500" },
  channel_priority: { Icon: Radio, color: "bg-sky-50 text-sky-700 border-sky-200", dot: "bg-sky-500" },
  escalation_ceiling: { Icon: Zap, color: "bg-orange-50 text-orange-700 border-orange-200", dot: "bg-orange-500" },
};

function parseConfig(config: Record<string, unknown> | string) {
  if (typeof config === "string") { try { return JSON.parse(config || "{}"); } catch { return {}; } }
  return config || {};
}

export default function RulesPage() {
  const [rules, setRules] = useState<Rule[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [toggling, setToggling] = useState<string | null>(null);
  useEffect(() => { apiFetch("/api/v1/rules").then((r: any) => setRules(r?.rules ?? r ?? [])).catch((e) => setErr(String(e))); }, []);
  const toggle = async (id: string) => {
    setToggling(id);
    try { await apiFetch(`/api/v1/rules/${id}/toggle`, { method: "PATCH" }); const r: any = await apiFetch("/api/v1/rules"); setRules(r?.rules ?? r ?? []); } catch (e: any) { setErr(String(e)); } finally { setToggling(null); }
  };
  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="rz-page-title flex items-center gap-2"><Shield size={20} className="text-[#0B5CFF]" /> Coordination Rules</h1>
          <p className="rz-page-desc mt-1">Windowed, IST-aware • single source of truth from <span className="rz-mono bg-white border px-1.5 py-0.5 rounded">BusinessRule</span></p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="rz-pill bg-emerald-50 border border-emerald-200 text-emerald-700"><span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />{rules.filter((r) => r.is_active).length} active</span>
          <span className="rz-pill bg-white border text-slate-500">{rules.filter((r) => !r.is_active).length} inactive</span>
        </div>
      </div>

      {err && <div className="rz-card px-4 py-3 text-sm bg-red-50 border-red-200 text-red-700">{err}</div>}

      <div className="space-y-3">
        {rules.length === 0 ? (
          <div className="rz-card p-10 text-center">
            <div className="w-10 h-10 rounded-xl bg-slate-100 border flex items-center justify-center mx-auto"><SlidersHorizontal size={16} className="text-slate-400" /></div>
            <div className="text-sm font-medium text-slate-600 mt-3">No rules yet</div>
            <div className="text-xs text-slate-400 mt-1">Seeded via backend lifespan — restart backend if empty.</div>
          </div>
        ) : (
          rules.map((rule) => {
            const config = parseConfig(rule.rule_config);
            const meta = ruleMeta[rule.rule_type] || { Icon: SlidersHorizontal, color: "bg-slate-50 text-slate-600 border-slate-200", dot: "bg-slate-400" };
            const Icon = meta.Icon;
            return (
              <div key={rule.id} className={`rz-card p-4 flex gap-4 items-start rz-card-hover ${rule.is_active ? "" : "opacity-60"}`}>
                <span className={`w-10 h-10 rounded-xl flex items-center justify-center border shrink-0 ${meta.color}`}><Icon size={16} /></span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <h3 className="text-[14px] font-semibold tracking-tight text-[#0B1020]">{rule.name}</h3>
                    <span className="rz-pill bg-slate-50 border text-slate-600 text-[11px]">{rule.rule_type.replaceAll("_", " ")}</span>
                    {rule.priority != null && <span className="rz-mono bg-white border px-2 py-0.5 rounded-full">p{rule.priority}</span>}
                    <span className={`ml-1 h-2 w-2 rounded-full ${rule.is_active ? meta.dot : "bg-slate-300"}`} />
                  </div>
                  <p className="text-[13px] text-slate-500 mt-1.5 leading-relaxed">{rule.description}</p>
                  <div className="flex flex-wrap gap-1.5 mt-3">
                    {Object.entries(config).slice(0,4).map(([k, v]) => (
                      <span key={k} className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-[#F2F4F7] border border-[#EAECF0] text-[11px]">
                        <span className="text-slate-500 font-medium">{k}</span>
                        <span className="font-semibold text-slate-800">{typeof v === "object" ? JSON.stringify(v) : String(v)}</span>
                      </span>
                    ))}
                    {Object.keys(config).length === 0 && <span className="text-xs text-slate-400">No config</span>}
                  </div>
                </div>
                <button
                  onClick={() => toggle(rule.id)}
                  disabled={toggling === rule.id}
                  aria-pressed={rule.is_active}
                  className={`shrink-0 inline-flex items-center gap-2 px-3.5 py-2 rounded-full text-xs font-semibold border transition-colors ${rule.is_active ? "bg-[#0B1020] text-white border-[#0B1020] hover:bg-black" : "bg-white text-slate-600 border-[#E6E8EB] hover:bg-slate-50"}`}
                >
                  <span className={`h-2 w-2 rounded-full ${rule.is_active ? "bg-emerald-400" : "bg-slate-300"}`} />
                  {toggling === rule.id ? "…" : rule.is_active ? "Active" : "Disabled"}
                </button>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
