"use client";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { Search, Users, TrendingUp, Shield } from "lucide-react";

interface Customer {
  id: string;
  name: string;
  email?: string;
  archetype: string;
  city: string;
  risk_score: number;
  lifetime_value: number;
  current_discount_exposure: number;
  total_contacts_received: number;
}

const archetypeStyle: Record<string, string> = {
  loyal_regular: "bg-emerald-50 text-emerald-700 border-emerald-200",
  high_value_at_risk: "bg-amber-50 text-amber-700 border-amber-200",
  price_sensitive: "bg-blue-50 text-blue-700 border-blue-200",
  low_engagement: "bg-slate-100 text-slate-600 border-slate-200",
  new_customer: "bg-violet-50 text-violet-700 border-violet-200",
};

function currency(n: number) {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(n || 0);
}

export default function CustomersPage() {
  const [list, setList] = useState<Customer[]>([]);
  const [search, setSearch] = useState("");
  useEffect(() => { apiFetch("/api/v1/customers?limit=100").then((r) => setList(r.customers || r.items || r || [])).catch(() => {}); }, []);
  const filtered = search ? list.filter((c) => `${c.name} ${c.id} ${c.archetype} ${c.city}`.toLowerCase().includes(search.toLowerCase())) : list;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="rz-page-title flex items-center gap-2"><Users size={20} className="text-[#0B5CFF]" /> Customers</h1>
          <p className="rz-page-desc mt-1">{filtered.length} of {list.length} • archetypes, LTV, risk — single merchant scope</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input placeholder="Search id, name, archetype, city" value={search} onChange={(e) => setSearch(e.target.value)} className="rz-input pl-9 w-[300px] h-[40px] text-sm" />
          </div>
        </div>
      </div>

      <div className="flex items-center gap-2 text-xs">
        <span className="rz-label">Legend</span>
        {Object.entries(archetypeStyle).slice(0,3).map(([k,v]) => (
          <span key={k} className={`rz-pill border ${v}`}>{k.replaceAll("_"," ")}</span>
        ))}
        <span className="ml-auto rz-pill bg-white border text-slate-500">{list.length} total contexts</span>
      </div>

      <div className="rz-card overflow-hidden">
        <div className="overflow-auto">
          <table className="w-full text-sm">
            <thead className="bg-[#F9FAFB] border-b text-[11px] uppercase tracking-[0.06em] text-slate-500">
              <tr>
                <th className="px-4 py-3 text-left font-semibold">Customer</th>
                <th className="px-4 py-3 text-left font-semibold">Archetype</th>
                <th className="px-4 py-3 text-left font-semibold">City</th>
                <th className="px-4 py-3 text-right font-semibold">LTV</th>
                <th className="px-4 py-3 text-right font-semibold">Exposure</th>
                <th className="px-4 py-3 text-right font-semibold">Contacts</th>
                <th className="px-4 py-3 text-right font-semibold">Risk</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#EAECF0]">
              {filtered.length === 0 ? (
                <tr><td colSpan={7} className="px-4 py-12 text-center">
                  <div className="w-10 h-10 rounded-xl bg-slate-100 border flex items-center justify-center mx-auto"><Users size={16} className="text-slate-400" /></div>
                  <div className="text-sm text-slate-500 mt-3">No customers — run simulation to seed</div>
                </td></tr>
              ) : filtered.slice(0,80).map((c) => (
                <tr key={c.id} className="hover:bg-[#F9FAFB] transition-colors group">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2.5">
                      <span className="w-8 h-8 rounded-full bg-[#0B1020] text-white flex items-center justify-center text-[11px] font-bold">{(c.name || c.id).slice(0,2).toUpperCase()}</span>
                      <div>
                        <div className="font-semibold text-[13px] text-[#0B1020] group-hover:text-[#0B5CFF] transition-colors">{c.name || c.id}</div>
                        <div className="rz-mono text-slate-400 truncate max-w-[180px]">{c.id}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3"><span className={`rz-pill border text-[11px] ${archetypeStyle[c.archetype] || "bg-slate-100 border-slate-200"}`}>{c.archetype?.replaceAll("_"," ")}</span></td>
                  <td className="px-4 py-3 text-slate-600 text-[13px]">{c.city}</td>
                  <td className="px-4 py-3 text-right font-semibold text-[13px]">{currency(c.lifetime_value)}</td>
                  <td className="px-4 py-3 text-right text-slate-600 text-[13px]">{currency(c.current_discount_exposure)}</td>
                  <td className="px-4 py-3 text-right">
                    <span className="rz-pill bg-slate-900 text-white text-[11px]">{c.total_contacts_received}</span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-2">
                      <div className="w-16 h-1.5 bg-[#EAECF0] rounded-full overflow-hidden"><div className={`h-full rounded-full ${c.risk_score>0.7?"bg-red-500":c.risk_score>0.4?"bg-amber-500":"bg-emerald-500"}`} style={{width:`${Math.min(100,(c.risk_score||0)*100)}%`}} /></div>
                      <span className="text-xs font-medium text-slate-600 w-8 text-right">{((c.risk_score||0)*100).toFixed(0)}%</span>
                      {c.risk_score>0.7 ? <Shield size={12} className="text-red-400" /> : <TrendingUp size={12} className="text-slate-300" />}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {filtered.length>80 && <div className="px-4 py-2.5 text-xs text-slate-500 border-t bg-[#F9FAFB] flex items-center justify-between"><span>Showing 80 of {filtered.length}</span><span className="rz-mono">limit 100</span></div>}
      </div>
    </div>
  );
}
