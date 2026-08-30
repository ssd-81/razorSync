import math
from typing import List, Dict

# v3: Churn cost as fraction of LTV (λ parameter — disclosed in UI as "30% LTV at risk")
CHURN_COST_LTV_FRACTION = 0.30


def compute_metrics(customers, decisions, actions):
    """
    customers: list of dicts (generated)
    decisions: list of CoordinationDecision-like dicts with verdict, actual outcome
    actions: list of action dicts
    """
    total_contacts = sum(1 for d in decisions if d["verdict"] in ("approved", "throttled"))
    total_blocked = sum(1 for d in decisions if d["verdict"] == "blocked")
    total_revenue = sum(float(d.get("actual_revenue") or 0) for d in decisions)
    total_conversions = sum(1 for d in decisions if d.get("actual_outcome") == "converted")
    churned = sum(1 for c in customers if c.get("churned"))
    num_customers = len(customers)
    avg_contacts = total_contacts / num_customers if num_customers else 0
    churn_rate = churned / num_customers if num_customers else 0
    # discount waste: discounts on non-converting contacts
    discount_waste = sum(float(a.get("discount_offered") or 0) for a, d in zip(actions, decisions) if d.get("actual_outcome") != "converted" and d["verdict"] in ("approved", "throttled"))
    revenue_per_contact = total_revenue / total_contacts if total_contacts else 0
    # false positive rate: blocked actions that would have converted (we simulate would_convert flag)
    would_convert_blocked = sum(1 for d in decisions if d["verdict"] == "blocked" and d.get("would_have_converted"))
    false_positive = would_convert_blocked / total_blocked if total_blocked else 0

    # v3: Net value — the full P&L story (econ01)
    # net_value = Σ(V-d)*converted - Σd*¬converted - Σ LTV*λ*churned
    churn_cost = 0.0
    for c in customers:
        if c.get("churned"):
            ltv = float(c.get("lifetime_value", 0))
            churn_cost += ltv * CHURN_COST_LTV_FRACTION

    net_value = total_revenue - discount_waste - churn_cost
    revenue_per_1000 = (total_revenue / total_contacts * 1000) if total_contacts else 0

    return {
        "total_revenue": round(total_revenue, 2),
        "total_contacts": total_contacts,
        "total_conversions": total_conversions,
        "avg_contacts_per_customer": round(avg_contacts, 3),
        "churn_rate": round(churn_rate, 4),
        "discount_waste": round(discount_waste, 2),
        "revenue_per_contact": round(revenue_per_contact, 2),
        "false_positive_rate": round(false_positive, 4),
        "total_blocked": total_blocked,
        # v3 net value metrics
        "net_value": round(net_value, 2),
        "churn_cost": round(churn_cost, 2),
        "revenue_per_1000": round(revenue_per_1000, 2),
    }


def welch_t_test(a: List[float], b: List[float]):
    """
    Welch's t-test for two samples with unequal variances.
    Returns t_stat, p_value approx via normal approximation or t-dist.
    If scipy available, use it; else approximate.
    """
    try:
        from scipy import stats
        t_stat, p_val = stats.ttest_ind(a, b, equal_var=False)
        return float(t_stat), float(p_val)
    except Exception:
        # simple approximation
        import math
        n1, n2 = len(a), len(b)
        if n1 < 2 or n2 < 2:
            return 0.0, 1.0
        m1 = sum(a) / n1
        m2 = sum(b) / n2
        v1 = sum((x - m1) ** 2 for x in a) / (n1 - 1) if n1 > 1 else 0
        v2 = sum((x - m2) ** 2 for x in b) / (n2 - 1) if n2 > 1 else 0
        if v1 == 0 and v2 == 0:
            return 0.0, 1.0
        t = (m1 - m2) / math.sqrt(v1 / n1 + v2 / n2)
        # approx p via normal
        # use erf
        p = 2 * (1 - 0.5 * (1 + math.erf(abs(t) / math.sqrt(2))))
        return float(t), float(p)
