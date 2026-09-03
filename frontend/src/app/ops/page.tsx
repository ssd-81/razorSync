"use client";
import { useEffect, useState, useRef } from "react";
import { apiFetch } from "@/lib/api";
import { formatISTTime, formatISTDateTime } from "@/lib/format";
import { MessageCircle, Smartphone, Mail, Bell, MonitorSmartphone, Check, Ban, Clock, AlertTriangle, Activity, Cpu } from "lucide-react";
import FullCycleCard from "@/components/FullCycleCard";

interface Decision {
  id: string;
  customer_id: string;
  verdict: string;
  block_reason: string | null;
  reasoning: string;
  source: string;
  created_at: string;
  trigger_event?: string | null;
  dispatcher_winner?: string | null;
  dispatcher?: { candidates: any[]; winner?: string | null } | null;
  action: { agent_type: string; channel: string; amount_involved: number; discount_offered: number; message_preview?: string | null } | null;
  rules_applied: string | null;
}

const CHANNEL_META: Record<string, { Icon: any; label: string; color: string }> = {
  whatsapp: { Icon: MessageCircle, label: "WhatsApp", color: "text-emerald-600 bg-emerald-50 border-emerald-200" },
  sms: { Icon: Smartphone, label: "SMS", color: "text-sky-600 bg-sky-50 border-sky-200" },
  email: { Icon: Mail, label: "Email", color: "text-slate-600 bg-slate-50 border-slate-200" },
  push: { Icon: Bell, label: "Push", color: "text-amber-600 bg-amber-50 border-amber-200" },
  in_app: { Icon: MonitorSmartphone, label: "In-App", color: "text-violet-600 bg-violet-50 border-violet-200" },
};
const AGENT_META: Record<string, { label: string; dot: string }> = {
  autopay_retry: { label: "Autopay Retry", dot: "bg-sky-500" },
  payment_link_recovery: { label: "Link Recovery", dot: "bg-emerald-500" },
  invoice_dunning: { label: "Invoice Dunning", dot: "bg-amber-500" },
  x_payout_growth: { label: "X Payout", dot: "bg-violet-500" },
};

export default function OpsPage() {
  const [customers, setCustomers] = useState<any[]>([]);
  const [selectedCustomer, setSelectedCustomer] = useState("");
  const [amount, setAmount] = useState(500);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [lastTs, setLastTs] = useState<string | null>(null);
  const [orderResult, setOrderResult] = useState<any>(null);
  const [failure, setFailure] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);
  const [loadingOrder, setLoadingOrder] = useState(false);
  const [inbox, setInbox] = useState<any[]>([]);
  const [agents, setAgents] = useState<any>(null);
  const [llm, setLlm] = useState<any>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const pollRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    apiFetch("/api/v1/customers?limit=20").then((r) => {
      const list = r.customers || r.items || r || [];
      setCustomers(Array.isArray(list) ? list : []);
      if (list.length) setSelectedCustomer(list[0].id);
    }).catch(() => apiFetch("/api/v1/simulation/seed", { method: "POST" }).then(() => apiFetch("/api/v1/customers?limit=20").then((r) => {
      const list = r.customers || r.items || r || []; setCustomers(list); if (list.length) setSelectedCustomer(list[0].id);
    })));
    apiFetch("/api/v1/ops/failure-status").then((r) => setFailure(r.simulate_razorpay_failure)).catch(() => {});
    apiFetch("/api/v1/decisions/recent?limit=20").then((d) => {
      if (Array.isArray(d)) { const asc=[...d].reverse(); setDecisions(asc); if(asc.length) setLastTs(asc[asc.length-1].created_at); }
    }).catch(()=>{});
    apiFetch("/api/v1/webhook/inbox?limit=10").then((r)=> setInbox(Array.isArray(r)?r:[])).catch(()=>{});
    apiFetch("/api/v1/agents").then(setAgents).catch(()=>{});
    apiFetch("/api/v1/agents/llm/status").then(setLlm).catch(()=>{});
  }, []);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      if (document.hidden || cancelled) return;
      try {
        const qs = lastTs ? `?since=${encodeURIComponent(lastTs)}` : "?limit=20";
        const [res, ib] = await Promise.all([
          apiFetch(`/api/v1/decisions/recent${qs}`).catch(()=>[]),
          apiFetch("/api/v1/webhook/inbox?limit=10").catch(()=>[]),
        ]);
        if (cancelled) return;
        if (Array.isArray(res) && res.length) { const asc=[...res].reverse(); setDecisions((p)=>[...p,...asc]); setLastTs(asc[asc.length-1].created_at); }
        if (Array.isArray(ib)) setInbox(ib);
      } catch {}
    };
    // LLM status changes rarely — refresh on its own slower loop.
    const llmTick = async () => {
      if (document.hidden || cancelled) return;
      const ls = await apiFetch("/api/v1/agents/llm/status").catch(()=>null);
      if (ls && !cancelled) setLlm(ls);
    };
    pollRef.current = setInterval(tick, 3000);
    const llmRef = setInterval(llmTick, 10000);
    return () => { cancelled = true; if (pollRef.current) clearInterval(pollRef.current); clearInterval(llmRef); };
  }, [lastTs]);

  const createOrder = async () => {
    if (!selectedCustomer) return;
    setLoadingOrder(true); setBanner(null);
    try {
      const body = { amount: amount*100, currency: "INR", customer_id: selectedCustomer, receipt: `rcpt_${Date.now()}` };
      const r = await apiFetch("/api/v1/orders", { method: "POST", body: JSON.stringify(body) });
      setOrderResult(r); if (r.banner) setBanner(r.banner);
      else setBanner(r.note || `Order ${r.order?.id} created — send a test event or complete payment for a decision.`);
      setTimeout(()=> apiFetch("/api/v1/webhook/inbox?limit=5").then(setInbox).catch(()=>{}), 800);
    } catch (e:any) { setBanner(String(e)); }
    finally { setLoadingOrder(false); }
  };

  const createWebhookSample = async () => {
    // Local console helper only. Signs with a non-secret placeholder value.
    // Real Razorpay webhooks are verified against RAZORPAY_WEBHOOK_SECRET
    // configured in backend/.env (never committed, never shipped to the browser).
    // Run backend with an empty RAZORPAY_WEBHOOK_SECRET for local work (verification skipped in dev mode).
    try {
      const payload = { event:"payment.failed", payload:{ payment:{ entity:{ id:`pay_ops_${Date.now()}`, order_id:`order_ops_${Date.now()}`, amount: amount*100, notes:{ customer_id: selectedCustomer } } } } };
      const raw = JSON.stringify(payload);
      const enc = new TextEncoder();
      const OPS_ONLY_SIGNING_VALUE = "local_ops_only_not_a_secret";
      const key = await crypto.subtle.importKey("raw", enc.encode(OPS_ONLY_SIGNING_VALUE), {name:"HMAC", hash:"SHA-256"}, false, ["sign"]);
      const sigBuf = await crypto.subtle.sign("HMAC", key, enc.encode(raw));
      const sig = Array.from(new Uint8Array(sigBuf)).map(b=>b.toString(16).padStart(2,"0")).join("");
      const r = await apiFetch("/api/v1/webhook/razorpay", { method:"POST", body: raw, headers: {"X-Razorpay-Signature": sig} as any });
      setBanner(`Queued ${r.inbox_id} → ${r.dispatcher?.winner ?? r.decision?.verdict ?? "pending"}`);
      apiFetch("/api/v1/webhook/inbox?limit=10").then(setInbox).catch(()=>{});
    } catch (e:any) { setBanner(String(e)); }
  };

  const toggleFailure = async () => {
    const next = !failure;
    const r = await apiFetch("/api/v1/ops/failure-toggle", { method:"POST", body: JSON.stringify({enabled: next})});
    setFailure(r.simulate_razorpay_failure); setBanner(r.banner);
  };

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="rz-page-title mt-2">Operations</h1>
          <p className="rz-page-desc mt-1 max-w-2xl">Create orders, review every verdict, and inspect how each one was scored.</p>
        </div>
        <div className="hidden md:flex items-center gap-2">
          <span className={`rz-pill border ${!llm ? "bg-white text-slate-400" : llm.enabled ? "bg-violet-600 text-white border-violet-600" : "bg-white text-slate-600"}`}>{!llm ? "…" : llm.enabled ? llm.model : "Built-in"}</span>
          <span className={`rz-pill border ${failure ? "bg-amber-500 text-white border-amber-500" : "bg-emerald-50 text-emerald-700 border-emerald-200"}`}>{failure ? "Drill on" : "Normal"}</span>
        </div>
      </div>

      {banner && <div className="rz-card px-4 py-3 text-sm flex gap-2.5 items-center bg-amber-50 border-amber-200 text-amber-800"><AlertTriangle size={16} className="shrink-0" />{banner}</div>}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-start">
        {/* Main column */}
        <div className="lg:col-span-2 space-y-4">
          <div className="rz-card p-5">
            <h2 className="font-semibold text-sm">Create order</h2>
            <p className="text-xs text-slate-500 mt-1 mb-4">An order starts the whole chain — create one, or send a ready-made event.</p>
            <div className="flex flex-wrap gap-3 items-end">
              <label className="flex flex-col gap-1.5">
                <span className="rz-label">Customer</span>
                <select value={selectedCustomer} onChange={(e)=>setSelectedCustomer(e.target.value)} className="rz-select min-w-[240px]">
                  {customers.map((c)=><option key={c.id} value={c.id}>{c.id} — {c.name || c.archetype}</option>)}
                </select>
              </label>
              <label className="flex flex-col gap-1.5">
                <span className="rz-label">Amount ₹</span>
                <input type="number" value={amount} onChange={(e)=>setAmount(Number(e.target.value))} className="rz-input w-28" />
              </label>
              <button onClick={createOrder} disabled={loadingOrder} className="rz-btn-primary">{loadingOrder?"Creating…":"Create Order"}</button>
              <button onClick={createWebhookSample} className="rz-btn-secondary"><Activity size={14} /> Send test event</button>
            </div>
            {orderResult && (
              <div className="mt-4 grid grid-cols-3 gap-3 text-xs">
                <div className="bg-slate-50 rounded-lg p-3 border"><div className="text-slate-500 text-[11px] uppercase tracking-wide">Order ID</div><div className="rz-mono font-medium truncate mt-1">{orderResult.order?.id}</div></div>
                <div className="bg-slate-50 rounded-lg p-3 border"><div className="text-slate-500 text-[11px] uppercase tracking-wide">Status</div><div className={`font-semibold mt-1 ${orderResult.order?.fallback?"text-amber-600":"text-emerald-600"}`}>{orderResult.order?.status}</div></div>
                <div className="bg-slate-50 rounded-lg p-3 border"><div className="text-slate-500 text-[11px] uppercase tracking-wide">Latency</div><div className="font-medium mt-1">{orderResult.latency_ms ?? "—"} ms</div></div>
                {orderResult.note && <div className="col-span-3 bg-slate-50 border rounded-lg p-3 text-xs leading-relaxed text-slate-600">{orderResult.note}</div>}
              </div>
            )}
          </div>

          <div className="rz-card p-5">
            <div className="flex items-center gap-2 mb-1">
              <h2 className="font-semibold text-sm">Decisions</h2>
              <span className="ml-auto text-xs text-slate-400">{decisions.length} decisions</span>
            </div>
            <p className="text-xs text-slate-500 mt-1 mb-4">Every verdict lands here with the reason attached — click any row to inspect the full race. Newest at the bottom.</p>
            {(() => {
              const sel = decisions.find((x) => x.id === selectedId) || [...decisions].slice(-1)[0];
              return sel ? <div className="mb-4"><FullCycleCard d={sel as any} /></div> : null;
            })()}
            {decisions.length===0 ? <div className="text-sm text-slate-400 py-8 text-center border border-dashed rounded-xl">Nothing yet — complete step 1 above</div> : (
              <div className="relative ml-4">
                <div className="timeline-line" />
                <div className="space-y-3">
                  {[...decisions].reverse().slice(0,10).map((d)=> {
                    const ch = d.action?.channel; const meta = ch ? CHANNEL_META[ch] : null; const Icon = meta?.Icon;
                    const isBlocked = d.verdict==="blocked";
                    const isSel = d.id === (selectedId || [...decisions].slice(-1)[0]?.id);
                    return (
                    <div key={d.id} className="relative pl-8">
                      <span className={`absolute left-[6px] top-3 w-2.5 h-2.5 rounded-full ring-4 ring-white ${isBlocked?"bg-slate-300":"bg-emerald-500"}`} />
                      <button onClick={()=>setSelectedId(d.id)} className="w-full text-left">
                      <div className={`rounded-xl border p-3 transition bg-white ${isSel?"ring-1 ring-[#0B5CFF] border-[#0B5CFF]/40":"border-slate-200"}`}>
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className={`inline-flex items-center gap-1 rz-pill border ${isBlocked?"bg-slate-100 text-slate-500 border-slate-200":"bg-emerald-50 text-emerald-700 border-emerald-200"}`}>{isBlocked?<Ban size={12} className="text-slate-400" />:<Check size={12} className="text-emerald-600" />}{d.verdict}</span>
                          {d.action && <span className={`inline-flex items-center gap-1 rz-pill border ${meta?.color || "bg-slate-50"}`}>{Icon && <Icon size={12} />}{AGENT_META[d.action.agent_type]?.label || d.action.agent_type}</span>}
                          <span className="rz-pill bg-slate-900 text-white text-[11px]">{d.source}</span>
                          <span className="ml-auto text-[11px] text-slate-400" title={formatISTDateTime(d.created_at)}>{formatISTTime(d.created_at)} IST • {d.customer_id.slice(0,12)}</span>
                        </div>
                        <div className="text-sm mt-2 font-medium leading-relaxed text-slate-800">{d.reasoning}</div>
                        {d.block_reason && <div className="text-xs text-slate-500 mt-1.5 pl-2 border-l-2 border-slate-200 leading-relaxed">{d.block_reason}</div>}
                        {(d.dispatcher?.candidates?.length || d.trigger_event) && <div className="text-[11px] text-slate-500 mt-1.5 rz-mono">{d.trigger_event || "event"} • {(d.dispatcher?.candidates?.length || 0)} scored • winner {d.dispatcher?.winner || d.dispatcher_winner || d.action?.agent_type || "—"}</div>}
                      </div>
                      </button>
                    </div>
                  )})}
                </div>
              </div>
            )}
          </div>

          <div className="rz-card p-5">
            <h2 className="font-semibold text-sm">Agents and scoring</h2>
            <p className="text-xs text-slate-500 mt-1 mb-4">Each contender is scored on revenue, churn risk, and cost — the winner runs unless a guardrail vetoes it.</p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {agents ? Object.entries(agents.agents || agents).slice(0,4).map(([k,v]:any)=> {
                const chs = (v as any).channels||[];
                return (
                <div key={k} className="border rounded-xl p-3 bg-white hover:border-slate-300 transition">
                  <div className="flex items-center gap-2"><span className={`h-2 w-2 rounded-full ${AGENT_META[k]?.dot || "bg-slate-400"}`} /><span className="font-semibold text-sm">{AGENT_META[k]?.label || k}</span><span className="ml-auto rz-mono bg-slate-100 border px-2 py-0.5 rounded text-[11px]">{k}</span></div>
                  <div className="text-xs text-slate-500 mt-1.5 leading-relaxed line-clamp-2">{(v as any).description}</div>
                  <div className="flex gap-1.5 mt-2.5 flex-wrap">
                    {chs.map((ch:string)=>{const m=CHANNEL_META[ch]; const Icon=m?.Icon; return <span key={ch} className={`inline-flex items-center gap-1 rz-pill border ${m?.color || "bg-white"}`}><Icon size={12} />{ch}</span>})}
                  </div>
                  <div className="text-[11px] text-slate-400 mt-2">trigger <code className="rz-mono bg-slate-50 px-1 py-0.5 rounded">{(v as any).trigger}</code></div>
                </div>
              )}) : <div className="text-xs text-slate-400">Loading agents…</div>}
            </div>
            <p className="text-[11px] text-slate-400 mt-3 leading-relaxed">Scores persist on every decision — select any verdict above to replay its race, winner, guardrail veto, and customer message.</p>
          </div>

        </div>

        {/* Side rail: system state */}
        <div className="space-y-4">
          <div className="rz-card p-5">
            <h2 className="font-semibold text-sm flex items-center gap-2"><Cpu size={14} className="text-violet-600" /> System</h2>
            <div className="mt-3 space-y-2.5">
              <div className="flex items-center justify-between p-2.5 rounded-lg bg-slate-50 border"><span className="text-xs text-slate-500">Provider</span><span className="rz-pill bg-slate-900 text-white">{llm?.provider || "—"}</span></div>
              <div className="p-2.5 rounded-lg bg-slate-50 border"><div className="text-[11px] uppercase tracking-wide text-slate-500">Model</div><div className="rz-mono font-medium mt-1 truncate">{llm?.model || "—"}</div><div className={`rz-pill mt-2 inline-flex ${llm?.enabled?"bg-violet-600 text-white":"bg-white border text-slate-600"}`}>{llm?.enabled?"enabled":"built-in"}</div></div>
              <div className="flex items-center justify-between p-2.5 rounded-lg bg-slate-50 border">
                <span className="text-xs text-slate-500">Outage drill</span>
                <button onClick={toggleFailure} className={`rz-pill border text-xs font-bold h-7 px-3 ${failure?"bg-amber-500 text-white border-amber-500":"bg-[#0B1020] text-white border-[#0B1020]"}`}>{failure?"On":"Off"}</button>
              </div>
              <div className="text-[11px] leading-relaxed text-slate-500">With the drill on, orders take the fallback path: cached decision, banner, audit entry.</div>
            </div>
          </div>
          <div className="rz-card p-4">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold flex items-center gap-1.5"><Clock size={14} /> Recent events</span>
            </div>
            <div className="mt-3 space-y-1.5 max-h-[300px] overflow-auto pr-1">
              {inbox.length===0? <div className="text-xs text-slate-400 py-6 text-center border border-dashed rounded-lg">No events yet</div> : inbox.slice(0,8).map((i)=>(
                <div key={i.id} className="flex items-center gap-2 p-2 rounded-lg border bg-white text-xs">
                  <span className={`h-1.5 w-1.5 rounded-full ${i.status==="completed"?"bg-emerald-500":"bg-amber-500"}`} />
                  <span className="rz-mono flex-1 truncate">{i.event}</span>
                  <span className={`rz-pill text-[11px] ${i.status==="completed"?"bg-emerald-600 text-white":"bg-amber-500 text-white"}`}>{i.status}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
