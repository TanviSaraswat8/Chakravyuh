const BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? "";

export type EventType =
  | "MSG_RECV" | "MSG_SENT" | "CALL" | "SCREEN_SHARE" | "REMOTE_APP" | "LINK_OPEN" | "APK_INSTALL"
  | "UPI_OPEN" | "PAYEE_NEW" | "FD_BREAK" | "PAY" | "RECV";

export interface SimEvent {
  t: number;
  type: EventType;
  stage: string;
  tactics: string[];
  text: string | null;
  channel: string;
  attrs: Record<string, any>;
  speaker: "them" | "me" | "system";
}

export interface Step {
  p: number;
  level: number;
  escalated: boolean;
  action: string | null;
  next_stage: string | null;
  p_seq: number | null;
  p_msg: number | null;
  r_payee: number | null;
  tactics: string[];
  stage_guess: string | null;
}

export interface ScenarioSummary { key: string; title: string; kind: "scam" | "legit"; blurb: string }

export interface Scenario extends ScenarioSummary {
  language: "en" | "hi" | "hinglish";
  channel: string;
  events: SimEvent[];
  scores: Step[];
  baseline: { alert: boolean }[];
  alerts: Record<string, Alert>;
  family_guess: string | null;
}

export interface Alert {
  id: string | null;
  level: number;
  action: string;
  reason_code: string;
  title: string;
  message: string;
  p: number;
  response?: string | null;
}

export interface ScoreOut {
  session_id: string | null;
  mode: string;
  latest: Step;
  steps: Step[];
  alert: Alert | null;
  family_guess: string | null;
}

export interface ArenaGen {
  generation: number;
  round: number;
  detection_rate: number;
  mean_loss: number;
  missed_examples: { family: string; ops: string[]; extra_tactics: string[]; message: string }[];
  top_genome: Record<string, any>;
}

export interface AdaptResult {
  accepted: boolean;
  round: number;
  gate_before?: number;
  gate_after?: number;
  detection_before: number;
  detection_after: number;
  legit_false_alarm_before: number;
  legit_false_alarm_after: number;
  trained_on: Record<string, number>;
  tested_on: Record<string, number>;
  error?: string;
}

export interface CampaignCard {
  campaign_id: string;
  name: string;
  size: number;
  top_tactics: string[];
  event_sequence: string[];
  languages: Record<string, number>;
  channels: Record<string, number>;
  payee_clusters: string[];
  example_message: string;
  draft_rule: string;
}

export interface Campaign { id: string; name: string; size: number; status: string; card: CampaignCard; created_at: string }

export interface User { id: string; email: string; role: string; status: string; permissions: string[] }

// Signing in sets an HttpOnly cookie that scripts cannot read. The CSRF token comes back in the
// response body and is kept only in this module's memory: nothing is written to browser storage.
let csrfToken: string | null = null;

export class ApiError extends Error {
  constructor(message: string, public status: number, public stepUp = false) { super(message); }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  const unsafe = method !== "GET" && method !== "HEAD";
  const res = await fetch(BASE + path, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(unsafe && csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch { /* not JSON */ }
    if (res.status === 401 && !path.startsWith("/v1/auth/")) detail = "You need to sign in first (Account page)";
    throw new ApiError(detail, res.status, res.headers.get("X-Step-Up-Required") === "true");
  }
  return res.json() as Promise<T>;
}

async function session(path: string, body?: unknown): Promise<User | null> {
  try {
    const r = await req<{ user: User; csrf_token: string }>(path, body === undefined ? undefined
      : { method: "POST", body: JSON.stringify(body) });
    csrfToken = r.csrf_token;
    return r.user;
  } catch (e) {
    if (e instanceof ApiError && e.status === 401 && path === "/v1/auth/me") { csrfToken = null; return null; }
    throw e;
  }
}

export const auth = {
  me: () => session("/v1/auth/me"),
  login: (email: string, password: string) => session("/v1/auth/login", { email, password }),
  register: (email: string, password: string) =>
    req<{ id: string; email: string; role: string }>("/v1/auth/register", { method: "POST", body: JSON.stringify({ email, password }) }),
  logout: async () => { await req("/v1/auth/logout", { method: "POST" }); csrfToken = null; },
  reauth: (password: string) => req<{ valid_seconds: number }>("/v1/auth/reauth", { method: "POST", body: JSON.stringify({ password }) }),
};

export const api = {
  health: () => req<{ status: string; model: { loaded: boolean; mode: string; trained_at?: string } }>("/health"),
  scenarios: () => req<ScenarioSummary[]>("/v1/demo/scenarios"),
  scenario: (key: string) => req<Scenario>(`/v1/demo/scenarios/${key}`),
  score: (body: { language: string; channel: string; events: Partial<SimEvent>[] }) =>
    req<ScoreOut>("/v1/score", { method: "POST", body: JSON.stringify(body) }),
  arena: (generations: number, population: number, fresh: boolean) =>
    req<{ gate: number; round: number; history: ArenaGen[]; defences: AdaptResult[]; error?: string }>("/v1/demo/arena", {
      method: "POST", body: JSON.stringify({ generations, population, per_genome: 2, fresh }),
    }),
  adapt: (epochs = 3) => req<AdaptResult>(`/v1/demo/arena/adapt?epochs=${epochs}`, { method: "POST" }),
  createSession: (language: string, channel: string) =>
    req<{ id: string }>("/v1/sessions", { method: "POST", body: JSON.stringify({ language, channel, source: "live" }) }),
  addEvent: (sid: string, ev: { type: string; t?: number; text?: string; attrs?: Record<string, any>; channel?: string }) =>
    req<ScoreOut>(`/v1/sessions/${sid}/events`, { method: "POST", body: JSON.stringify(ev) }),
  respondAlert: (id: string, response: "proceeded" | "cancelled" | "legit") =>
    req<Alert>(`/v1/alerts/${id}/respond`, { method: "POST", body: JSON.stringify({ response }) }),
  campaigns: () => req<Campaign[]>("/v1/campaigns"),
  refreshCampaigns: () =>
    req<{ created: number; unknown_sessions: number; pool: number; tactic_drift_psi: number; drift_alarm: boolean }>(
      "/v1/campaigns/refresh", { method: "POST" }),
  setCampaign: (id: string, status: string) =>
    req(`/v1/campaigns/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
  meta: () => req<{ model: any; benchmark: any }>("/v1/meta"),
  metrics: () => req<Record<string, any>>("/v1/metrics"),
  signup: (body: { email: string; name: string; org?: string; role: string }) =>
    req<{ id: string; api_key: string; cohort: string }>("/v1/beta/signup", { method: "POST", body: JSON.stringify(body) }),
  feedback: (body: { kind: string; rating?: number; comment?: string; page?: string }, testerKey?: string) =>
    req<{ id: number }>("/v1/beta/feedback", {
      method: "POST", body: JSON.stringify(body), headers: testerKey ? { "X-API-Key": testerKey } : {},
    }),
};

export const pct = (x: number | null | undefined, digits = 0) =>
  x == null ? "–" : `${(x * 100).toFixed(digits)}%`;

export const LEVELS = ["Quiet", "Nudge", "Check-in", "Cooling-off", "Hold"];

export const tacticLabel = (t: string) => t.replace(/_/g, " ");

export const TYPE_LABEL: Record<string, string> = {
  MSG_RECV: "Message received", MSG_SENT: "Reply sent", CALL: "Call", SCREEN_SHARE: "Screen share",
  REMOTE_APP: "Remote-access app", LINK_OPEN: "Link opened", APK_INSTALL: "App sideloaded",
  UPI_OPEN: "UPI app opened", PAYEE_NEW: "New payee", FD_BREAK: "FD broken", PAY: "Payment", RECV: "Money received",
};
