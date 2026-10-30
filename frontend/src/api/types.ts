export type Paginated<T> = { count: number; next: string | null; previous: string | null; results: T[] };

export type Membership = { organization: { id: number; name: string; slug: string }; role: "PROPERTY_MANAGER" | "LEASING_AGENT" };
export type Me = { id: number; email: string; first_name: string; last_name: string; memberships: Membership[] };

export type ProspectStatus =
  | "NEW" | "CONTACTED" | "TOUR_SCHEDULED" | "TOURED" | "APPLIED" | "APPROVED" | "LEASED" | "LOST";

export type TourSummary = { id: number; start: string; end: string; status: string; unit: number; unit_number: string };

export type ProspectRow = {
  id: number;
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  source: string;
  status: ProspectStatus;
  assigned_agent: { id: number; first_name: string; last_name: string; email: string } | null;
  interested_property: { id: number; name: string } | null;
  desired_move_in: string | null;
  beds_min: number | null;
  budget_max: string | null;
  has_pets: boolean;
  last_contacted_at: string | null;
  created_at: string;
  next_tour: TourSummary | null;
};

export type ProspectDetail = ProspectRow & {
  notes: string;
  tours: TourSummary[];
  conversations: { id: number; channel: string; last_message_at: string | null; needs_handoff: boolean }[];
  applications: { id: number; status: string; unit: number; submitted_at: string | null }[];
};

export type InboxRow = {
  id: number;
  channel: "EMAIL" | "SMS" | "CHAT";
  subject: string;
  last_message_at: string | null;
  is_unread: boolean;
  needs_handoff: boolean;
  open_handoffs: number;
  prospect: { id: number; name: string; email: string; phone: string; status: ProspectStatus; assigned_agent: number | null };
  last_message: { body: string; direction: "IN" | "OUT"; is_assistant: boolean } | null;
};

export type Message = {
  id: number;
  conversation: number;
  direction: "IN" | "OUT";
  channel: string;
  body: string;
  sender: number | null;
  is_assistant: boolean;
  sent_at: string;
};

export type Suggestion = { suggestion: string; handoff_reason: string | null; tools_called: string[] };

export type Tour = {
  id: number;
  prospect: number;
  unit: number;
  agent: number | null;
  start: string;
  end: string;
  status: "SCHEDULED" | "COMPLETED" | "CANCELED" | "NO_SHOW";
  booked_by: "AGENT" | "ASSISTANT" | "PROSPECT";
  notes: string;
  prospect_name: string;
  unit_number: string;
  property_id: number;
  property_name: string;
  timezone: string;
  agent_name: string | null;
};

export type Property = { id: number; name: string; city: string; state: string; timezone: string };

export type Unit = {
  id: number;
  property: number;
  property_name: string;
  number: string;
  floor: number;
  beds: number;
  baths: string;
  sqft: number | null;
  rent: string;
  available_from: string | null;
  status: "AVAILABLE" | "NOTICE" | "OCCUPIED" | "OFFLINE";
};

export type ChatReply = { session: string; reply: string; handoff: boolean; tour_id: number | null };
