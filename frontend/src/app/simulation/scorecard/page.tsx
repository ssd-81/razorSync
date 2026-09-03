"use client";
import { useState } from "react";
import { apiFetch } from "@/lib/api";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell } from "recharts";
import { Play, Loader2, TrendingUp, Shield, Wallet, AlertTriangle, BarChart3, Users, IndianRupee, FlaskConical } from "lucide-react";
import { safeFixed, safeCurrency, safeInt } from "@/lib/format";

export default function ScorecardPage() {
  const [numCustomers, setNumCustomers] = useState(200);
  const [seeds, setSeeds] = useState("42,137,256");
  const [duration, setDuration] = useState(7);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [jobId, setJobId] = useState<string | null>(null);
  const [scorecard, setScorecard] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const runSync = async () => {
    setLoading(true); setError(null); setProgress(0);
    try {
      const body = { num_customers: numCustomers, seeds: seeds.split(",").map((s) => parseInt(s.trim())).filter((n) => !isNaN(n)), duration_days: duration };
      const r = await apiFetch("/api/v1/simulation/scorecard", { method: "POST", body: JSON.stringify(body) }, 120000);
      setScorecard(r); setProgress(100);
    } catch (e: any) { setError(String(e)); } finally { setLoading(false); }
  };

  const runAsync = async () => {
    setLoading(true); setError(null); setProgress(0); setScorecard(null);
    try {
      const body = { num_customers: numCustomers, seeds: seeds.split(",").map((s) => parseInt(s.trim())).filter((n) => !isNaN(n)), duration_days: duration };
      const j = await apiFetch("/api/v1/simulation/scorecard/async", { method: "POST", body: JSON.stringify(body) });
      setJobId(j.job_id);
      let done = false;
      while (!done) {
        await new Promise((r) => setTimeout(r, 800));
        const st = await apiFetch(`/api/v1/simulation/scorecard/status/${j.job_id}`);
        setProgress(st.progress || 0);
        if (st.status === "completed") { setScorecard(st.result); done = true; setProgress(100); }
        if (st.status === "failed") { setError(st.error || "Job failed"); done = true; }
      }
    } catch (e: any) { setError(String(e)); } finally { setLoading(false); }
  };

  const run = () => {
    // Sync POST times out after 10s (apiFetch default) once dispatcher runs per
    // contact — 200x3 is well over that. Always use the async job + polling.
    return runAsync();
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="rz-page-title flex items-center gap-2"><BarChart3 size={20} className="text-[#0B5CFF]" /> Simulation Scorecard</h1>
          <p className="rz-page-desc mt-1">Multiple seeds with uncertainty bands. <span className="font-medium text-[#0B1020]">Net value</span> is headline P&amp;L.</p>
        </div>
        <span className="hidden sm:inline-flex rz-pill bg-[#0B5CFF] text-white">Policy + Guardrail</span>
      </div>

      {scorecard && scorecard.meta.num_customers < 200 && (
        <div className="rz-card px-4 py-3 flex items-start gap-3 bg-amber-50 border-amber-200">
          <AlertTriangle size={16} className="text-amber-600 mt-0.5 shrink-0" />
          <div className="flex-1">
            <div className="text-sm font-semibold text-amber-800">Small run</div>
            <div className="text-xs text-amber-700 mt-0.5">{scorecard.meta.num_customers} × {scorecard.meta.num_seeds} — wide uncertainty bands at this size.</div>
          </div>
          <button onClick={() => { setNumCustomers(200); setSeeds("42,137,256"); }} className="rz-btn-secondary text-xs h-8">Fix to 200×3 →</button>
        </div>
      )}

      {/* Controls */}
      <div className="rz-card p-5">
        <div className="flex items-center gap-2 mb-4">
          <span className="w-7 h-7 rounded-lg bg-slate-900 text-white flex items-center justify-center"><FlaskConical size={14} /></span>
          <span className="rz-section-title">Run parameters</span>
          <span className="ml-auto rz-pill bg-slate-50 border text-slate-500 text-[11px] hidden sm:inline-flex">Same rules apply</span>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-12 gap-3 items-end">
          <label className="md:col-span-3">
            <span className="rz-label">Customers / seed</span>
            <input type="number" value={numCustomers} onChange={(e) => setNumCustomers(parseInt(e.target.value) || 0)} className="rz-input mt-1.5" />
          </label>
          <label className="md:col-span-5">
            <span className="rz-label">Seeds (comma)</span>
            <input value={seeds} onChange={(e) => setSeeds(e.target.value)} className="rz-input mt-1.5" placeholder="42,137,256" />
          </label>
          <label className="md:col-span-2">
            <span className="rz-label">Days</span>
            <input type="number" value={duration} onChange={(e) => setDuration(parseInt(e.target.value) || 0)} className="rz-input mt-1.5" />
          </label>
          <button onClick={run} disabled={loading} className="md:col-span-2 rz-btn-primary h-[42px]">
            {loading ? <><Loader2 size={14} className="animate-spin" /> Running {progress}%</> : <><Play size={14} /> Run Simulation</>}
          </button>
        </div>
        {loading && (
          <div className="mt-4 space-y-2">
            <div className="rz-progress-track"><div className="rz-progress-fill" style={{ width: `${progress}%` }} /></div>
            <div className="flex items-center justify-between text-xs text-slate-500">
              <span className="rz-mono">progress {progress}% • {progress === 100 ? "done" : "running"}</span>
              <span className="rz-pill bg-slate-50 border text-slate-500">{progress === 100 ? "done" : "running"}</span>
            </div>
          </div>
        )}
      </div>

      {error && <div className="rz-card px-4 py-3 text-sm bg-red-50 border-red-200 text-red-700">{error}</div>}

      {scorecard && (
        <div className="space-y-6">
          {/* Headline 4 */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <HeadlineCard
              icon={Wallet} accent="bg-[#0B5CFF] text-white" title="Net Value" sub="Revenue − waste − churn"
              delta={`${safeFixed(scorecard.net_value.delta_pct.mean,1)}% Δ`} ci={`Range [${safeFixed(scorecard.net_value.delta_pct.low,1)}%, ${safeFixed(scorecard.net_value.delta_pct.high,1)}%]`}
              foot={`${scorecard.revenue.significant ? '✓ significant' : '✗ within noise'} • Uncoord ${safeCurrency(scorecard.net_value.uncoordinated_mean)} → Coord ${safeCurrency(scorecard.net_value.coordinated_mean)}`}
              extra={`Assumes ${Math.round(scorecard.net_value.lambda * 100)}% of LTV at risk`} highlight
            />
            <HeadlineCard icon={TrendingUp} accent="bg-emerald-600 text-white" title="Revenue / 1k msgs" sub="Efficiency"
              delta={`${safeFixed(scorecard.revenue_per_1000.delta_pct.mean,1)}% Δ`} ci={`Range [${safeFixed(scorecard.revenue_per_1000.delta_pct.low,1)}%, ${safeFixed(scorecard.revenue_per_1000.delta_pct.high,1)}%]`}
              foot={`Uncoord ${safeCurrency(scorecard.revenue_per_1000.uncoordinated_mean)} → Coord ${safeCurrency(scorecard.revenue_per_1000.coordinated_mean)}`} extra=""
            />
            <HeadlineCard icon={Shield} accent="bg-red-500 text-white" title="Churn Cost Saved" sub="LTV protected"
              delta={`${safeCurrency(scorecard.churn_cost.saved)} saved`} ci={`Range [${safeInt(scorecard.churn_cost.ci.low)}, ${safeInt(scorecard.churn_cost.ci.high)}]`}
              foot={`Uncoord ${safeCurrency(scorecard.churn_cost.uncoordinated_mean)} → Coord ${safeCurrency(scorecard.churn_cost.coordinated_mean)}`} extra=""
            />
            <HeadlineCard icon={AlertTriangle} accent="bg-amber-500 text-white" title="False Positive" sub="Blocked that would convert"
              delta={`${safeFixed(scorecard.false_positive.mean * 100,1)}%`} ci={`Range [${safeFixed(scorecard.false_positive.ci.low * 100,1)}%, ${safeFixed(scorecard.false_positive.ci.high * 100,1)}%]`}
              foot={scorecard.false_positive.note} extra=""
            />
          </div>

          {/* Secondary 4 */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <SmallCard title="Revenue / Contact" sub="Efficiency" delta={`${safeFixed(scorecard.revenue_per_contact.delta_pct.mean,1)}% Δ`} ci={`Range [${safeFixed(scorecard.revenue_per_contact.delta_pct.low,1)}%, ${safeFixed(scorecard.revenue_per_contact.delta_pct.high,1)}%]`} />
            <SmallCard title="Discount Waste Saved" delta={`${safeCurrency(scorecard.discount_waste.saved)}`} ci={`Range [${safeInt(scorecard.discount_waste.ci.low)}, ${safeInt(scorecard.discount_waste.ci.high)}]`} />
            <SmallCard title="Churn Reduction" delta={`${safeFixed(scorecard.churn.reduction_pct.mean,1)}% Δ`} ci={`Range [${safeFixed(scorecard.churn.reduction_pct.low,1)}%, ${safeFixed(scorecard.churn.reduction_pct.high,1)}%]`} />
            <SmallCard title="Total Revenue" sub="7-day raw" delta={`${safeFixed(scorecard.revenue.delta_pct.mean,1)}% Δ`} ci={scorecard.revenue.significant ? '✓ significant' : '✗ within noise'} />
          </div>

          {/* Charts */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <ChartCard title="Net Value" sub="With uncertainty band • headline P&L" data={scorecard.charts.net_value} colors={['#94A3B8', '#0B5CFF']} formatter={(v: number) => safeCurrency(v)} />
            <ChartCard title="Contact Volume" sub="Fewer contacts, same intent" data={scorecard.charts.contacts} colors={['#94A3B8', '#0EA5E9']} formatter={(v: number) => safeInt(v)} />
            <ChartCard title="Churn Cost" sub="Cost of lost customers" data={scorecard.charts.churn_cost} colors={['#FCA5A5', '#EF4444']} formatter={(v: number) => safeCurrency(v)} />
          </div>

          {/* v4: which agents did the work — dispatcher wins across all seeds */}
          {(scorecard.dispatcher || scorecard.agent_wins_chart) && (
            <div className="rz-card overflow-hidden">
              <div className="px-5 py-4 border-b bg-[#F9FAFB] flex items-center gap-2">
                <span className="rz-section-title">Agent wins — coordinated races</span>
                <span className="ml-auto rz-pill bg-white border text-slate-500">{scorecard.dispatcher?.races ?? 0} races • {scorecard.dispatcher?.policy_blocks ?? 0} policy blocks • {scorecard.dispatcher?.governor_blocks ?? 0} governor blocks</span>
              </div>
              <div className="p-5 grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
                <div>
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={scorecard.agent_wins_chart || []} layout="vertical" margin={{ left: 24 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#EAECF0" />
                      <XAxis type="number" tick={{ fontSize: 11, fill: "#667085" }} axisLine={false} tickLine={false} />
                      <YAxis type="category" dataKey="name" tick={{ fontSize: 11, fill: "#101828" }} axisLine={false} tickLine={false} width={150} />
                      <Tooltip contentStyle={{ borderRadius: 12, border: "1px solid #EAECF0", fontSize: 12 }} />
                      <Bar dataKey="value" radius={[0, 8, 8, 0]}>
                        {(scorecard.agent_wins_chart || []).map((_: any, idx: number) => (
                          <Cell key={idx} fill={['#0B5CFF', '#0EA5E9', '#8B5CF6', '#10B981'][idx % 4]} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <div className="space-y-2">
                  {(scorecard.agent_wins_chart || []).map((w: any) => (
                    <div key={w.name} className="flex items-center gap-2 text-sm border rounded-lg px-3 py-2">
                      <span className="rz-mono font-semibold">{w.name}</span>
                      <span className="ml-auto rz-pill bg-slate-900 text-white">{safeInt(w.value)} wins</span>
                    </div>
                  ))}
                  {(!scorecard.agent_wins_chart || scorecard.agent_wins_chart.length === 0) && <div className="text-xs text-slate-500">No dispatcher races recorded — run a simulation to see which agents win.</div>}
                  <div className="text-[11px] text-slate-500 leading-relaxed">Same policy scoring as live: winner per contact, governor can still veto. Per-seed breakdown in JSON below.</div>
                </div>
              </div>
            </div>
          )}

          <div className="rz-card overflow-hidden">
            <div className="px-5 py-3 border-b bg-[#F9FAFB] flex items-center gap-2">
              <span className="w-7 h-7 rounded-lg bg-white border flex items-center justify-center"><Users size={12} className="text-slate-500" /></span>
              <span className="rz-section-title">Per-seed Raw</span>
              <span className="ml-auto rz-pill bg-white border text-slate-500">{scorecard.meta.num_seeds} seeds</span>
            </div>
            <details className="px-5 py-4">
              <summary className="text-sm font-semibold cursor-pointer text-[#0B5CFF] hover:underline">Show JSON — all seeds, uncoordinated vs coordinated</summary>
              <pre className="text-xs bg-[#0B1020] text-slate-100 p-4 rounded-xl overflow-auto max-h-[420px] mt-3">{JSON.stringify(scorecard.per_seed, null, 2)}</pre>
            </details>
          </div>
        </div>
      )}

      {!scorecard && !loading && (
        <div className="rz-card p-8 text-center">
          <div className="w-12 h-12 rounded-xl bg-[#F2F4F7] border flex items-center justify-center mx-auto"><BarChart3 size={18} className="text-slate-400" /></div>
          <div className="text-sm font-semibold text-slate-700 mt-3">Ready to simulate</div>
          <div className="text-xs text-slate-500 mt-1">Try <span className="rz-mono bg-slate-50 border px-1.5 py-0.5 rounded">200 × 3</span> first, then <span className="rz-mono bg-slate-50 border px-1.5 py-0.5 rounded">500 × 20</span> for a full evaluation.</div>
        </div>
      )}
    </div>
  );
}

function HeadlineCard({ icon: Icon, accent, title, sub, delta, ci, foot, extra, highlight }: any) {
  return (
    <div className={`rz-card p-5 ${highlight ? "ring-1 ring-[#0B5CFF]/20 border-[#0B5CFF]/30" : ""}`}>
      <div className="flex items-center gap-2">
        <span className={`w-8 h-8 rounded-lg flex items-center justify-center ${accent}`}><Icon size={14} /></span>
        <div>
          <div className="text-sm font-semibold tracking-tight">{title}</div>
          <div className="text-[11px] text-slate-500">{sub}</div>
        </div>
      </div>
      <div className="text-[22px] font-bold tracking-tight mt-3">{delta}</div>
      <div className="text-xs text-slate-500 mt-1">{ci}</div>
      <div className="text-xs text-slate-600 mt-2 leading-relaxed">{foot}</div>
      {extra && <div className="rz-mono bg-slate-50 border px-2 py-1 rounded-full w-fit mt-2">{extra}</div>}
    </div>
  );
}

function SmallCard({ title, sub, delta, ci }: any) {
  return (
    <div className="rz-card p-4">
      <div className="text-sm font-semibold">{title}</div>
      {sub && <div className="text-[11px] text-slate-500">{sub}</div>}
      <div className="text-lg font-bold mt-2">{delta}</div>
      <div className="text-xs text-slate-500">{ci}</div>
    </div>
  );
}

function ChartCard({ title, sub, data, colors, formatter }: any) {
  return (
    <div className="rz-card overflow-hidden">
      <div className="px-5 py-4 border-b">
        <div className="text-sm font-semibold">{title}</div>
        <div className="text-xs text-slate-500">{sub}</div>
      </div>
      <div className="p-4">
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={data} barCategoryGap="30%">
            <CartesianGrid strokeDasharray="3 3" stroke="#EAECF0" />
            <XAxis dataKey="name" tick={{ fontSize: 11, fill: "#667085" }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 11, fill: "#667085" }} axisLine={false} tickLine={false} />
            <Tooltip
              contentStyle={{ borderRadius: 12, border: "1px solid #EAECF0", boxShadow: "0 4px 12px rgba(16,24,40,0.08)", fontSize: 12 }}
              formatter={(value: number) => [formatter(value), title]}
            />
            <Bar dataKey="value" radius={[8, 8, 0, 0]}>
              {data.map((_: any, idx: number) => (
                <Cell key={idx} fill={colors[idx % colors.length]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        <div className="flex flex-wrap gap-3 mt-2 text-xs text-slate-500">
          {data.map((e: any, i: number) => (
            <span key={i} className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{ background: colors[i] }} />{e.name}: {formatter(e.value)}</span>
          ))}
        </div>
      </div>
    </div>
  );
}
