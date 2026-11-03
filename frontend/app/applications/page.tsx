"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Card, Empty, ErrorNote, Loading, useToast } from "@/components/ui";
import { STATUS_LABEL, ago, api, download, json, type AppStatus, type Application } from "@/lib/api";
import { useApi, waitForTask } from "@/lib/hooks";

const COLUMNS: AppStatus[] = [
  "saved", "shortlisted", "prepared", "applied", "interview_scheduled", "offer_received", "rejected",
];

export default function ApplicationsPage() {
  const apps = useApi<Application[]>("/applications");
  const [selected, setSelected] = useState<string | null>(null);
  const current = apps.data?.find((a) => a.id === selected) ?? null;

  return (
    <>
      <h1>Application tracker</h1>
      <p className="sub">Save jobs from the explorer, then move them along. Agents prepare drafts, and you send everything yourself.</p>
      <ErrorNote error={apps.error} />
      {!apps.data && !apps.error && <Loading />}
      {apps.data && apps.data.length === 0 && (
        <Card><Empty>No applications yet. Open the <Link href="/jobs">Job Explorer</Link> and save a job.</Empty></Card>
      )}
      {apps.data && apps.data.length > 0 && (
        <div className="board">
          {COLUMNS.map((col) => {
            const items = apps.data!.filter((a) => a.status === col);
            return (
              <div key={col} className="column">
                <h2><span>{STATUS_LABEL[col]}</span><span className="meta">{items.length}</span></h2>
                {items.map((a) => (
                  <div key={a.id} className={`app-card ${selected === a.id ? "selected" : ""}`}
                       onClick={() => setSelected(a.id)} role="button" tabIndex={0}
                       onKeyDown={(e) => e.key === "Enter" && setSelected(a.id)}>
                    <div className="job-title">{a.job_title}</div>
                    <div className="meta">{a.company_name} · {a.country ?? "Europe"}</div>
                    <div className="meta">updated {ago(a.updated_at)}</div>
                    {a.cover_letter_draft && <span className={`badge ${a.drafts_approved_at ? "good" : "warn"}`}>
                      {a.drafts_approved_at ? "Drafts approved" : "Drafts to review"}</span>}
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      )}
      {current && <Detail app={current} onChange={apps.reload} onClose={() => setSelected(null)} />}
    </>
  );
}

function Detail({ app, onChange, onClose }: { app: Application; onChange: () => void; onClose: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [cover, setCover] = useState(app.cover_letter_draft ?? "");
  const [outreach, setOutreach] = useState(app.outreach_message_draft ?? "");
  const [notes, setNotes] = useState(app.notes ?? "");
  useEffect(() => {
    setCover(app.cover_letter_draft ?? "");
    setOutreach(app.outreach_message_draft ?? "");
    setNotes(app.notes ?? "");
  }, [app]);

  async function run(label: string, fn: () => Promise<unknown>, ok: string) {
    setBusy(label);
    try {
      await fn();
      toast(ok);
      onChange();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
    } finally {
      setBusy(null);
    }
  }

  const prep = app.interview_prep;
  const dirty = cover !== (app.cover_letter_draft ?? "") || outreach !== (app.outreach_message_draft ?? "");

  return (
    <Card className="spaced" title={<>{app.job_title} <span className="meta">· {app.company_name}</span></>}
          actions={<>
            <Link className="button" href={`/jobs/${app.job_id}`}>View job</Link>
            <button onClick={onClose}>Close</button>
          </>}>
      <div className="row" style={{ marginBottom: 12 }}>
        <label htmlFor="status">Status</label>
        <select id="status" value={app.status} disabled={busy !== null}
                onChange={(e) => run("status", () => api(`/applications/${app.id}`, { method: "PATCH", ...json({ status: e.target.value }) }), "Status updated.")}>
          {(Object.keys(STATUS_LABEL) as AppStatus[]).map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
        </select>
        <span className="spacer" />
        <button className="primary" disabled={busy !== null}
                onClick={() => run("prepare", async () => {
                  const { task_id } = await api<{ task_id: string }>(`/applications/${app.id}/prepare`, { method: "POST" });
                  toast("Preparing drafts…");
                  const state = await waitForTask(task_id);
                  if (state !== "SUCCESS") throw new Error(`Preparation ended: ${state}`);
                }, "Drafts ready for review.")}>
          {busy === "prepare" ? "Preparing…" : app.cover_letter_draft ? "Regenerate drafts" : "Prepare application"}
        </button>
        <button className="small" onClick={() => run("delete", () => api(`/applications/${app.id}`, { method: "DELETE" }), "Removed.").then(onClose)}
                disabled={busy !== null}>Remove</button>
      </div>

      {app.cover_letter_draft == null ? (
        <Empty>No drafts yet. “Prepare application” writes a tailored CV, cover letter, recruiter message and interview notes. Nothing is ever sent.</Empty>
      ) : (
        <div className="grid grid-2">
          <div>
            <h3 style={{ marginTop: 0 }}>Cover letter</h3>
            <textarea rows={12} value={cover} onChange={(e) => setCover(e.target.value)} aria-label="Cover letter draft" />
            <h3>Recruiter message</h3>
            <textarea rows={4} value={outreach} onChange={(e) => setOutreach(e.target.value)} aria-label="Recruiter message draft" />
            <div className="row" style={{ marginTop: 8 }}>
              <button disabled={!dirty || busy !== null}
                      onClick={() => run("save", () => api(`/applications/${app.id}/drafts`, { method: "PATCH", ...json({ cover_letter_draft: cover, outreach_message_draft: outreach }) }), "Drafts saved.")}>
                Save edits
              </button>
              <button className="primary" disabled={dirty || busy !== null || Boolean(app.drafts_approved_at)}
                      onClick={() => run("approve", () => api(`/applications/${app.id}/approve-drafts`, { method: "POST" }), "Drafts approved.")}>
                {app.drafts_approved_at ? "Approved" : "Approve drafts"}
              </button>
              {app.tailored_resume_id && (
                <button onClick={() => download(`/applications/${app.id}/tailored-cv`, `CV - ${app.company_name ?? "job"}.docx`).catch((e) => toast(String(e), "err"))}>
                  Download tailored CV
                </button>
              )}
              <button className="small" onClick={() => navigator.clipboard?.writeText(outreach).then(() => toast("Message copied."))}>Copy message</button>
            </div>
            <p className="note">
              {app.drafts_approved_at ? `Approved ${ago(app.drafts_approved_at)}. ` : "Not approved yet. "}
              Written {prep?.generated_with === "llm" ? "by the local AI model" : "from templates (AI model not running)"}.
              You send applications and messages yourself.
            </p>
          </div>
          <div>
            <h3 style={{ marginTop: 0 }}>Interview preparation</h3>
            <label>Technical questions to practise</label>
            <ul className="plain">{prep?.technical_questions?.map((q) => <li key={q}>{q}</li>)}</ul>
            {!!prep?.prepare_for_gaps?.length && (<><label>Gaps to prepare for</label><ul className="plain cons">{prep.prepare_for_gaps.map((q) => <li key={q}>{q}</li>)}</ul></>)}
            <label>Strengths to highlight</label>
            <div className="chips">{prep?.strengths_to_highlight?.map((s) => <span key={s} className="chip good">{s}</span>)}</div>
            <label>Questions to ask them</label>
            <ul className="plain">{prep?.questions_to_ask?.map((q) => <li key={q}>{q}</li>)}</ul>
          </div>
        </div>
      )}

      <h3>Notes</h3>
      <textarea rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} aria-label="Notes" />
      <div className="row" style={{ marginTop: 6 }}>
        <button className="small" disabled={notes === (app.notes ?? "")}
                onClick={() => run("notes", () => api(`/applications/${app.id}`, { method: "PATCH", ...json({ notes }) }), "Notes saved.")}>Save notes</button>
      </div>

      <h3>History</h3>
      <ul className="plain">
        {app.status_history.map((h, i) => (
          <li key={i}>{h.from ? `${STATUS_LABEL[h.from as AppStatus] ?? h.from} → ` : ""}{STATUS_LABEL[h.to as AppStatus] ?? h.to}
            <span className="meta"> · {ago(h.at)}{h.note ? ` · ${h.note}` : ""}</span></li>
        ))}
      </ul>
    </Card>
  );
}
