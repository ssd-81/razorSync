import Link from "next/link";
import { FlaskConical, BarChart3, ArrowRight, Shield, Zap } from "lucide-react";

export default function SimIndex(){
  return (
    <div className="space-y-6 max-w-3xl">
      <div className="flex items-center gap-3">
        <span className="w-9 h-9 rounded-xl bg-[#0B5CFF] text-white flex items-center justify-center"><FlaskConical size={16} /></span>
        <h1 className="rz-page-title">Simulation</h1>
        <span className="rz-pill bg-emerald-50 text-emerald-700 border border-emerald-200">Same engine</span>
      </div>
      <p className="rz-page-desc">Customers are generated from fixed seeds and every proposal is checked against the same active rules. Toggle a rule in <Link href="/rules" className="text-[#0B5CFF] font-medium hover:underline">Rules</Link> → re-run → numbers shift, with false positives tracked throughout.</p>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="rz-card p-5">
          <div className="flex items-center gap-2"><Shield size={14} className="text-[#0B5CFF]" /><span className="rz-section-title">Same rules</span></div>
          <p className="text-sm text-slate-600 mt-2 leading-relaxed">Simulation checks every proposal against the active rule set — same time windows, same limits, same thresholds.</p>
        </div>
        <div className="rz-card p-5">
          <div className="flex items-center gap-2"><Zap size={14} className="text-amber-500" /><span className="rz-section-title">What you’ll see</span></div>
          <p className="text-sm text-slate-600 mt-2 leading-relaxed">Revenue per contact, net value (P&amp;L), churn cost, and error rates across scenarios and seeds.</p>
        </div>
      </div>

      <Link href="/simulation/scorecard" className="rz-btn-primary w-fit">Open Scorecard <ArrowRight size={14} /></Link>
    </div>
  );
}
