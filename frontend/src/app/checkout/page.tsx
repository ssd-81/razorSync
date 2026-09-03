"use client";
import { useState, useEffect, useCallback } from "react";
import { apiFetch } from "@/lib/api";
import { CreditCard, CheckCircle2, XCircle, Loader2, ArrowLeft, Shield, Clock } from "lucide-react";

declare global { interface Window { Razorpay: any; } }
interface CheckoutOrder { order_id: string; key_id: string; amount: number; currency: string; customer_id: string; }
interface Decision { id: string; verdict: string; block_reason: string | null; reasoning: string; source: string; created_at: string; action: { agent_type: string; channel: string; amount_involved: number; discount_offered: number } | null; }

export default function CheckoutPage() {
  const [mounted, setMounted] = useState(false);
  const [customers, setCustomers] = useState<any[]>([]);
  const [selectedCustomer, setSelectedCustomer] = useState("");
  const [amount, setAmount] = useState(1000); // ₹1000 ensures policy score >0 for all archetypes (high LTV 15k needs >~1030 to be profitable; 500 still negative for high-risk)
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState<"form" | "paying" | "waiting" | "done">("form");
  const [orderResult, setOrderResult] = useState<any>(null);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState("");

  useEffect(() => {
    setMounted(true);
    const script = document.createElement("script");
    script.src = "https://checkout.razorpay.com/v1/checkout.js";
    script.async = true;
    document.body.appendChild(script);
    apiFetch("/api/v1/customers?limit=20").then((r) => {
      const list = r.customers || r.items || r || [];
      setCustomers(Array.isArray(list) ? list : []);
      if (Array.isArray(list) && list.length > 0) setSelectedCustomer(list[0].id);
    }).catch(() => {});
    return () => { try { document.body.removeChild(script); } catch {} };
  }, []);

  const pollDecision = useCallback(async (customerId: string) => {
    setStatusMessage("Confirming payment…");
    for (let i = 0; i < 30; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      try {
        const decisions = await apiFetch("/api/v1/decisions/recent?limit=5") as any[];
        if (Array.isArray(decisions)) {
          const match = decisions.find((d: any) => d.customer_id === customerId && d.source === "live");
          if (match) { setDecision(match); setStep("done"); setStatusMessage(""); return; }
        }
      } catch {}
      setStatusMessage(`Confirming payment… (${i + 1}/30)`);
    }
    setError("Confirmation timed out — payment may still have succeeded. Check Ops for the latest decision or try again.");
    setStatusMessage("");
    setStep("form");
  }, []);

  const handlePayment = async () => {
    if (!selectedCustomer || typeof window === "undefined" || !window.Razorpay) { setError("Razorpay Checkout not loaded. Refresh the page."); return; }
    setLoading(true); setError(null); setStep("paying");
    try {
      const order: CheckoutOrder = await apiFetch("/api/v1/checkout/order", { method: "POST", body: JSON.stringify({ amount: amount * 100, currency: "INR", customer_id: selectedCustomer }) });
      setOrderResult(order);
      const rzp = new window.Razorpay({
        key: order.key_id,
        order_id: order.order_id,
        amount: order.amount,
        currency: order.currency,
        name: "RazorSync",
        description: `Test payment for ${selectedCustomer}`,
        handler: function (response: any) {
          setOrderResult((prev: any) => ({ ...prev, payment_id: response.razorpay_payment_id }));
          setStep("waiting");
          pollDecision(selectedCustomer);
        },
        prefill: { contact: customers.find((c) => c.id === selectedCustomer)?.phone || "", email: customers.find((c) => c.id === selectedCustomer)?.email || "" },
        theme: { color: "#0B5CFF" },
        modal: { ondismiss: function () { setStep("form"); setLoading(false); setError("Payment cancelled."); } },
        // Request all methods — popup only shows what’s enabled in Dashboard. If only Card appears, enable UPI/Netbanking there.
        config: {
          display: {
            blocks: {
              upi: { name: "UPI", instruments: [{ method: "upi" }] },
              card: { name: "Card", instruments: [{ method: "card" }] },
              netbanking: { name: "Netbanking", instruments: [{ method: "netbanking" }] },
              wallet: { name: "Wallet", instruments: [{ method: "wallet" }] },
            },
            sequence: ["block.upi", "block.card", "block.netbanking", "block.wallet"],
            preferences: { show_default_blocks: true },
          },
        },
      });
      rzp.on("payment.failed", function (response: any) {
        setStep("form"); setLoading(false);
        const desc: string = response.error?.description || "Unknown error";
        setError(`Payment failed: ${desc}`);
      });
      rzp.open();
    } catch (e: any) { setStep("form"); setError(String(e)); } finally { setLoading(false); }
  };

  if (!mounted) {
    return (
      <div className="space-y-6 max-w-2xl mx-auto">
        <div className="rz-card p-10 text-center">
          <Loader2 size={18} className="mx-auto animate-spin text-slate-400" />
          <div className="text-sm text-slate-500 mt-3">Loading Checkout…</div>
        </div>
      </div>
    );
  }

  const razorpayLoaded = typeof window !== "undefined" && !!window.Razorpay;
  const steps: Array<{ key: typeof step; label: string }> = [
    { key: "form", label: "Pay" }, { key: "paying", label: "Checkout" }, { key: "waiting", label: "Confirming" }, { key: "done", label: "Done" }
  ];
  const stepIdx = steps.findIndex((s) => s.key === step);

  return (
    <div className="space-y-6 max-w-[640px] mx-auto">
      <div>
        <h1 className="rz-page-title flex items-center gap-2"><CreditCard size={20} className="text-[#0B5CFF]" /> Checkout</h1>
        <p className="rz-page-desc mt-1">Complete a payment to trigger coordination.</p>
      </div>

      {/* Stepper — Razorpay style */}
      <div className="rz-card px-5 py-4">
        <div className="flex items-center gap-2">
          {steps.map((s, i) => {
            const active = i === stepIdx;
            const done = i < stepIdx;
            return (
              <div key={s.key} className="flex items-center gap-2 flex-1">
                <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shrink-0 border-2 ${done ? "bg-emerald-600 border-emerald-600 text-white" : active ? "bg-[#0B5CFF] border-[#0B5CFF] text-white shadow" : "bg-white border-[#EAECF0] text-slate-400"}`}>
                  {done ? <CheckCircle2 size={14} /> : i + 1}
                </div>
                <span className={`text-xs font-semibold hidden sm:block ${active ? "text-[#0B1020]" : done ? "text-emerald-700" : "text-slate-400"}`}>{s.label}</span>
                {i < steps.length - 1 && <div className={`flex-1 h-0.5 mx-2 rounded-full ${i < stepIdx ? "bg-emerald-500" : "bg-[#EAECF0]"}`} />}
              </div>
            );
          })}
        </div>
      </div>

      {error && <div className="rz-card px-4 py-3 text-sm bg-red-50 border-red-200 text-red-700 flex gap-2"><XCircle size={16} className="shrink-0 mt-0.5" />{error}</div>}

      {step === "form" && (
        <div className="rz-card p-6 space-y-4">
          <div className="flex items-center gap-2">
            <span className="w-7 h-7 rounded-lg bg-[#0B5CFF] text-white flex items-center justify-center"><CreditCard size={14} /></span>
            <h2 className="rz-section-title">Create Payment</h2>
            <span className="ml-auto rz-pill bg-slate-50 border text-slate-500">INR</span>
          </div>
          <div className="space-y-3">
            <label>
              <span className="rz-label">Customer</span>
              <select value={selectedCustomer} onChange={(e) => setSelectedCustomer(e.target.value)} className="rz-select mt-1.5 w-full">
                {customers.map((c) => <option key={c.id} value={c.id}>{c.id} — {c.name} ({c.archetype})</option>)}
              </select>
            </label>
            <label>
              <span className="rz-label">Amount (₹)</span>
              <input type="number" value={amount} onChange={(e) => setAmount(Number(e.target.value))} min={1} className="rz-input mt-1.5" />
            </label>
          </div>
          <button onClick={handlePayment} disabled={loading || !selectedCustomer || !razorpayLoaded} className="w-full rz-btn-primary py-3 text-[14px]">
            {!razorpayLoaded ? <><Loader2 size={14} className="animate-spin" /> Loading Razorpay…</> : `Pay ₹${amount} →`}
          </button>
        </div>
      )}

      {(step === "paying" || step === "waiting") && (
        <div className="rz-card p-8 text-center space-y-4">
          <div className="w-12 h-12 rounded-xl bg-[#F2F4F7] border flex items-center justify-center mx-auto">
            {step === "paying" ? <CreditCard size={18} className="text-[#0B5CFF]" /> : <Loader2 size={18} className="animate-spin text-[#0B5CFF]" />}
          </div>
          <div className="text-[16px] font-semibold">{step === "paying" ? "Complete payment in Razorpay" : "Confirming payment…"}</div>
          <div className="text-sm text-slate-500">{statusMessage || "Processing…"}</div>
          {orderResult && <div className="rz-mono bg-[#F9FAFB] border rounded-xl px-3 py-2 text-slate-500">Order {orderResult.order_id} {orderResult.payment_id ? `• Payment ${orderResult.payment_id}` : ""}</div>}
          <div className="flex items-center justify-center gap-1.5 text-xs text-slate-400"><Clock size={12} /> Confirming payment • up to 30s</div>
        </div>
      )}

      {step === "done" && decision && (
        <div className="space-y-4">
          {/* Payment — always succeeded */}
          <div className="rz-card px-4 py-3 flex items-center gap-2 bg-emerald-50 border-emerald-200">
            <span className="w-7 h-7 rounded-full bg-emerald-600 text-white flex items-center justify-center"><CheckCircle2 size={14} /></span>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold text-emerald-800">Payment captured — funds settled by Razorpay</div>
              <div className="rz-mono text-emerald-700 text-xs mt-0.5 truncate">Order {orderResult?.order_id || "—"} {orderResult?.payment_id ? `• Payment ${orderResult.payment_id}` : ""}</div>
            </div>
            <span className="rz-pill bg-emerald-600 text-white">paid</span>
          </div>

          {decision.verdict === "blocked" ? (
            <div className="rz-card p-5 border-amber-200 bg-amber-50/60">
              <div className="flex gap-3">
                <span className="w-9 h-9 rounded-xl bg-amber-500 text-white flex items-center justify-center shrink-0"><Shield size={16} /></span>
                <div className="flex-1 min-w-0">
                  <div className="font-bold text-[15px] text-amber-900">No follow-up sent — suppressed to protect customer</div>
                  <div className="text-sm text-slate-700 mt-1.5 leading-relaxed">Your payment is safe. RazorSync decided <b>not to trigger an upsell</b> for this payment to avoid churn on a high-value customer. This is not a payment failure.</div>
                  <div className="mt-3 rounded-xl bg-white border p-3 space-y-2">
                    <div className="flex items-center gap-2">
                      <span className="rz-pill bg-amber-100 text-amber-800 border-amber-200">Policy</span>
                      <span className="text-xs text-slate-600">{decision.block_reason}</span>
                    </div>
                    {decision.action && (
                      <div className="flex flex-wrap gap-1.5">
                        <span className="rz-pill bg-white border text-slate-600">{decision.action.agent_type}</span>
                        <span className="rz-pill bg-white border text-slate-600">{decision.action.channel}</span>
                        <span className="rz-mono bg-[#F9FAFB] border px-2 py-1 rounded-full">₹{decision.action.amount_involved}</span>
                      </div>
                    )}
                    <div className="text-xs text-slate-500 leading-relaxed bg-[#F9FAFB] border rounded-lg p-2.5">
                      Why: Expected upsell revenue (≈ ₹{decision.action ? Math.round(decision.action.amount_involved * 0.5 * 0.7) : 4}) was outweighed by churn risk (30% of LTV at risk). For <b>high_value_at_risk</b> (LTV ₹15k) a ₹10 upsell scores ≈ -355. Try with <b>loyal_regular</b> (LTV ₹8k) or amount ≥ ₹{Math.ceil(360 / 0.35)} — same payment flow will then show <span className="rz-pill bg-emerald-100 text-emerald-700 border-emerald-200 text-[11px]">Approved</span> and send the upsell.
                    </div>
                  </div>
                  <div className="flex gap-2 mt-3">
                    <a href="/audit" className="rz-btn-secondary text-xs">View in Audit →</a>
                    <a href="/execution" className="rz-btn-ghost border text-xs">Execution Graph →</a>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="rz-card p-5 border-emerald-200 bg-emerald-50/40">
              <div className="flex gap-3">
                <span className="w-9 h-9 rounded-xl bg-emerald-600 text-white flex items-center justify-center shrink-0"><CheckCircle2 size={16} /></span>
                <div className="flex-1 min-w-0">
                  <div className="font-bold text-[15px] text-emerald-900">Upsell approved — outreach queued</div>
                  <div className="text-sm text-slate-700 mt-1 leading-relaxed">{decision.reasoning}</div>
                  {decision.action && <div className="rz-mono bg-white border rounded-full px-2.5 py-1 w-fit mt-3">Channel {decision.action.channel} • Agent {decision.action.agent_type} • ₹{decision.action.amount_involved}</div>}
                </div>
                <span className="rz-pill bg-emerald-600 text-white">approved</span>
              </div>
            </div>
          )}

          <button onClick={() => { setStep("form"); setOrderResult(null); setDecision(null); setError(null); setStatusMessage(""); }} className="rz-btn-secondary"><ArrowLeft size={14} /> Pay again</button>
        </div>
      )}

    </div>
  );
}
