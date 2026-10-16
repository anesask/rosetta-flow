// Types mirror rosetta_flow.app.server and app.live. All trace and report text is untrusted
// (agent and tool output): React renders it as text, never as HTML.

export type Span = {
  id: string;
  kind: string;
  text?: string;
  tool?: string;
  args?: unknown;
  result?: unknown;
  status?: string;
  call_id?: string;
};

export type Sabotage = { name: string; text: string };

export type LiveRun = {
  trace_id: string;
  domain: string;
  language: string;
  intent: string;
  agent: string;
  spans: Span[];
  sabotage: Sabotage[];
  tool_docs?: Record<string, string>;
};

export type LiveInfo = { screener: string; confirmer: string | null; available: boolean; runs: LiveRun[] };

export type Finding = {
  error_type: string;
  span_ids: string[];
  evidence: string[];
  explanation: string;
  expected_behavior?: string;
  impact?: string;
  severity?: string;
  confidence?: number;
};

export type EvidenceCheck = { finding: number; unverified_quotes: string[] };

export type TierResult = {
  model: string;
  verdict: string;
  failure: string | null;
  findings: Finding[];
  evidence: EvidenceCheck[];
  seconds: number;
  tool_calls: number;
  tokens: number;
  tools?: string[];
};

export type Truth = { sabotage: string | null; error_type?: string; span_ids?: string[]; note?: string };

export type LiveEvent =
  | { event: "run"; spans: Span[]; truth: Truth }
  | { event: "tier"; tier: "screener" | "confirmer"; model: string }
  | { event: "tool"; tier: "screener" | "confirmer"; name: string; args: string }
  | { event: "screened"; result: TierResult; escalated: boolean }
  | { event: "confirmed"; result: TierResult }
  | { event: "done"; verdict: string; caught: boolean; seconds: number }
  | { event: "error"; message: string };

export type FleetRow = {
  id: string;
  domain: string;
  error: string | null;
  screen: string;
  escalated: boolean;
  final: string;
  tok8: number;
  tok70: number;
  tok70_alone: number;
  alone: string;
};

export type RunSummary = {
  trace_id: string;
  domain: string;
  language: string;
  steps: number;
  verdict: string;
  findings: number;
  severity: string | null;
  types: string[];
  truth: string[] | null;
  live: boolean;
};

export type RunDetail = {
  summary: RunSummary;
  spans: Span[];
  audit: {
    model: string;
    failure: string | null;
    report: { verdict: string; findings: Finding[] } | null;
    evidence: EvidenceCheck[];
    tool_calls: number;
    duration_s: number;
  } | null;
  truth: { type: string; span_ids: string[] }[] | null;
};

export type TrailEntry = { at: string; reviewer: string; trace_id: string; finding: number; decision: string; hash: string };
export type Trail = {
  entries: TrailEntry[];
  count: number;
  intact: boolean;
  broken_at: number | null;
  latest: Record<string, string>;
};

/** CHF per million tokens at the CSCS inference API. */
export const PRICE = { "8B": 0.0122, "70B": 0.0923 };

export const typeName = (t: string | null | undefined) => (t ?? "").replaceAll("_", " ");

export const shortModel = (m: string | null | undefined) => (m ?? "").split("/").pop() ?? "";

export const costOf = (r: TierResult) => (r.tokens / 1e6) * (r.model.includes("70B") ? PRICE["70B"] : PRICE["8B"]);

export async function getJSON<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return (await res.json()) as T;
}

export async function postJSON<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = (await res.json().catch(() => ({}))) as { detail?: string };
  if (!res.ok) throw new Error(data.detail ?? res.statusText);
  return data as T;
}

/** POST and read a newline-delimited JSON stream, one event per line. */
export async function* streamNDJSON<T>(url: string): AsyncGenerator<T> {
  const res = await fetch(url, { method: "POST" });
  if (!res.ok) {
    const d = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(d.detail ?? res.statusText);
  }
  const reader = res.body!.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let nl;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl);
      buf = buf.slice(nl + 1);
      if (line.trim()) yield JSON.parse(line) as T;
    }
  }
}
