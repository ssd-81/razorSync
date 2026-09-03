import random
from datetime import datetime, timedelta, timezone

# _defaults for fallback if yaml missing
_DEFAULT_AGENT_DEFS = {
    "autopay_retry": {
        "trigger": "payment.failed",
        "delays_h": [0, 24, 72],
        "channels": ["sms", "whatsapp", "email"],
        "discounts": [0, 0, 0],
        "description": "Razorpay Subscriptions / Autopay failed — retry with payment link",
    },
    "payment_link_recovery": {
        "trigger": "payment_link.abandoned",
        "delays_h": [1, 6, 24],
        "channels": ["whatsapp", "email", "sms"],
        "discounts": [0, 0.05, 0.10],
        "description": "Payment Links abandoned — recover with progressive discount",
    },
    "invoice_dunning": {
        "trigger": "invoice.overdue",
        "delays_h": [0, 48],
        "channels": ["email", "whatsapp"],
        "discounts": [0, 0],
        "description": "Invoices overdue — dunning sequence",
    },
    "x_payout_growth": {
        "trigger": "payout.completed",
        "delays_h": [2],
        "channels": ["in_app", "email"],
        "discounts": [0],
        "description": "RazorpayX — post-payout upsell to drive growth",
    },
}
_DEFAULT_WEBHOOK_MAP = {
    "payment.failed": ["autopay_retry", "invoice_dunning"],
    "payment.captured": ["x_payout_growth"],
    "order.paid": ["x_payout_growth", "payment_link_recovery"],
    "payment_link.abandoned": ["payment_link_recovery"],
    "invoice.overdue": ["invoice_dunning"],
    "refund.created": ["autopay_retry"],
}

def _load():
    try:
        from app.agents import load_agents_config
        agents, wmap = load_agents_config()
        if agents and wmap:
            # normalize: ensure each agent has required keys
            norm = {}
            for k, v in agents.items():
                norm[k] = {
                    "trigger": v.get("trigger", _DEFAULT_AGENT_DEFS.get(k, {}).get("trigger", "unknown")),
                    "delays_h": v.get("delays_h", [0]),
                    "channels": v.get("channels", ["whatsapp"]),
                    "discounts": v.get("discounts", [0]),
                    "description": v.get("description", k),
                }
            return norm, wmap
    except Exception:
        pass
    return _DEFAULT_AGENT_DEFS, _DEFAULT_WEBHOOK_MAP

AGENT_DEFS, WEBHOOK_AGENT_MAP = _load()

def generate_actions_for_customer(customer: dict, seed: int, duration_days: int = 7, base_time: datetime = None):
    """
    Generate 1-3 agent actions per customer over duration, deterministically via seed + customer id.
    Each customer gets actions staggered in time.
    """
    rng = random.Random(hash((seed, customer["id"])) % (2**32))
    if base_time is None:
        base_time = datetime.now(timezone.utc)

    num_actions = rng.choices([1, 2, 3], weights=[0.5, 0.3, 0.2])[0]
    agent_types = list(AGENT_DEFS.keys())

    actions = []
    for idx in range(num_actions):
        agent_type = rng.choice(agent_types)
        ade = AGENT_DEFS[agent_type]
        # pick a delay variant
        step = rng.randint(0, len(ade["delays_h"]) - 1)
        delay_h = ade["delays_h"][step]
        channel = ade["channels"][min(step, len(ade["channels"]) - 1)]
        discount_pct = ade["discounts"][min(step, len(ade["discounts"]) - 1)]
        discount_offered = round(customer["amount_involved"] * discount_pct, 2) if discount_pct else 0
        # stagger within duration: random hour offset + delay_h
        hour_offset = rng.randint(0, duration_days * 24 - 1)
        # spread actions
        proposed_at = base_time + timedelta(hours=hour_offset + delay_h + idx * 3)
        # agent priority & confidence based on risk/amount
        priority = rng.randint(3, 9)
        if customer["archetype"] == "high_value_at_risk":
            priority = min(10, priority + 1)
        confidence = round(rng.uniform(0.4, 0.9), 2)

        actions.append({
            "agent_id": f"{agent_type}_{seed}_{idx}",
            "agent_type": agent_type,
            "customer_id": customer["id"],
            "merchant_id": customer["merchant_id"],
            "action_type": f"{agent_type}_outreach_{step}",
            "channel": channel,
            "priority": priority,
            "message_template": f"Hi {customer['name']}, we have an update regarding your {agent_type}",
            "discount_offered": discount_offered,
            "amount_involved": customer["amount_involved"],
            "proposed_at": proposed_at,
            "proposed_delay_seconds": int(delay_h * 3600),
            "confidence": confidence,
            "reasoning": f"Simulated {agent_type} trigger {ade['trigger']}",
        })
    # sort by proposed_at
    actions.sort(key=lambda x: x["proposed_at"])
    return actions
