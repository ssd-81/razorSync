from app.models.action import AgentAction
from app.models.customer import CustomerContext

AGENT_WEIGHTS = {
    "subscription_retry": 1.2,
    "dunning": 1.15,
    "cart_recovery": 1.0,
    "upsell": 0.8,
}

class PriorityRanker:
    def score(self, action: AgentAction, customer: CustomerContext) -> float:
        base = float(action.priority or 5)  # 1-10
        weight = AGENT_WEIGHTS.get(action.agent_type, 1.0)
        confidence = float(action.confidence or 0.5)
        # risk and engagement adjust
        risk = float(customer.risk_score or 0.5)
        engagement = float(customer.engagement_score or 0.5)
        # high risk + high amount gets boost
        amount_factor = min(float(action.amount_involved or 0) / 1000.0, 1.0) * 0.5
        # score formula
        score = base * weight * (0.5 + confidence) * (0.8 + risk * 0.4) * (0.7 + engagement * 0.6) + amount_factor
        return round(score, 3)
