"use client";

import Link from "next/link";
import { Fragment, use, useState } from "react";

import { Bar, Card, Empty, ErrorNote, ScoreRing, Tri, VisaBadge, useToast } from "@/components/ui";
import {
  COMPONENT_LABEL, STATUS_LABEL, ago, api, eur, json, type JobDetail,
} from "@/lib/api";
import { useApi, waitForTask } from "@/lib/hooks";

export default function JobPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const job = useApi<JobDetail>(`/jobs/${id}`);
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  async function save() {
    try {
      await api("/applications", { method: "POST", ...json({ job_id: id }) });
      toast("Saved to your applications.");
      job.reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
    }
  }

  async function reprocess() {
    setBusy(true);
    try {
      const { task_id } = await api<{ task_id: string }>(`/jobs/${id}/reprocess`, { method: "POST" });
      toast("Re-analysing this job…");
      const state = await waitForTask(task_id);
      toast(state === "SUCCESS" ? "Analysis updated." : `Re-analysis ended: ${state}`, state === "SUCCESS" ? "ok" : "err");
      job.reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
    } finally {
      setBusy(false);
    }
  }

  if (job.error) return <ErrorNote error={job.error} />;
  const j = job.data;
  if (!j) return <p className="meta">Loading…</p>;
  const m = j.match, v = j.visa, s = j.salary;

  return (
    <>
      <p className="meta"><Link href="/jobs">← Job Explorer</Link></p>
      <div className="row" style={{ alignItems: "flex-start", marginBottom: 16 }}>
        <ScoreRing score={m?.overall_score ?? null} size={64} />
        <div style={{ flex: 1, minWidth: 240 }}>
          <h1>{j.title}</h1>
          <p className="sub" style={{ marginBottom: 6 }}>
            {j.company_name ?? "Unknown company"} · {[j.city, j.country].filter(Boolean).join(", ") || "Europe-wide"}
            {j.remote_type !== "unknown" ? ` · ${j.remote_type}` : ""} · posted {ago(j.posted_at)}
          </p>
          <div className="row">
            <VisaBadge value={v?.classification ?? null} />
            {m?.recommended && <span className="badge good">Recommended</span>}
            {j.status !== "active" && <span className="badge warn">{j.status}</span>}
            {j.source_key === "sample" && <span className="badge muted">Sample data</span>}
          </div>
        </div>
        <div className="row">
          {j.application_status
            ? <Link className="button" href="/applications">{STATUS_LABEL[j.application_status]} →</Link>
            : <button onClick={save}>Save job</button>}
          <button onClick={reprocess} disabled={busy}>{busy ? "Analysing…" : "Re-analyse"}</button>
          <a className="button primary" href={j.apply_url ?? j.url} target="_blank" rel="noopener noreferrer"
             style={{ background: "var(--accent)", color: "#fff", borderColor: "var(--accent)" }}>
            Open job posting ↗
          </a>
        </div>
      </div>

      <div className="grid grid-2">
        <Card title="Why this score">
          {!m ? <Empty>Not scored yet. Run the analysis.</Empty> : (
            <>
              {Object.entries(m.component_scores).map(([k, val]) => (
                <Bar key={k} label={`${COMPONENT_LABEL[k] ?? k} · ${Math.round((m.weights_used[k] ?? 0) * 100)}%`} value={val} />
              ))}
              <h3>In favour</h3>
              {m.reasons_for.length ? <ul className="plain pros">{m.reasons_for.map((r) => <li key={r}>{r}</li>)}</ul> : <Empty>—</Empty>}
              <h3>Watch out</h3>
              {m.reasons_against.length ? <ul className="plain cons">{m.reasons_against.map((r) => <li key={r}>{r}</li>)}</ul> : <Empty>Nothing flagged.</Empty>}
              <h3>Interview likelihood</h3>
              <p style={{ margin: 0 }}><strong style={{ textTransform: "capitalize" }}>{m.interview_likelihood}</strong>{" "}
                <span className="note">· {m.interview_likelihood_note}</span></p>
              {m.semantic_similarity == null && (
                <p className="note">Meaning-based matching is off because the local AI model isn't running. The score uses skill coverage only.</p>
              )}
            </>
          )}
        </Card>

        <Card title="Skills">
          {!m ? <Empty>—</Empty> : (
            <>
              <h3 style={{ marginTop: 0 }}>You have ({m.matched_skills.length})</h3>
              <div className="chips">{m.matched_skills.map((x) => <span key={x} className="chip good">{x}</span>)}</div>
              <h3>Missing ({m.missing_skills.length})</h3>
              {m.missing_skills.length ? <div className="chips">{m.missing_skills.map((x) => <span key={x} className="chip bad">{x}</span>)}</div> : <Empty>None.</Empty>}
              {m.experience_gaps.length > 0 && (<><h3>Experience</h3><ul className="plain cons">{m.experience_gaps.map((g) => <li key={g}>{g}</li>)}</ul></>)}
            </>
          )}
        </Card>

        <Card title="Visa & work authorization">
          {!v ? <Empty>Not analysed yet.</Empty> : (
            <>
              <p style={{ marginTop: 0 }}><VisaBadge value={v.classification} />{" "}
                <span className="note">confidence {v.confidence != null ? Math.round(v.confidence * 100) : "—"}% · {v.method}</span></p>
              <p>{v.rationale}</p>
              <dl className="kv">
                <dt>Sponsorship mentioned</dt><dd><Tri value={v.mentions_sponsorship} yes="Offered" no="Not offered" /></dd>
                <dt>Relocation support</dt><dd><Tri value={v.relocation_support} /></dd>
                <dt>Non-EU applicants</dt><dd><Tri value={v.non_eu_applicants_accepted} yes="Accepted" no="Not accepted" /></dd>
                <dt>EU authorization required</dt><dd><Tri value={v.eu_authorization_required} /></dd>
                <dt>Documented sponsor</dt><dd><Tri value={v.employer_documented_sponsor} /></dd>
              </dl>
              <h3>Evidence</h3>
              {v.evidence.length ? v.evidence.map((e, i) => (
                <blockquote key={i}>
                  “{e.quote}”
                  <div className="meta">{e.signal.replace(/_/g, " ")}{e.url && <> · <a href={e.url} target="_blank" rel="noopener noreferrer">source</a></>}</div>
                </blockquote>
              )) : <Empty>The posting says nothing about visas, work permits or relocation.</Empty>}
              {v.country_pathways.length > 0 && (
                <>
                  <h3>Work-permit routes in this country</h3>
                  <ul className="plain">
                    {v.country_pathways.map((p) => (
                      <li key={p.name}><a href={p.reference_url} target="_blank" rel="noopener noreferrer">{p.name}</a>
                        <div className="meta">{p.notes}</div></li>
                    ))}
                  </ul>
                  <p className="note">General information, not legal advice. Thresholds change yearly. Check the official pages.</p>
                </>
              )}
            </>
          )}
        </Card>

        <Card title="Salary">
          {!s ? <Empty>Not analysed yet.</Empty> : (
            <>
              <dl className="kv">
                <dt>Advertised</dt>
                <dd>{s.has_actual_salary ? `${eur(s.actual_min_eur)} – ${eur(s.actual_max_eur)} gross / year` : <span className="badge warn">Not stated in the posting</span>}</dd>
                {j.salary_raw && <><dt>As written</dt><dd className="meta">{j.salary_raw}</dd></>}
                {!s.has_actual_salary && s.estimated_max_eur && <><dt>Estimate</dt><dd>{eur(s.estimated_min_eur)} – {eur(s.estimated_max_eur)} <span className="badge muted">estimate</span></dd></>}
                <dt>Benchmark median</dt><dd>{eur(s.benchmark_median_eur)} <span className="note">(approximate)</span></dd>
                <dt>Take-home (est.)</dt><dd>{eur(s.est_net_annual_eur)} / year</dd>
                <dt>Living costs (est.)</dt><dd>{eur(s.est_living_cost_annual_eur)} / year</dd>
                <dt>Savings (est.)</dt><dd><strong>{eur(s.est_savings_annual_eur)}</strong> / year</dd>
                <dt>Meets your minimum</dt><dd><Tri value={s.meets_candidate_minimum} /></dd>
              </dl>
              <details style={{ marginTop: 10 }}>
                <summary className="note" style={{ cursor: "pointer" }}>Assumptions behind these numbers</summary>
                <dl className="kv" style={{ marginTop: 8 }}>
                  {Object.entries(s.assumptions).map(([k, val]) => (
                    <Fragment key={k}><dt>{k.replace(/_/g, " ")}</dt><dd className="meta">{String(val)}</dd></Fragment>
                  ))}
                </dl>
              </details>
            </>
          )}
        </Card>
      </div>

      <Card title="Job description" className="spaced">
        <div className="row meta" style={{ marginBottom: 8 }}>
          {j.employment_type && <span>{j.employment_type}</span>}
          {j.seniority && <span>· {j.seniority}</span>}
          {j.experience_min_years != null && <span>· {j.experience_min_years}+ years</span>}
          <span>· found {ago(j.discovered_at)} via {j.source_key}</span>
        </div>
        <div className="description">{j.description || "No description provided."}</div>
      </Card>
    </>
  );
}
