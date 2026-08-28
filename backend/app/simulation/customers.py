import random
import uuid
from datetime import datetime, timezone, timedelta
from typing import List

ARCHETYPES = {
    "loyal_regular": {"pct": 0.20, "response_prob": 0.7, "conversion_prob": 0.6, "churn_threshold": 8, "discount_sensitivity": 0.3, "ltv": 8000, "risk": 0.2, "engagement": 0.8},
    "price_sensitive": {"pct": 0.30, "response_prob": 0.5, "conversion_prob": 0.4, "churn_threshold": 3, "discount_sensitivity": 0.9, "ltv": 4000, "risk": 0.5, "engagement": 0.5},
    "low_engagement": {"pct": 0.25, "response_prob": 0.15, "conversion_prob": 0.2, "churn_threshold": 2, "discount_sensitivity": 0.4, "ltv": 2000, "risk": 0.7, "engagement": 0.2},
    "high_value_at_risk": {"pct": 0.15, "response_prob": 0.4, "conversion_prob": 0.5, "churn_threshold": 2, "discount_sensitivity": 0.6, "ltv": 15000, "risk": 0.8, "engagement": 0.4},
    "new_customer": {"pct": 0.10, "response_prob": 0.3, "conversion_prob": 0.3, "churn_threshold": 3, "discount_sensitivity": 0.7, "ltv": 3000, "risk": 0.4, "engagement": 0.6},
}

CITIES = ["Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Chennai", "Pune", "Kolkata", "Jaipur"]

def generate_customers(num: int, seed: int, merchant_id: str = "merchant_default"):
    random.seed(seed)
    archetype_list = []
    for arch, cfg in ARCHETYPES.items():
        count = int(num * cfg["pct"])
        archetype_list.extend([arch] * count)
    # fill remainder due to rounding
    while len(archetype_list) < num:
        archetype_list.append(random.choice(list(ARCHETYPES.keys())))
    random.shuffle(archetype_list)

    customers = []
    for i, arch in enumerate(archetype_list[:num]):
        cfg = ARCHETYPES[arch]
        # slight jitter
        jitter = lambda x: max(0, min(1, x + random.uniform(-0.05, 0.05)))
        cid = f"cust_{seed}_{i:04d}"
        customers.append({
            "id": cid,
            "merchant_id": merchant_id,
            "name": f"Customer {i+1}",
            "city": random.choice(CITIES),
            "email": f"user{i}_{seed}@example.com",
            "phone": f"90000{i:05d}",
            "archetype": arch,
            "response_probability": jitter(cfg["response_prob"]),
            "conversion_probability": jitter(cfg["conversion_prob"]),
            "churn_threshold": cfg["churn_threshold"],
            "discount_sensitivity": jitter(cfg["discount_sensitivity"]),
            "lifetime_value": cfg["ltv"],
            "risk_score": jitter(cfg["risk"]),
            "engagement_score": jitter(cfg["engagement"]),
            "outstanding_payments": random.choice([0, 0, 499, 999, 1499]),
            "amount_involved": random.choice([499, 999, 1499, 1999, 2999]),
        })
    return customers
