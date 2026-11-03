"use client";

import Link from "next/link";
import { useState } from "react";

import { Card, Empty, ErrorNote, Loading, ScoreRing, VisaBadge, useToast } from "@/components/ui";
import {
  ago, api, json, type AgentSummary, type Candidate, type JobSummary, type Notification,
  type Overview, type Page,
} from "@/lib/api";
import { useApi, waitForTask } from "@/lib/hooks";

export default function OverviewPage() {
  const stats = useApi<Overview>("/stats/overview");
  const top = useApi<Page<JobSummary>>("/jobs?sort=match_score&page_size=6");
  const notes = useApi<Notification[]>("/notifications?limit=8");
  const agents = useApi<AgentSummary[]>("/agents/summary");
  const cand = useApi<Candidate>("/candidate");
  const toast = useToast();
  const [running, setRunning] = useState(false);

  async function runNow() {
    setRunning(true);
    try {
      const r = await api<{ queued: { task_id: string }[] }>("/pipeline/run", { method: "POST", ...json({}) });
      toast("Search started. This usually takes about a minute.");
      const states = await Promise.all(r.queued.map((q) => waitForTask(q.task_id)));
      toast(states.every((s) => s === "SUCCESS") ? "Search finished." : `Search ended: ${states.join(", ")}`,
            states.every((s) => s === "SUCCESS") ? "ok" : "err");
      await Promise.all([stats.reload(), top.reload(), notes.reload(), agents.reload()]);
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
    } finally {
      setRunning(false);
    }
  }

  const s = stats.data;
  const discovery = agents.data?.find((a) => a.agent_name === "discovery");
  const missing = cand.data?.profile_completeness ?? [];

  return (
    <>
      <div className="row">
        <div>
          <h1>Overview</h1>
          <p className="sub">
            Last search {ago(discovery?.last_started_at)}
            {discovery?.last_status ? ` · ${discovery.last_status}` : ""}
          </p>
        </div>
        <span className="spacer" />
        <button className="primary" onClick={runNow} disabled={running}>
          {running ? "Searching…" : "Find & analyse jobs now"}
        </button>
      </div>

      <ErrorNote error={stats.error} />
      {s && (
        <div className="stats">
          <Stat label="Jobs discovered" value={s.total_jobs} sub={`${s.active_jobs} active`} />
          <Stat label={`Match your profile (≥${s.match_threshold})`} value={s.matching_jobs} />
          <Stat label={`High matches (≥${s.high_match_threshold})`} value={s.high_match_jobs} tone="good" />
          <Stat label="Visa sponsorship (offered or possible)" value={s.visa_sponsorship_jobs} tone="accent" />
          <Stat label="Applications submitted" value={s.applications_submitted} />
          <Stat label="Applications pending" value={s.applications_pending} />
        </div>
      )}

      {missing.length > 0 && (
        <Card className="callout" title="Complete your profile for accurate results">
          <p className="note">The agents never guess these. Until you fill them in, visa and salary fit are scored as unknown.</p>
          <div className="chips">{missing.map((m) => <span key={m} className="chip">{m}</span>)}</div>
          <p><Link href="/profile">Open your profile →</Link></p>
        </Card>
      )}

      <div className="grid grid-3" style={{ marginTop: 16 }}>
        <Card title="Top matches" actions={<Link href="/jobs">All jobs →</Link>}>
          {!top.data ? <Loading /> : top.data.items.length ? (
            <div className="table-wrap">
              <table>
                <tbody>
                  {top.data.items.map((j) => (
                    <tr key={j.id}>
                      <td style={{ width: 52 }}><ScoreRing score={j.match_score} /></td>
                      <td>
                        <Link href={`/jobs/${j.id}`} className="job-title">{j.title}</Link>
                        <div className="meta">{j.company_name} · {[j.city, j.country].filter(Boolean).join(", ") || "Europe"}</div>
                      </td>
                      <td><VisaBadge value={j.visa_classification} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <Empty>No jobs yet. Run a search to get started.</Empty>}
        </Card>

        <Card title="Notifications" actions={
          <button className="small" onClick={async () => { await api("/notifications/read", { method: "POST" }); notes.reload(); }}>
            Mark all read
          </button>}>
          {!notes.data ? <Loading /> : notes.data.length ? (
            <ul className="plain" style={{ paddingLeft: 0, listStyle: "none" }}>
              {notes.data.map((n) => (
                <li key={n.id} style={{ marginBottom: 10, opacity: n.status === "read" ? 0.6 : 1 }}>
                  <div style={{ fontWeight: 600 }}>
                    {n.job_id ? <Link href={`/jobs/${n.job_id}`}>{n.title}</Link> : n.title}
                  </div>
                  <div className="meta">{kindLabel(n.kind)} · {ago(n.created_at)}</div>
                </li>
              ))}
            </ul>
          ) : <Empty>No notifications.</Empty>}
        </Card>
      </div>
    </>
  );
}

function kindLabel(k: string) {
  return { high_match: "High match", visa_sponsorship: "Visa sponsorship", new_jobs: "New jobs",
           daily_digest: "Digest", system: "System" }[k] ?? k;
}

function Stat({ label, value, sub, tone }: { label: string; value: number; sub?: string; tone?: string }) {
  return (
    <div className={`stat ${tone ?? ""}`}>
      <div className="value">{value}</div>
      <div className="label">{label}{sub ? ` · ${sub}` : ""}</div>
    </div>
  );
}
