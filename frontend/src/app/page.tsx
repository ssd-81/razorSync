"use client";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { BarChart3, CheckCircle2, Settings2, Users, ArrowRight, Sparkles, Shield, Clock, Wallet, ChevronRight } from "lucide-react";
import { safeFixed } from "@/lib/format";
import Link from "next/link";

export default function Overview() {
  const [metrics, setMetrics] = useState<unknown>(null);
  const [failure, setFailure] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch("/api/v1/metrics").then(setMetrics).catch((e) => setError(String(e)));
    apiFetch("/api/v1/ops/failure-status").then((r) => setFailure(r.simulate_razorpay_failure)).catch(() => {});
  }, []);

  const m = metrics as any;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="rz-pill bg-emerald-50 text-emerald-700 border border-emerald-200">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" /> Live • v3 Production
            </span>
            <span className="rz-pill bg-slate-900 text-white">merchant_default</span>
          </div>
          <h1 className="rz-page-title mt-3">RazorSync — Coordination Engine</h1>
          <p className="rz-page-desc mt-2 max-w-3xl">
            Agents propose. <span className="font-medium text-slate-700">RazorSync disposes.</span> Single decision layer for Razorpay Agent Studio — native primitives, net-value P&amp;L, and human suspension for financial risk.
          </p>
        </div>
        <Link href="/ops" className="hidden md:inline-flex rz-btn-primary">
          Open Ops Console <ArrowRight size={14} />
        </Link>
      </div>

      {failure && (
        <div className="rz-card px-4 py-3 flex items-center gap-2.5 bg-amber-50 border-amber-200 text-amber-800">
          <span className="h-2 w-2 rounded-full bg-amber-500 shrink-0" />
          <span className="text-sm font-medium">Razorpay unavailable — using cached coordination decision</span>
          <span className="ml-auto text-xs opacity-70">Fallback active</span>
        </div>
      )}
      {error && <div className="rz-card px-4 py-3 text-sm bg-red-50 border-red-200 text-red-700">{error}</div>}

      {/* Metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard label="Total Decisions" value={m?.total_decisions ?? "—"} sub="All time" icon={BarChart3} accent="bg-slate-900 text-white" />
        <MetricCard label="Approval Rate" value={m?.total_decisions ? `${safeFixed((m.approved_count / m.total_decisions) * 100, 0)}%` : "—"} sub="Approved / total" icon={CheckCircle2} accent="bg-emerald-600 text-white" />
        <MetricCard label="Active Rules" value={m?.active_rules ?? "—"} sub="Governor guardrails" icon={Settings2} accent="bg-[#0B5CFF] text-white" />
        <MetricCard label="Customers" value={m?.total_customers ?? "—"} sub="Contexts loaded" icon={Users} accent="bg-slate-700 text-white" />
      </div>

      {/* Architecture + Evaluation */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        <div className="lg:col-span-3 rz-card p-6">
          <div className="flex items-center gap-2 mb-4">
            <span className="w-7 h-7 rounded-lg bg-[#0B5CFF] text-white flex items-center justify-center"><Shield size={14} /></span>
            <h2 className="rz-section-title">Pipeline</h2>
            <span className="ml-auto rz-pill bg-slate-50 border text-slate-600">WAL • Redis • HITL</span>
          </div>

          {/* Visual pipeline */}
          <div className="flex items-center gap-1.5 overflow-auto py-1">
            <PipelineStep label="Webhook" sub="HMAC" color="bg-slate-900 text-white" />
            <ChevronRight size={14} className="text-slate-300 shrink-0" />
            <PipelineStep label="Dispatcher" sub="Policy score" color="bg-[#0B5CFF] text-white" />
            <ChevronRight size={14} className="text-slate-300 shrink-0" />
            <PipelineStep label="Governor" sub="5 rules IST" color="bg-emerald-600 text-white" />
            <ChevronRight size={14} className="text-slate-300 shrink-0" />
            <PipelineStep label="Guardrail" sub="hard/soft" color="bg-amber-500 text-white" />
            <ChevronRight size={14} className="text-slate-300 shrink-0" />
            <PipelineStep label="Execute" sub="audit" color="bg-violet-600 text-white" />
          </div>

          <div className="rz-divider my-4" />
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
            <div className="rounded-xl bg-slate-50 border p-3">
              <div className="font-semibold text-slate-800 flex items-center gap-1.5"><Sparkles size={12} /> Agents</div>
              <div className="text-slate-500 mt-1 leading-relaxed">autopay_retry · payment_link_recovery · invoice_dunning · x_payout_growth</div>
            </div>
            <div className="rounded-xl bg-slate-50 border p-3">
              <div className="font-semibold text-slate-800 flex items-center gap-1.5"><Settings2 size={12} /> Guardrails</div>
              <div className="text-slate-500 mt-1 leading-relaxed">frequency · cooldown · time window · budget · financial ceiling</div>
            </div>
            <div className="rounded-xl bg-amber-50 border border-amber-200 p-3">
              <div className="font-semibold text-amber-800 flex items-center gap-1.5"><Users size={12} /> HITL</div>
              <div className="text-amber-700 mt-1 leading-relaxed">hard → SUSPEND → human approve / reject → re-validate</div>
            </div>
          </div>
        </div>

        <div className="lg:col-span-2 rz-card p-6">
          <div className="flex items-center gap-2 mb-4">
            <span className="w-7 h-7 rounded-lg bg-slate-900 text-white flex items-center justify-center"><Clock size={14} /></span>
            <h2 className="rz-section-title">Evaluation Workflow</h2>
            <span className="ml-auto rz-pill bg-emerald-50 text-emerald-700 border border-emerald-200">Ready</span>
          </div>
          <div className="space-y-3">
            {[
              { t: "01", d: "Live Checkout → webhook → decision appears" },
              { t: "02", d: "Dispatcher scores → guardrail verdict with reason" },
              { t: "03", d: "Scorecard — revenue/1k and net value with 95% CI" },
              { t: "04", d: "Toggle rules → re-run → compare outcomes" },
            ].map((s) => (
              <div key={s.t} className="flex gap-3">
                <span className="rz-mono bg-slate-900 text-white px-2 py-1 rounded-lg h-fit shrink-0">{s.t}</span>
                <span className="text-sm text-slate-600 leading-relaxed pt-0.5">{s.d}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* CTAs */}
      <div className="rz-card p-4">
        <div className="flex items-center gap-2 mb-3">
          <Wallet size={14} className="text-slate-400" />
          <span className="text-xs font-semibold tracking-wide text-slate-500 uppercase">Start here</span>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href="/checkout" className="rz-btn-primary">Live Checkout <ArrowRight size={14} /></Link>
          <Link href="/ops" className="rz-btn-primary bg-slate-900 border-slate-900 hover:bg-black">Ops Console</Link>
          <Link href="/execution" className="rz-btn-secondary">Execution Graph</Link>
          <div className="w-px h-6 bg-slate-200 mx-1 self-center hidden sm:block" />
          <Link href="/simulation/scorecard" className="rz-btn-ghost border">Scorecard</Link>
          <Link href="/rules" className="rz-btn-ghost border">Rules</Link>
          <Link href="/customers" className="rz-btn-ghost border">Customers</Link>
          <Link href="/audit" className="rz-btn-ghost border">Audit</Link>
        </div>
      </div>
    </div>
  );
}

function MetricCard({ label, value, sub, icon: Icon, accent }: { label: string; value: any; sub: string; icon: any; accent: string }) {
  return (
    <div className="rz-card p-4 rz-card-hover">
      <div className="flex items-start justify-between">
        <span className={`w-9 h-9 rounded-xl flex items-center justify-center ${accent}`}><Icon size={16} /></span>
        <span className="rz-pill bg-slate-50 border text-slate-500 text-[10px]">{sub}</span>
      </div>
      <div className="text-2xl font-bold mt-3 tracking-tight text-[#0B1020]">{value}</div>
      <div className="text-xs font-medium text-slate-500 mt-1">{label}</div>
    </div>
  );
}

function PipelineStep({ label, sub, color }: { label: string; sub: string; color: string }) {
  return (
    <div className={`px-3 py-2 rounded-xl text-xs font-semibold leading-tight shrink-0 ${color}`}>
      <div>{label}</div>
      <div className="text-[10px] opacity-80 font-medium">{sub}</div>
    </div>
  );
}
