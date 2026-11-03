"use client";

import { useState } from "react";

import { Card, Empty, ErrorNote, Loading, useToast } from "@/components/ui";
import { ago, api, json, type AgentSummary, type Execution, type Source } from "@/lib/api";
import { useApi, waitForTask } from "@/lib/hooks";

const AGENT_LABEL: Record<string, string> = {
  orchestrator: "Orchestrator (whole pipeline)", discovery: "Job discovery", selection: "Selection",
  embedding: "Embeddings", matching: "Job matching", visa: "Visa intelligence", salary: "Salary intelligence",
  ranking: "Ranking", notifications: "Notifications", cv_intelligence: "CV intelligence",
  application: "Application preparation", job_expiry: "Job expiry",
};

export default function AgentsPage() {
  const summary = useApi<AgentSummary[]>("/agents/summary");
  const [filter, setFilter] = useState("");
  const execs = useApi<Execution[]>(`/agents/executions?limit=40${filter ? `&agent=${filter}` : ""}`);
  const sources = useApi<Source[]>("/sources");
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  async function run(body: object, label: string) {
    setBusy(true);
    try {
      const r = await api<{ queued: { task_id: string }[] }>("/pipeline/run", { method: "POST", ...json(body) });
      toast(`${label} started…`);
      const states = await Promise.all(r.queued.map((q) => waitForTask(q.task_id)));
      toast(`${label}: ${states.join(", ")}`, states.every((s) => s === "SUCCESS") ? "ok" : "err");
      summary.reload(); execs.reload(); sources.reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
    } finally {
      setBusy(false);
    }
  }

  async function toggle(s: Source) {
    await api(`/sources/${s.id}`, { method: "PATCH", ...json({ enabled: !s.enabled }) });
    sources.reload();
  }

  return (
    <>
      <div className="row">
        <div><h1>Agent monitoring</h1><p className="sub">What every agent did, when, and how long it took.</p></div>
        <span className="spacer" />
        <button disabled={busy} onClick={() => run({ analyse_only: true, force: true }, "Re-analysis")}>Re-analyse all jobs</button>
        <button className="primary" disabled={busy} onClick={() => run({}, "Search")}>{busy ? "Running…" : "Run full search"}</button>
      </div>

      <ErrorNote error={summary.error} />
      <Card title="Agents (last 24 hours)">
        <div className="table-wrap">
          <table>
            <thead><tr><th>Agent</th><th>Last status</th><th>Last run</th><th className="num">Duration</th>
              <th className="num">Runs</th><th className="num">Failed</th><th className="num">Created</th><th className="num">LLM tokens</th></tr></thead>
            <tbody>
              {summary.data?.map((a) => (
                <tr key={a.agent_name}>
                  <td className="job-title">{AGENT_LABEL[a.agent_name] ?? a.agent_name}</td>
                  <td><StatusBadge status={a.last_status} /></td>
                  <td className="meta">{ago(a.last_started_at)}</td>
                  <td className="num">{fmtMs(a.last_duration_ms)}</td>
                  <td className="num">{a.runs_24h}</td>
                  <td className="num" style={{ color: a.failures_24h ? "var(--low)" : undefined }}>{a.failures_24h}</td>
                  <td className="num">{a.items_created_24h}</td>
                  <td className="num">{a.llm_tokens_24h || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card className="spaced" title="Recent executions" actions={
        <select value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter by agent">
          <option value="">All agents</option>
          {Object.entries(AGENT_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>}>
        {!execs.data ? <Loading /> : execs.data.length ? (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Agent</th><th>Status</th><th>Trigger</th><th>Started</th><th className="num">Duration</th>
                <th className="num">Processed</th><th className="num">Created</th><th className="num">Failed</th><th>Detail</th></tr></thead>
              <tbody>
                {execs.data.map((e) => (
                  <tr key={e.id}>
                    <td>{AGENT_LABEL[e.agent_name] ?? e.agent_name}</td>
                    <td><StatusBadge status={e.status} /></td>
                    <td className="meta">{e.trigger}</td>
                    <td className="meta">{ago(e.started_at)}</td>
                    <td className="num">{fmtMs(e.duration_ms)}</td>
                    <td className="num">{e.items_processed}</td>
                    <td className="num">{e.items_created}</td>
                    <td className="num">{e.items_failed}</td>
                    <td className="meta" style={{ maxWidth: 320 }}>
                      {e.error_message ?? (e.llm_calls ? `${e.llm_calls} LLM calls · ${(e.llm_prompt_tokens ?? 0) + (e.llm_completion_tokens ?? 0)} tokens` : "")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Empty>No executions yet.</Empty>}
      </Card>

      <Card className="spaced" title="Job sources">
        <div className="table-wrap">
          <table>
            <thead><tr><th>Source</th><th>Type</th><th className="num">Active jobs</th><th>Last success</th><th>Last error</th><th>Enabled</th></tr></thead>
            <tbody>
              {sources.data?.filter((s) => s.key !== "sample").map((s) => (
                <tr key={s.id}>
                  <td className="job-title">{s.name}</td>
                  <td className="meta">{s.connector}</td>
                  <td className="num">{s.active_jobs}</td>
                  <td className="meta">{ago(s.last_success_at)}</td>
                  <td className="meta" style={{ color: s.last_error ? "var(--low)" : undefined, maxWidth: 300 }}>{s.last_error ?? "—"}</td>
                  <td><input type="checkbox" checked={s.enabled} onChange={() => toggle(s)} aria-label={`Enable ${s.name}`} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}

function StatusBadge({ status }: { status: string | null }) {
  if (!status) return <span className="badge muted">never run</span>;
  const tone = { succeeded: "good", failed: "bad", running: "info", retrying: "warn" }[status] ?? "muted";
  return <span className={`badge ${tone}`}>{status}</span>;
}

function fmtMs(ms: number | null) {
  if (ms == null) return "—";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}
