import uuid
import json
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.action import AgentAction
from app.models.decision import CoordinationDecision
from app.models.audit import AuditEntry
from app.models.customer import CustomerContext
from app.engine.rules import RulesEngine
from app.engine.collisions import CollisionDetector
from app.engine.priority import PriorityRanker
from app.engine.context import ContextManager

logger = logging.getLogger(__name__)


class CoordinationEngine:
    def __init__(self, db: Session):
        self.db = db
        self.rules_engine = RulesEngine(db)
        self.collision_detector = CollisionDetector(db)
        self.priority_ranker = PriorityRanker()
        self.context_manager = ContextManager(db)

    def process_action(self, action: AgentAction) -> CoordinationDecision:
        # 1. VALIDATE
        customer = self.context_manager.load(action.customer_id)
        if not customer:
            return self._block(action, "Customer not found", [], customer_id=action.customer_id)

        # 2. CHECK HARD GUARDRAILS FIRST (v3-10: financial_ceiling, state_conflict → SUSPEND)
        # Hard guardrails fire before soft rules — high-value/risk actions get suspended
        # before they even hit frequency/budget checks
        from app.api.hitl import check_hard_guardrails, suspend_action
        guardrail_info = check_hard_guardrails(action, customer, self.db)
        if guardrail_info:
            suspension = suspend_action(action, customer, guardrail_info, self.db)
            decision = self._block(
                action,
                f"SUSPENDED: {guardrail_info['reason']}",
                [guardrail_info["guardrail"]],
                customer_id=customer.id,
                reasoning=f"Hard guardrail {guardrail_info['guardrail']} triggered — HITL ticket {suspension['ticket_id']}",
            )
            decision.block_reason = f"SUSPENDED → ticket {suspension['ticket_id']}: {guardrail_info['reason']}"
            self.db.add(decision)
            self.db.commit()
            self._audit(action, decision, customer, [guardrail_info["guardrail"]])
            return decision

        # 3. EVALUATE SOFT RULES (windowed, IST-aware)
        rules_result = self.rules_engine.evaluate(action, customer, proposed_at=action.proposed_at)
        if rules_result.verdict == "blocked":
            decision = self._block(action, rules_result.block_reason, rules_result.rules_triggered, customer_id=customer.id, reasoning=rules_result.reasoning)
            self._audit(action, decision, customer, rules_result.rules_triggered)
            return decision

        # 4. CHECK COLLISIONS
        collisions = self.collision_detector.check(action, customer)
        if collisions.has_duplicates:
            decision = self._block(action, collisions.reason, collisions.rules_triggered, customer_id=customer.id)
            self._audit(action, decision, customer, collisions.rules_triggered)
            return decision
        if collisions.has_conflicts:
            # treat as deferred/throttled? For v1 block with conflict reason
            decision = self._block(action, collisions.reason, collisions.rules_triggered, customer_id=customer.id)
            self._audit(action, decision, customer, collisions.rules_triggered)
            return decision

        # 5. PRIORITY RANK
        score = self.priority_ranker.score(action, customer)

        # 6. DECIDE
        decision = self._approve(action, customer, score, rules_result.rules_triggered)

        # 7. UPDATE CONTEXT
        self.context_manager.update_after_decision(customer, action, decision)

        # 8. AUDIT
        self._audit(action, decision, customer, rules_result.rules_triggered)

        self.db.commit()
        return decision

    def _block(self, action: AgentAction, reason: str, triggered: list, customer_id: str = None, reasoning: str = None) -> CoordinationDecision:
        dec = CoordinationDecision(
            id=f"dec_{uuid.uuid4().hex[:12]}",
            action_id=action.id,
            customer_id=customer_id or action.customer_id,
            verdict="blocked",
            block_reason=reason,
            rules_applied=json.dumps(triggered),
            reasoning=reasoning or reason,
            confidence=float(action.confidence or 0.5),
        )
        self.db.add(dec)
        self.db.flush()
        logger.info("Blocked action %s for customer %s: %s", action.id, action.customer_id, reason)
        # we commit outside? For blocked we also commit to persist
        self.db.commit()
        return dec

    def _approve(self, action: AgentAction, customer: CustomerContext, score: float, triggered: list) -> CoordinationDecision:
        # estimated revenue: amount * conversion probability * confidence
        conv = float(customer.conversion_probability or 0.3)
        conf = float(action.confidence or 0.5)
        amt = float(action.amount_involved or 0)
        est = round(amt * conv * conf, 2)
        dec = CoordinationDecision(
            id=f"dec_{uuid.uuid4().hex[:12]}",
            action_id=action.id,
            customer_id=customer.id,
            verdict="approved",
            approved_channel=action.channel,
            approved_delay_seconds=action.proposed_delay_seconds,
            approved_discount=float(action.discount_offered or 0),
            rules_applied=json.dumps(triggered),
            reasoning=f"Approved with score {score}, est revenue ₹{est}",
            estimated_revenue_impact=est,
            confidence=conf,
        )
        self.db.add(dec)
        self.db.flush()
        logger.info("Approved action %s for customer %s score %s", action.id, customer.id, score)
        return dec

    def _audit(self, action: AgentAction, decision: CoordinationDecision, customer: CustomerContext, rules_triggered: list):
        # active agent count: count distinct agent_type for this customer last 24h? simple: count recent actions
        try:
            snapshot = json.dumps({
                "id": customer.id,
                "risk_score": customer.risk_score,
                "engagement_score": customer.engagement_score,
                "total_contacts_received": customer.total_contacts_received,
                "current_discount_exposure": customer.current_discount_exposure,
            })
        except Exception:
            snapshot = "{}"
        entry = AuditEntry(
            id=f"aud_{uuid.uuid4().hex[:12]}",
            customer_id=customer.id,
            merchant_id=action.merchant_id or customer.merchant_id,
            action_id=action.id,
            decision_id=decision.id,
            customer_snapshot=snapshot,
            active_agent_count=1,
            rules_evaluated=json.dumps(rules_triggered),
            actual_outcome=None,
            actual_revenue=None,
        )
        self.db.add(entry)
        self.db.flush()
        # commit handled by caller for approved; for blocked we already committed. Ensure audit persisted
        if decision.verdict == "blocked":
            self.db.commit()
