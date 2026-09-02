"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { CreditCard, Zap, GitBranch, BarChart3, FlaskConical, Settings2, Users, ClipboardList } from "lucide-react";

const groups = [
  {
    label: "LIVE",
    items: [
      { href: "/checkout", icon: CreditCard, label: "Checkout" },
      { href: "/ops", icon: Zap, label: "Ops Console" },
      { href: "/execution", icon: GitBranch, label: "Execution Graph" },
    ],
  },
  {
    label: "ANALYTICS",
    items: [
      { href: "/simulation/scorecard", icon: BarChart3, label: "Scorecard" },
      { href: "/simulation", icon: FlaskConical, label: "Simulation" },
    ],
  },
  {
    label: "OPERATIONS",
    items: [
      { href: "/rules", icon: Settings2, label: "Rules" },
      { href: "/customers", icon: Users, label: "Customers" },
      { href: "/audit", icon: ClipboardList, label: "Audit Trail" },
    ],
  },
];

export default function Sidebar() {
  const pathname = usePathname();
  const isActive = (href: string) =>
    pathname === href || (href !== "/" && pathname?.startsWith(href));

  return (
    <aside className="w-[240px] bg-[#0B1020] text-white flex flex-col shrink-0 border-r border-white/[0.06] sticky top-0 h-screen">
      <div className="px-5 py-5 border-b border-white/[0.07]">
        <Link href="/" className="flex items-center gap-2.5 group">
          <span className="w-8 h-8 rounded-lg bg-[#0B5CFF] flex items-center justify-center text-white font-bold text-[13px] tracking-tight">Rz</span>
          <div>
            <div className="font-bold text-[15px] tracking-tight leading-none text-white group-hover:text-blue-100 transition-colors">RazorSync</div>
            <div className="text-[11px] text-slate-400 font-medium mt-0.5 tracking-wide">Coordination Engine • v3</div>
          </div>
        </Link>
      </div>

      <nav className="flex-1 py-4 px-3 space-y-6 overflow-auto">
        {groups.map((g) => (
          <div key={g.label}>
            <div className="px-2 mb-2 text-[10px] font-semibold tracking-widest text-slate-500">{g.label}</div>
            <div className="space-y-1">
              {g.items.map(({ href, icon: Icon, label }) => {
                const active = isActive(href);
                return (
                  <Link
                    key={href}
                    href={href}
                    className={`flex items-center gap-2.5 px-2.5 py-2 text-[13px] rounded-lg transition-all ${
                      active ? "bg-white text-[#0B1020] font-semibold shadow-sm" : "text-slate-300 hover:text-white hover:bg-white/[0.07]"
                    }`}
                  >
                    <Icon size={16} className={active ? "opacity-100 text-[#0B5CFF]" : "opacity-80"} />
                    {label}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      <div className="px-4 py-4 border-t border-white/[0.07] space-y-3">
        <div className="flex items-center gap-2 text-[11px] font-medium text-slate-300">
          <span className="h-2 w-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.6)] animate-pulse" /> Live • Razorpay Test
        </div>
        <div className="flex items-center gap-1.5">
          <span className="rz-pill bg-white/10 text-slate-300 border border-white/10 text-[10px]">Polling 2s</span>
          <span className="rz-pill bg-white/10 text-slate-300 border border-white/10 text-[10px]">95% CI</span>
          <span className="rz-pill bg-white/10 text-slate-300 border border-white/10 text-[10px]">WAL</span>
        </div>
      </div>
    </aside>
  );
}
