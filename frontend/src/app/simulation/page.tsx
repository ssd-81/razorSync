import Link from "next/link";
import { FlaskConical, BarChart3, ArrowRight, Shield, Zap } from "lucide-react";

export default function SimIndex(){
  return (
    <div className="space-y-6 max-w-3xl">
      <div className="flex items-center gap-3">
        <span className="w-9 h-9 rounded-xl bg-[#0B5CFF] text-white flex items-center justify-center"><FlaskConical size={16} /></span>
        <h1 className="rz-page-title">Simulation</h1>
        <span className="rz-pill bg-emerald-50 text-emerald-700 border border-emerald-200">Engine parity</span>
      </div>
      <p className="rz-page-desc">Deterministic customer generation + windowed RulesEngine replay. Toggle a rule in <Link href="/rules" className="text-[#0B5CFF] font-medium hover:underline">Rules</Link> → re-run → numbers shift. Honest false-positive tracking.</p>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="rz-card p-5">
          <div className="flex items-center gap-2"><Shield size={14} className="text-[#0B5CFF]" /><span className="rz-section-title">Parity guarantee</span></div>
          <p className="text-sm text-slate-600 mt-2 leading-relaxed">Simulation calls <span className="rz-mono bg-slate-50 border px-1.5 py-0.5 rounded">RulesEngine.evaluate</span> — same IST, same windowed counts, same thresholds from <span className="rz-mono bg-slate-50 border px-1.5 py-0.5 rounded">BusinessRule</span>.</p>
        </div>
        <div className="rz-card p-5">
          <div className="flex items-center gap-2"><Zap size={14} className="text-amber-500" /><span className="rz-section-title">What you’ll see</span></div>
          <p className="text-sm text-slate-600 mt-2 leading-relaxed">Revenue/1k, net value (P&amp;L), churn cost, CIs, Welch p-value. 2 scenarios × N seeds.</p>
        </div>
      </div>

      <Link href="/simulation/scorecard" className="rz-btn-primary w-fit">Open Scorecard — CIs + p-values <ArrowRight size={14} /></Link>
    </div>
  );
}
