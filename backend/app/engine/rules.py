import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.rule import BusinessRule
from app.models.action import AgentAction
from app.models.decision import CoordinationDecision
from app.models.audit import AuditEntry
from app.models.customer import CustomerContext

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

# Valid rule types
VALID_RULE_TYPES = {"frequency_cap", "budget_limit", "cooldown", "channel_priority", "escalation_ceiling", "time_window"}


class RuleEvaluationResult:
    def __init__(self, verdict: str = "approved", block_reason: Optional[str] = None, rules_triggered: Optional[List[str]] = None, reasoning: str = ""):
        self.verdict = verdict  # approved | blocked
        self.block_reason = block_reason
        self.rules_triggered = rules_triggered or []
        self.reasoning = reasoning


class RulesEngine:
    def __init__(self, db: Session):
        self.db = db

    def evaluate(self, action: AgentAction, customer: CustomerContext, proposed_at: Optional[datetime] = None) -> RuleEvaluationResult:
        """
        Windowed, IST-aware evaluation.
        proposed_at defaults to action.proposed_at or now.
        All thresholds sourced from BusinessRule.rule_config (single source).
        """
        if proposed_at is None:
            proposed_at = action.proposed_at or datetime.now(timezone.utc)
        # ensure timezone aware UTC
        if proposed_at.tzinfo is None:
            proposed_at = proposed_at.replace(tzinfo=timezone.utc)

        merchant_id = action.merchant_id or customer.merchant_id
        rules: List[BusinessRule] = (
            self.db.query(BusinessRule)
            .filter(BusinessRule.merchant_id == merchant_id, BusinessRule.is_active == True)  # noqa: E712
            .order_by(BusinessRule.priority.desc())
            .all()
        )

        triggered: List[str] = []
        for rule in rules:
            # scope filtering
            try:
                applies_agents = json.loads(rule.applies_to_agents) if rule.applies_to_agents else []
                applies_channels = json.loads(rule.applies_to_channels) if rule.applies_to_channels else []
            except Exception:
                applies_agents, applies_channels = [], []

            if applies_agents and action.agent_type not in applies_agents:
                continue
            if applies_channels and action.channel not in applies_channels:
                continue

            try:
                config = json.loads(rule.rule_config) if isinstance(rule.rule_config, str) else rule.rule_config
            except Exception as e:
                logger.warning("Invalid rule_config for rule %s: %s", rule.id, e)
                continue

            verdict_block, reason = self._evaluate_single(rule.rule_type, config, action, customer, proposed_at)
            if verdict_block:
                triggered.append(rule.id)
                return RuleEvaluationResult(
                    verdict="blocked",
                    block_reason=reason,
                    rules_triggered=triggered,
                    reasoning=f"Blocked by {rule.name} ({rule.rule_type}): {reason}",
                )

        return RuleEvaluationResult(verdict="approved", rules_triggered=triggered, reasoning="All rules passed")

    def _evaluate_single(self, rule_type: str, config: dict, action: AgentAction, customer: CustomerContext, proposed_at: datetime) -> Tuple[bool, str]:
        now = proposed_at
        # Source-aware window: simulation (Jan 2026) should count simulation decisions, live counts live/fallback
        is_sim = now.year == 2026 and now.month == 1
        def _source_filter(q):
            if is_sim:
                return q.filter(CoordinationDecision.source == "simulation")
            return q.filter(CoordinationDecision.source.in_(["live", "fallback"]))

        if rule_type == "frequency_cap":
            max_contacts = int(config.get("max_contacts", 2))
            window_hours = float(config.get("window_hours", 24))
            window_start = now - timedelta(hours=window_hours)
            # Windowed count via Python filtering on proposed_at (SQLite tz handling) — source-aware
            q = self.db.query(AgentAction.proposed_at).join(CoordinationDecision, AgentAction.id == CoordinationDecision.action_id).filter(
                    CoordinationDecision.customer_id == customer.id,
                    CoordinationDecision.verdict.in_(["approved", "throttled"]),
                )
            q = _source_filter(q)
            rows = q.all()
            count = 0
            for (prop,) in rows:
                if prop is None:
                    continue
                p = prop if prop.tzinfo else prop.replace(tzinfo=timezone.utc)
                if window_start <= p <= now:
                    count += 1
            # Also include audit entries if decisions table empty for new customers: fallback to counting recent actions via audit?
            if count >= max_contacts:
                return True, f"frequency_cap: {count} contacts in last {window_hours}h >= {max_contacts}"
            return False, ""

        elif rule_type == "cooldown":
            cooldown_hours = float(config.get("cooldown_hours", 4))
            # Windowed cooldown: hours since last_contact_at
            if customer.last_contact_at:
                last = customer.last_contact_at
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                hours_since = (now - last).total_seconds() / 3600
                if hours_since < cooldown_hours:
                    return True, f"cooldown: {hours_since:.1f}h since last contact < {cooldown_hours}h"
            # Also check recent approved decision via proposed_at if last_contact_at not set
            else:
                q2 = self.db.query(AgentAction).join(CoordinationDecision, AgentAction.id == CoordinationDecision.action_id).filter(
                        CoordinationDecision.customer_id == customer.id,
                        CoordinationDecision.verdict.in_(["approved", "throttled"]),
                    )
                q2 = _source_filter(q2)
                recent = q2.order_by(AgentAction.proposed_at.desc()).first()
                if recent and recent.proposed_at:
                    rt = recent.proposed_at
                    if rt.tzinfo is None:
                        rt = rt.replace(tzinfo=timezone.utc)
                    hours_since = (now - rt).total_seconds() / 3600
                    if hours_since < cooldown_hours:
                        return True, f"cooldown: {hours_since:.1f}h since last decision < {cooldown_hours}h"
            return False, ""

        elif rule_type == "time_window":
            start_hour = int(config.get("start_hour", 9))
            end_hour = int(config.get("end_hour", 21))
            # IST check: convert now to Asia/Kolkata
            ist_now = now.astimezone(IST)
            hour = ist_now.hour + ist_now.minute / 60.0
            # handle overnight windows? assume start < end (9-21)
            if not (start_hour <= hour < end_hour):
                return True, f"time_window: IST {ist_now.strftime('%H:%M')} outside {start_hour:02d}:00-{end_hour:02d}:00 IST"
            return False, ""

        elif rule_type == "budget_limit":
            max_discount = float(config.get("max_discount", 200))
            current = float(customer.current_discount_exposure or 0.0)
            offered = float(action.discount_offered or 0.0)
            if current + offered > max_discount:
                return True, f"budget_limit: exposure {current}+{offered}={current+offered} > {max_discount}"
            return False, ""

        elif rule_type == "escalation_ceiling":
            max_esc = int(config.get("max_escalations", 3))
            window_hours = float(config.get("window_hours", 168))  # default 7 days
            window_start = now - timedelta(hours=window_hours)
            q = self.db.query(AgentAction.proposed_at).join(CoordinationDecision, AgentAction.id == CoordinationDecision.action_id).filter(
                    CoordinationDecision.customer_id == customer.id,
                    CoordinationDecision.verdict.in_(["approved", "throttled"]),
                )
            q = _source_filter(q)
            rows = q.all()
            count = 0
            for (prop,) in rows:
                if prop is None:
                    continue
                p = prop if prop.tzinfo else prop.replace(tzinfo=timezone.utc)
                if window_start <= p <= now:
                    count += 1
            if count >= max_esc:
                return True, f"escalation_ceiling: {count} escalations in {window_hours}h >= {max_esc}"
            return False, ""

        elif rule_type == "channel_priority":
            # Not blocking, just ranking hint — never blocks
            return False, ""

        else:
            logger.warning("Unknown rule_type %s", rule_type)
            return False, ""

    def get_rules_snapshot(self, merchant_id: str):
        rules = self.db.query(BusinessRule).filter(BusinessRule.merchant_id == merchant_id).all()
        snap = []
        for r in rules:
            snap.append({
                "id": r.id,
                "rule_type": r.rule_type,
                "rule_config": json.loads(r.rule_config) if isinstance(r.rule_config, str) else r.rule_config,
                "is_active": r.is_active,
                "priority": r.priority,
            })
        return snap
