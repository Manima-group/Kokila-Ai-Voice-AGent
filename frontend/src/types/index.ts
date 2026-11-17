export type Membership = { tenant_id: string; tenant_name: string; role: string; tenant_status: string; permissions: string[] };
export type Me = { id: string; email: string; full_name: string; is_superadmin: boolean; memberships: Membership[] };
export type Page<T> = { items: T[]; total: number; limit: number; offset: number };

export type Agent = {
  id: string;
  name: string;
  description: string | null;
  template: string;
  status: string;
  provider: string;
  provider_agent_id: string | null;
  published_version_id: string | null;
  latest_version: number;
  sync_status: string;
  sync_error: string | null;
  created_at: string;
};

export type AgentConfig = {
  languages: string[];
  voice_id: string;
  greeting: string;
  instructions: string;
  business_rules: string[];
  business_hours: { start: string; end: string; timezone: string; days: number[] };
  allowed_tools: string[];
  escalation: { transfer_number: string | null; notify_emails: string[] };
  outcome_fields: string[];
  max_call_seconds: number;
};

export type Contact = { id: string; phone_e164: string; name: string | null; email: string | null; language: string | null; tags: string[]; source: string; created_at: string };

export type Call = {
  id: string;
  direction: string;
  provider: string;
  status: string;
  analysis_status: string;
  from_number: string | null;
  to_number: string | null;
  agent_id: string | null;
  contact_id: string | null;
  campaign_id: string | null;
  started_at: string | null;
  ended_at: string | null;
  duration_seconds: number;
  outcome: string | null;
  sentiment: string | null;
  handoff_requested: boolean;
  is_mock: boolean;
  created_at: string;
};

export type Campaign = {
  id: string;
  name: string;
  purpose: string;
  agent_id: string;
  from_phone_number_id: string;
  status: string;
  window_start: string;
  window_end: string;
  timezone: string;
  days_of_week: number[];
  max_concurrency: number;
  max_attempts: number;
  retry_delay_minutes: number;
  created_at: string;
};

export type PhoneNumber = {
  id: string;
  e164: string;
  label: string | null;
  provider: string;
  number_type: string;
  inbound_agent_id: string | null;
  outbound_enabled: boolean;
  status: string;
};

export type Lead = {
  id: string;
  contact_id: string;
  status: string;
  score: number;
  source: string;
  assigned_to: string | null;
  last_outcome: string | null;
  notes: string | null;
  next_follow_up_at: string | null;
  contact_name?: string | null;
  contact_phone?: string | null;
  updated_at: string;
};
