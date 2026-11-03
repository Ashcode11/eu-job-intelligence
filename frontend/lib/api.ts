// Typed client for the FastAPI backend. Requests go to /backend/* (same origin, rewritten by
// Next.js to the API). The API key is kept in this browser's localStorage only.

const KEY_STORAGE = "eujobs.apiKey";
const BASE = "/backend/api/v1";

export function getApiKey(): string | null {
  try {
    return window.localStorage.getItem(KEY_STORAGE);
  } catch {
    return null;
  }
}

export function setApiKey(key: string | null): void {
  try {
    if (key) window.localStorage.setItem(KEY_STORAGE, key);
    else window.localStorage.removeItem(KEY_STORAGE);
  } catch {
    /* storage unavailable: the user re-enters the key next time */
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

function errorMessage(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d))
      return d.map((e) => `${(e.loc ?? []).slice(1).join(".")}: ${e.msg}`).join("; ");
    return JSON.stringify(d);
  }
  return `Request failed (${status})`;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const key = getApiKey();
  if (key) headers.set("X-API-Key", key);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const res = await fetch(`${BASE}${path}`, { ...init, headers, cache: "no-store" });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const body = text ? JSON.parse(text) : undefined;
  if (!res.ok) {
    if (res.status === 401) window.dispatchEvent(new Event("eujobs:unauthorized"));
    throw new ApiError(res.status, errorMessage(body, res.status));
  }
  return body as T;
}

export const json = (data: unknown): RequestInit => ({ body: JSON.stringify(data) });

export async function download(path: string, filename: string): Promise<void> {
  const key = getApiKey();
  const res = await fetch(`${BASE}${path}`, { headers: key ? { "X-API-Key": key } : {} });
  if (!res.ok) throw new ApiError(res.status, `Download failed (${res.status})`);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------- types
export type VisaClass =
  | "explicit_sponsorship"
  | "potential_sponsorship"
  | "eu_authorization_required"
  | "not_mentioned"
  | "not_suitable";

export type AppStatus =
  | "saved"
  | "shortlisted"
  | "prepared"
  | "applied"
  | "interview_scheduled"
  | "rejected"
  | "offer_received"
  | "withdrawn";

export interface JobSummary {
  id: string;
  title: string;
  company_name: string | null;
  country: string | null;
  city: string | null;
  remote_type: string;
  posted_at: string | null;
  status: string;
  url: string;
  source_key: string;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  match_score: number | null;
  visa_classification: VisaClass | null;
  application_status: AppStatus | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Evidence {
  url: string | null;
  quote: string;
  signal: string;
}

export interface JobDetail extends JobSummary {
  apply_url: string | null;
  description: string;
  location_raw: string | null;
  employment_type: string | null;
  seniority: string | null;
  experience_min_years: number | null;
  required_skills: string[];
  salary_raw: string | null;
  discovered_at: string;
  last_seen_at: string;
  company: { id: string; name: string; website: string | null; documented_sponsor: boolean | null } | null;
  match: {
    overall_score: number;
    component_scores: Record<string, number>;
    weights_used: Record<string, number>;
    semantic_similarity: number | null;
    matched_skills: string[];
    missing_skills: string[];
    experience_gaps: string[];
    reasons_for: string[];
    reasons_against: string[];
    recommended: boolean;
    interview_likelihood: "low" | "medium" | "high" | null;
    interview_likelihood_note: string;
    updated_at: string;
  } | null;
  visa: {
    classification: VisaClass;
    mentions_sponsorship: boolean | null;
    relocation_support: boolean | null;
    non_eu_applicants_accepted: boolean | null;
    eu_authorization_required: boolean | null;
    employer_documented_sponsor: boolean | null;
    evidence: Evidence[];
    country_pathways: { name: string; reference_url: string; notes: string; country: string }[];
    confidence: number | null;
    rationale: string | null;
    method: string;
  } | null;
  salary: {
    has_actual_salary: boolean;
    actual_min_eur: number | null;
    actual_max_eur: number | null;
    source_currency: string | null;
    estimated_min_eur: number | null;
    estimated_max_eur: number | null;
    benchmark_median_eur: number | null;
    benchmark_source: string | null;
    est_net_annual_eur: number | null;
    est_living_cost_annual_eur: number | null;
    est_savings_annual_eur: number | null;
    meets_candidate_minimum: boolean | null;
    assumptions: Record<string, unknown>;
  } | null;
}

export interface Skill {
  id: string;
  name: string;
  category: string | null;
  proficiency: number | null;
  years: number | null;
  aliases: string[];
  source: string;
}

export interface Experience {
  id: string;
  organization: string;
  title: string;
  location: string | null;
  start_date: string | null;
  end_date: string | null;
  is_current: boolean;
  description: string | null;
  highlights: string[];
  technologies: string[];
}

export interface Resume {
  id: string;
  version_label: string;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  is_primary: boolean;
  job_id: string | null;
  parsed_at: string | null;
  parse_error: string | null;
  created_at: string;
}

export interface Candidate {
  id: string;
  full_name: string;
  email: string | null;
  phone: string | null;
  current_designation: string | null;
  years_experience: number | null;
  current_organization: string | null;
  previous_organizations: string[];
  summary: string | null;
  current_country: string | null;
  citizenship: string[] | null;
  has_eu_work_authorization: boolean | null;
  eu_work_authorization_details: string | null;
  requires_visa_sponsorship: boolean | null;
  open_to_relocation: boolean | null;
  relocation_notes: string | null;
  notice_period_weeks: number | null;
  target_roles: string[];
  preferred_countries: string[];
  preferred_cities: string[];
  remote_preference: string | null;
  min_salary_eur: number | null;
  target_salary_eur: number | null;
  match_weights: Record<string, number>;
  skills: Skill[];
  experiences: Experience[];
  resumes: Resume[];
  profile_completeness: string[];
}

export interface ResumeAnalysis {
  status: "pending" | "failed" | "parsed";
  error?: string;
  skills?: { name: string; mentions: number; category: string | null }[];
  certifications?: string[];
  years_experience?: number | null;
  suggested_skills?: { name: string; category: string | null }[];
  demand?: {
    jobs_considered: number;
    strengths: { skill: string; jobs: number }[];
    missing_in_demand: { skill: string; jobs: number }[];
  };
}

export interface Application {
  id: string;
  job_id: string;
  status: AppStatus;
  status_history: { from: string | null; to: string; at: string; note?: string }[];
  notes: string | null;
  tailored_resume_id: string | null;
  cover_letter_draft: string | null;
  outreach_message_draft: string | null;
  interview_prep: {
    technical_questions?: string[];
    prepare_for_gaps?: string[];
    strengths_to_highlight?: string[];
    questions_to_ask?: string[];
    generated_with?: string;
  } | null;
  drafts_approved_at: string | null;
  applied_at: string | null;
  interview_at: string | null;
  updated_at: string;
  job_title: string | null;
  company_name: string | null;
  country: string | null;
}

export interface Overview {
  total_jobs: number;
  active_jobs: number;
  matching_jobs: number;
  high_match_jobs: number;
  visa_sponsorship_jobs: number;
  applications_submitted: number;
  applications_pending: number;
  match_threshold: number;
  high_match_threshold: number;
}

export interface AgentSummary {
  agent_name: string;
  last_status: string | null;
  last_started_at: string | null;
  last_duration_ms: number | null;
  runs_24h: number;
  failures_24h: number;
  items_created_24h: number;
  llm_tokens_24h: number;
}

export interface Execution {
  id: string;
  workflow_run_id: string | null;
  agent_name: string;
  trigger: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  items_processed: number;
  items_created: number;
  items_failed: number;
  error_type: string | null;
  error_message: string | null;
  llm_model: string | null;
  llm_prompt_tokens: number | null;
  llm_completion_tokens: number | null;
  llm_calls: number;
}

export interface Notification {
  id: string;
  kind: string;
  title: string;
  body: string;
  job_id: string | null;
  status: string;
  created_at: string;
}

export interface Source {
  id: string;
  key: string;
  name: string;
  connector: string;
  enabled: boolean;
  last_run_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
  active_jobs: number;
}

// ---------------------------------------------------------------- labels
export const VISA_LABEL: Record<VisaClass, string> = {
  explicit_sponsorship: "Sponsorship offered",
  potential_sponsorship: "Sponsorship possible",
  eu_authorization_required: "EU work permit required",
  not_mentioned: "Not mentioned",
  not_suitable: "Not suitable",
};

export const STATUS_LABEL: Record<AppStatus, string> = {
  saved: "Saved",
  shortlisted: "Shortlisted",
  prepared: "Application prepared",
  applied: "Applied",
  interview_scheduled: "Interview scheduled",
  rejected: "Rejected",
  offer_received: "Offer received",
  withdrawn: "Withdrawn",
};

export const COMPONENT_LABEL: Record<string, string> = {
  technical_skills: "Technical skills",
  experience: "Experience",
  responsibilities: "Responsibilities",
  seniority: "Seniority",
  location: "Location & relocation",
  compensation: "Compensation",
};

export const COUNTRY_NAME: Record<string, string> = {
  DE: "Germany", NL: "Netherlands", IE: "Ireland", SE: "Sweden", DK: "Denmark", FI: "Finland",
  BE: "Belgium", LU: "Luxembourg", AT: "Austria", CH: "Switzerland", FR: "France", ES: "Spain",
  PT: "Portugal", IT: "Italy", PL: "Poland", NO: "Norway", GB: "United Kingdom",
};

export const eur = (n: number | null | undefined) =>
  n == null ? "—" : `€${Math.round(n).toLocaleString("en-GB")}`;

export const ago = (iso: string | null | undefined) => {
  if (!iso) return "—";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
};
