"""v3 Dispatcher — evaluates all eligible agents for an event, picks winner by policy score.

DECISION V3-08: Dispatcher scores all candidates, picks winner.
DECISION V3-15: Policy then Guardrail — Policy picks best for growth, Guardrail vetoes unsafe.

Policy formula:
  score = est_revenue(V * p_conv * confidence)
        - churn_risk(remaining_contacts) * LTV * CHURN_COST_FRACTION
        - discount_cost(discount * discount_sensitivity)
        - channel_cost (penalty for mismatched channels)

Deterministic in Phase A (no LLM). LLM proposals will replace static
AGENT_DEFS proposals in Phase B.
"""
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.models.customer import CustomerContext
from app.simulation.agents import AGENT_DEFS

logger = logging.getLogger(__name__)

# v3: Policy weights (from V3-04, V3-08)
CHURN_COST_FRACTION = 0.30  # λ — 30% of LTV at risk per churn
CHANNEL_FIT_BONUS = 0.05  # bonus for high-value customers on whatsapp
COORDINATION_BOOST = 0.12  # v3-04: timing relevance boost (was 0.08)
CHANNEL_COST = {
    "whatsapp": 0.30,
    "sms": 0.15,
    "email": 0.05,
    "push": 0.10,
    "in_app": 0.02,
}


class DispatcherResult:
    """Result of dispatcher evaluating candidates."""

    def __init__(self):
        self.candidates: List[Dict[str, Any]] = []
        self.winner: Optional[Dict[str, Any]] = None
        self.all_blocked: bool = False
        self.block_reason: Optional[str] = None


def generate_candidate_proposals(
    event: str,
    customer: CustomerContext,
    merchant_id: str,
    amount: float = 0.0,
) -> List[Dict[str, Any]]:
    """Generate action proposals for all agents eligible for this event.

    Phase A: deterministic from AGENT_DEFS.
    Phase B: calls LLM for each candidate, falls back to AGENT_DEFS on failure.
    """
    from app.simulation.agents import WEBHOOK_AGENT_MAP
    try:
        from app.llm.client import call_llm
        from app.config import settings
        LLM_ENABLED = settings.llm_enabled
    except Exception:
        from app.engine.llm_client import call_llm, LLM_ENABLED  # fallback legacy

    eligible_agent_types = WEBHOOK_AGENT_MAP.get(event, [])
    if not eligible_agent_types:
        return []

    # Build customer context for LLM
    cust_ctx = {
        "lifetime_value": customer.lifetime_value,
        "risk_score": customer.risk_score,
        "total_contacts_received": customer.total_contacts_received,
        "churn_threshold": customer.churn_threshold,
        "archetype": customer.archetype,
    }

    proposals = []
    for agent_type in eligible_agent_types:
        ade = AGENT_DEFS.get(agent_type, {})
        channels = ade.get("channels", ["whatsapp"])
        delays = ade.get("delays_h", [0])
        discounts_pct = ade.get("discounts", [0])

        # Phase B: try LLM first, fall back to deterministic
        llm_result = None
        if LLM_ENABLED:
            llm_result = call_llm(agent_type, merchant_id, event, customer.id, amount, cust_ctx)

        if llm_result:
            # LLM proposed — use its output, validated against allowed values
            channel = llm_result.get("channel", channels[0])
            if channel not in channels:
                channel = channels[0]  # fallback to allowed channel
            discount = float(llm_result.get("discount_offered", 0))
            confidence = float(llm_result.get("confidence", 0.7))
            reasoning = llm_result.get("reasoning", ade.get("description", agent_type))
            proposals.append({
                "agent_type": agent_type,
                "channel": channel,
                "delay_h": delays[0] if delays else 0,
                "discount_offered": discount,
                "discount_pct": discount / amount if amount else 0,
                "amount": amount,
                "confidence": confidence,
                "reasoning": f"LLM: {reasoning}",
                "source": "llm",
                "llm_latency_s": llm_result.get("llm_latency_s"),
            })
        else:
            # Deterministic fallback (Phase A default)
            channel = channels[0] if channels else "whatsapp"
            delay_h = delays[0] if delays else 0
            discount_pct = discounts_pct[0] if discounts_pct else 0
            discount = round(amount * discount_pct, 2) if discount_pct and amount else 0
            proposals.append({
                "agent_type": agent_type,
                "channel": channel,
                "delay_h": delay_h,
                "discount_offered": discount,
                "discount_pct": discount_pct,
                "amount": amount,
                "confidence": 0.7,
                "reasoning": f"{ade.get('description', agent_type)} — {event}",
                "source": "deterministic",
            })

    return proposals


def score_proposal(
    proposal: Dict[str, Any],
    customer: CustomerContext,
) -> Dict[str, Any]:
    """Score a single proposal using the v3 policy formula.

    Returns proposal dict with added 'score' and 'score_breakdown'.
    """
    amount = float(proposal.get("amount", 0))
    discount = float(proposal.get("discount_offered", 0))
    confidence = float(proposal.get("confidence", 0.7))
    channel = proposal.get("channel", "whatsapp")

    # Customer metrics
    ltv = float(customer.lifetime_value or 0)
    conv_prob = float(customer.conversion_probability or 0.3)
    discount_sensitivity = float(customer.discount_sensitivity or 0.5)
    contacts_received = int(customer.total_contacts_received or 0)
    churn_threshold = int(customer.churn_threshold or 5)

    # 1. Expected revenue: V * p_conv * confidence
    est_revenue = amount * conv_prob * confidence

    # 2. Churn risk: marginal risk from THIS action
    # Each additional contact increases churn probability by a small amount
    # Risk = (fatigue_rate) × LTV × λ — only the incremental risk from this contact
    fatigue_rate = 0.08 if not channel == 'whatsapp' else 0.05  # whatsapp is less intrusive
    churn_risk = fatigue_rate * ltv * CHURN_COST_FRACTION

    # 3. Discount cost: discount × sensitivity (how much value you give away)
    discount_cost = discount * discount_sensitivity

    # 4. Channel cost: cheaper channels = better for merchant
    channel_cost = CHANNEL_COST.get(channel, 0.10)

    # 5. Channel fit bonus: whatsapp for high-value customers
    channel_fit = 0.0
    if channel == "whatsapp" and ltv > 10000:
        channel_fit = CHANNEL_FIT_BONUS

    # Final score
    score = est_revenue - churn_risk - discount_cost - channel_cost + channel_fit

    return {
        **proposal,
        "score": round(score, 4),
        "score_breakdown": {
            "est_revenue": round(est_revenue, 4),
            "churn_risk": round(churn_risk, 4),
            "discount_cost": round(discount_cost, 4),
            "channel_cost": round(channel_cost, 4),
            "channel_fit": round(channel_fit, 4),
        },
    }


def dispatch(
    event: str,
    customer: CustomerContext,
    merchant_id: str,
    amount: float = 0.0,
    db: Optional[Session] = None,
) -> DispatcherResult:
    """Main dispatcher: generate proposals, score all, pick winner.

    Returns DispatcherResult with scored candidates and winner.
    """
    result = DispatcherResult()

    proposals = generate_candidate_proposals(event, customer, merchant_id, amount)
    if not proposals:
        result.all_blocked = True
        result.block_reason = f"No eligible agents for event: {event}"
        return result

    # Score each proposal
    scored = [score_proposal(p, customer) for p in proposals]
    scored.sort(key=lambda x: x["score"], reverse=True)
    result.candidates = scored

    # Winner = highest score (if positive)
    winner = scored[0]
    if winner["score"] <= 0:
        result.all_blocked = True
        result.block_reason = f"All candidates scored ≤0 (best: {winner['agent_type']} = {winner['score']:.4f})"
        return result

    result.winner = winner
    logger.info(
        "Dispatcher: event=%s customer=%s winner=%s score=%.4f candidates=%s",
        event, customer.id, winner["agent_type"], winner["score"],
        [f"{c['agent_type']}={c['score']:.4f}" for c in scored],
    )
    return result
