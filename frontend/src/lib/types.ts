export type Verdict = "approved" | "blocked" | "throttled" | "rerouted" | "deferred";
export type AgentType = "subscription_retry" | "cart_recovery" | "upsell" | "dunning";
export type ChannelType = "email" | "whatsapp" | "sms" | "push" | "in_app";
export type RuleType = "frequency_cap" | "budget_limit" | "cooldown" | "channel_priority" | "escalation_ceiling" | "time_window";

export interface Customer {
  id: string;
  name: string;
  city: string;
  archetype: string;
  risk_score: number;
  engagement_score: number;
  total_contacts_received: number;
  current_discount_exposure: number;
  churned: boolean;
  last_contact_at: string | null;
}

export interface BusinessRule {
  id: string;
  merchant_id: string;
  name: string;
  description: string | null;
  rule_type: RuleType;
  rule_config: Record<string, unknown>;
  priority: number;
  is_active: boolean;
  applies_to_agents: string[];
  applies_to_channels: string[];
}

export interface AuditEntry {
  id: string;
  timestamp: string;
  customer_id: string;
  verdict: Verdict | null;
  block_reason: string | null;
  agent_type: string | null;
  channel: string | null;
  amount_involved: number | null;
}

export interface SimulationResult {
  num_customers: number;
  seeds: number[];
  per_seed: {
    seed: number;
    uncoordinated: Record<string, number>;
    coordinated: Record<string, number>;
  }[];
  aggregate: {
    revenue: { uncoordinated_mean: number; coordinated_mean: number };
    contacts: { uncoordinated_mean: number; coordinated_mean: number };
    churn_rate: { uncoordinated_mean: number; coordinated_mean: number };
    revenue_per_contact: { uncoordinated_mean: number; coordinated_mean: number };
    discount_waste: { uncoordinated_mean: number; coordinated_mean: number };
  };
  significance: { t_stat: number; p_value: number };
}
