"use client";

import { useEffect, useState, type FormEvent } from "react";

import { Card, Empty, ErrorNote, Loading, useToast } from "@/components/ui";
import {
  COMPONENT_LABEL, COUNTRY_NAME, ago, api, json, type Candidate, type ResumeAnalysis,
} from "@/lib/api";
import { useApi, waitForTask } from "@/lib/hooks";

type TriState = "" | "true" | "false";
const tri = (v: boolean | null): TriState => (v == null ? "" : v ? "true" : "false");
const fromTri = (v: TriState): boolean | null => (v === "" ? null : v === "true");
const list = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

export default function ProfilePage() {
  const cand = useApi<Candidate>("/candidate");
  const c = cand.data;

  return (
    <>
      <h1>Your profile</h1>
      <p className="sub">The agents use only what you enter here. Nothing about your visa status is guessed.</p>
      <ErrorNote error={cand.error} />
      {!c && !cand.error && <Loading />}
      {c && (
        <div className="stack">
          {c.profile_completeness.length > 0 && (
            <Card className="callout" title="Still missing">
              <div className="chips">{c.profile_completeness.map((m) => <span key={m} className="chip">{m}</span>)}</div>
            </Card>
          )}
          <ProfileForm cand={c} onSaved={cand.reload} />
          <Resumes cand={c} onChange={cand.reload} />
          <Skills cand={c} onChange={cand.reload} />
          <Card title="Experience">
            {c.experiences.length ? c.experiences.map((e) => (
              <div key={e.id} style={{ marginBottom: 10 }}>
                <strong>{e.title}</strong>, {e.organization} {e.is_current && <span className="badge info">current</span>}
                {e.description && <div className="meta">{e.description}</div>}
                {e.technologies.length > 0 && <div className="chips" style={{ marginTop: 4 }}>{e.technologies.map((t) => <span key={t} className="chip">{t}</span>)}</div>}
              </div>
            )) : <Empty>No experience entries.</Empty>}
            <p className="note">Edit experience through the API (<code>/api/v1/candidate/experiences</code>) for now.</p>
          </Card>
        </div>
      )}
    </>
  );
}

function ProfileForm({ cand, onSaved }: { cand: Candidate; onSaved: () => void }) {
  const toast = useToast();
  const [f, setF] = useState(() => toForm(cand));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => setF(toForm(cand)), [cand]);

  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const weightSum = Object.values(f.weights).reduce((a, b) => a + (Number(b) || 0), 0);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api("/candidate", {
        method: "PATCH",
        ...json({
          full_name: f.full_name,
          email: f.email || null,
          current_designation: f.current_designation || null,
          years_experience: f.years_experience ? Number(f.years_experience) : null,
          current_organization: f.current_organization || null,
          previous_organizations: list(f.previous_organizations),
          summary: f.summary || null,
          current_country: f.current_country || null,
          citizenship: f.citizenship ? list(f.citizenship) : null,
          has_eu_work_authorization: fromTri(f.has_eu_work_authorization),
          eu_work_authorization_details: f.eu_work_authorization_details || null,
          requires_visa_sponsorship: fromTri(f.requires_visa_sponsorship),
          open_to_relocation: fromTri(f.open_to_relocation),
          relocation_notes: f.relocation_notes || null,
          target_roles: list(f.target_roles),
          preferred_countries: f.preferred_countries,
          min_salary_eur: f.min_salary_eur ? Number(f.min_salary_eur) : null,
          target_salary_eur: f.target_salary_eur ? Number(f.target_salary_eur) : null,
          remote_preference: f.remote_preference || null,
          match_weights: Object.fromEntries(Object.entries(f.weights).map(([k, v]) => [k, Number(v) / 100])),
        }),
      });
      toast("Profile saved. Jobs are re-scored on the next run, or now from Agents.");
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  const countries = Array.from(new Set([...Object.keys(COUNTRY_NAME), ...f.preferred_countries]));

  return (
    <form onSubmit={submit} className="stack">
      <Card title="About you">
        <div className="form-grid">
          <Field label="Full name"><input value={f.full_name} onChange={set("full_name")} required /></Field>
          <Field label="Email"><input type="email" value={f.email} onChange={set("email")} /></Field>
          <Field label="Current designation"><input value={f.current_designation} onChange={set("current_designation")} /></Field>
          <Field label="Years of experience"><input type="number" min={0} max={60} step={0.5} value={f.years_experience} onChange={set("years_experience")} /></Field>
          <Field label="Current organization"><input value={f.current_organization} onChange={set("current_organization")} /></Field>
          <Field label="Previous organizations (comma-separated)"><input value={f.previous_organizations} onChange={set("previous_organizations")} /></Field>
        </div>
        <Field label="Summary"><textarea rows={3} value={f.summary} onChange={set("summary")} /></Field>
        <Field label="Target roles (comma-separated)"><textarea rows={2} value={f.target_roles} onChange={set("target_roles")} /></Field>
      </Card>

      <Card title="Work authorization & relocation">
        <p className="note" style={{ marginTop: 0 }}>Leave a field on “Not set” if you prefer. The visa agent then treats it as unknown instead of guessing.</p>
        <div className="form-grid">
          <Field label="Citizenship (country codes, e.g. IN)"><input value={f.citizenship} onChange={set("citizenship")} placeholder="Not set" /></Field>
          <Field label="Current country (code)"><input value={f.current_country} onChange={set("current_country")} maxLength={2} placeholder="Not set" /></Field>
          <TriField label="Existing EU work authorization" value={f.has_eu_work_authorization} onChange={set("has_eu_work_authorization")} />
          <TriField label="Need visa sponsorship" value={f.requires_visa_sponsorship} onChange={set("requires_visa_sponsorship")} />
          <TriField label="Open to relocation" value={f.open_to_relocation} onChange={set("open_to_relocation")} />
          <Field label="Remote preference">
            <select value={f.remote_preference} onChange={set("remote_preference")}>
              <option value="">Not set</option><option value="any">Any</option><option value="onsite">On-site</option>
              <option value="hybrid">Hybrid</option><option value="remote">Remote</option>
            </select>
          </Field>
        </div>
        <Field label="Authorization details (optional)"><input value={f.eu_work_authorization_details} onChange={set("eu_work_authorization_details")} /></Field>
      </Card>

      <Card title="Where and for how much">
        <label>Preferred countries</label>
        <div className="check-row" style={{ margin: "6px 0 12px" }}>
          {countries.map((cc) => (
            <label key={cc}>
              <input type="checkbox" checked={f.preferred_countries.includes(cc)}
                     onChange={(e) => setF({ ...f, preferred_countries: e.target.checked
                       ? [...f.preferred_countries, cc] : f.preferred_countries.filter((x) => x !== cc) })} />
              {COUNTRY_NAME[cc] ?? cc}
            </label>
          ))}
        </div>
        <div className="form-grid">
          <Field label="Minimum salary (EUR gross / year)"><input type="number" min={0} step={1000} value={f.min_salary_eur} onChange={set("min_salary_eur")} placeholder="Not set" /></Field>
          <Field label="Target salary (EUR gross / year)"><input type="number" min={0} step={1000} value={f.target_salary_eur} onChange={set("target_salary_eur")} placeholder="Not set" /></Field>
        </div>
      </Card>

      <Card title="Match weights" actions={<span className={`badge ${Math.abs(weightSum - 100) < 0.1 ? "good" : "bad"}`}>Total {weightSum}%</span>}>
        <div className="form-grid">
          {Object.entries(f.weights).map(([k, v]) => (
            <Field key={k} label={`${COMPONENT_LABEL[k] ?? k} (%)`}>
              <input type="number" min={0} max={100} value={v}
                     onChange={(e) => setF({ ...f, weights: { ...f.weights, [k]: e.target.value } })} />
            </Field>
          ))}
        </div>
        <p className="note">Weights must add up to 100%.</p>
      </Card>

      <ErrorNote error={error} />
      <div className="row"><button className="primary" disabled={saving || Math.abs(weightSum - 100) > 0.1}>{saving ? "Saving…" : "Save profile"}</button></div>
    </form>
  );
}

function toForm(c: Candidate) {
  return {
    full_name: c.full_name, email: c.email ?? "", current_designation: c.current_designation ?? "",
    years_experience: c.years_experience?.toString() ?? "", current_organization: c.current_organization ?? "",
    previous_organizations: c.previous_organizations.join(", "), summary: c.summary ?? "",
    current_country: c.current_country ?? "", citizenship: (c.citizenship ?? []).join(", "),
    has_eu_work_authorization: tri(c.has_eu_work_authorization),
    eu_work_authorization_details: c.eu_work_authorization_details ?? "",
    requires_visa_sponsorship: tri(c.requires_visa_sponsorship), open_to_relocation: tri(c.open_to_relocation),
    relocation_notes: c.relocation_notes ?? "", target_roles: c.target_roles.join(", "),
    preferred_countries: [...c.preferred_countries], min_salary_eur: c.min_salary_eur?.toString() ?? "",
    target_salary_eur: c.target_salary_eur?.toString() ?? "", remote_preference: c.remote_preference ?? "",
    weights: Object.fromEntries(Object.entries(c.match_weights).map(([k, v]) => [k, String(Math.round(v * 100))])) as Record<string, string>,
  };
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="field" style={{ marginBottom: 8 }}><label>{label}</label>{children}</div>;
}

function TriField({ label, value, onChange }: { label: string; value: TriState; onChange: (e: { target: { value: string } }) => void }) {
  return (
    <Field label={label}>
      <select value={value} onChange={onChange}>
        <option value="">Not set</option><option value="true">Yes</option><option value="false">No</option>
      </select>
    </Field>
  );
}

function Skills({ cand, onChange }: { cand: Candidate; onChange: () => void }) {
  const toast = useToast();
  const [name, setName] = useState("");
  const [level, setLevel] = useState("3");

  async function add(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/candidate/skills", { method: "POST", ...json({ name, proficiency: Number(level) }) });
      setName("");
      onChange();
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "err");
    }
  }
  async function update(id: string, proficiency: number) {
    await api(`/candidate/skills/${id}`, { method: "PATCH", ...json({ proficiency }) });
    onChange();
  }
  async function remove(id: string) {
    await api(`/candidate/skills/${id}`, { method: "DELETE" });
    onChange();
  }

  return (
    <Card title={`Skills inventory (${cand.skills.length})`}>
      <form className="row" onSubmit={add} style={{ marginBottom: 12 }}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Add a skill, e.g. ArgoCD" required aria-label="New skill" />
        <select value={level} onChange={(e) => setLevel(e.target.value)} aria-label="Proficiency">
          {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>Level {n}</option>)}
        </select>
        <button>Add</button>
      </form>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Skill</th><th>Category</th><th>Level (1–5)</th><th>Source</th><th></th></tr></thead>
          <tbody>
            {cand.skills.map((s) => (
              <tr key={s.id}>
                <td className="job-title">{s.name}</td>
                <td className="meta">{s.category ?? "—"}</td>
                <td>
                  <select value={s.proficiency ?? ""} onChange={(e) => update(s.id, Number(e.target.value))} aria-label={`${s.name} level`}>
                    <option value="" disabled>—</option>
                    {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
                  </select>
                </td>
                <td className="meta">{s.source}</td>
                <td><button className="small danger" onClick={() => remove(s.id)}>Remove</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function Resumes({ cand, onChange }: { cand: Candidate; onChange: () => void }) {
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [label, setLabel] = useState("main");
  const [busy, setBusy] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const uploaded = cand.resumes.filter((r) => !r.job_id);

  async function upload(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("version_label", label);
      const r = await api<{ id: string }>("/candidate/resumes", { method: "POST", body: fd });
      toast("Uploaded. Reading your CV…");
      setFile(null);
      onChange();
      setOpenId(r.id);
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "err");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Resumes">
      <form className="row" onSubmit={upload} style={{ marginBottom: 12 }}>
        <input type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
               onChange={(e) => setFile(e.target.files?.[0] ?? null)} aria-label="Resume file" />
        <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Version label" aria-label="Version label" style={{ width: 140 }} />
        <button className="primary" disabled={!file || busy}>{busy ? "Uploading…" : "Upload"}</button>
        <span className="note">PDF or DOCX, up to 10 MB</span>
      </form>
      {uploaded.length === 0 ? <Empty>No resume yet. Upload one so the CV agent can read it.</Empty> : uploaded.map((r) => (
        <div key={r.id} style={{ borderTop: "1px solid var(--border)", padding: "10px 0" }}>
          <div className="row">
            <strong>{r.version_label}</strong>
            <span className="meta">{r.original_filename} · {(r.size_bytes / 1024).toFixed(0)} KB · {ago(r.created_at)}</span>
            {r.is_primary && <span className="badge info">primary</span>}
            {r.parse_error && <span className="badge bad">could not read</span>}
            <span className="spacer" />
            {!r.is_primary && <button className="small" onClick={async () => { await api(`/candidate/resumes/${r.id}/primary`, { method: "POST" }); onChange(); }}>Make primary</button>}
            <button className="small" onClick={() => setOpenId(openId === r.id ? null : r.id)}>{openId === r.id ? "Hide analysis" : "Analysis"}</button>
            <button className="small danger" onClick={async () => { await api(`/candidate/resumes/${r.id}`, { method: "DELETE" }); onChange(); }}>Delete</button>
          </div>
          {openId === r.id && <Analysis resumeId={r.id} onApplied={onChange} />}
        </div>
      ))}
    </Card>
  );
}

function Analysis({ resumeId, onApplied }: { resumeId: string; onApplied: () => void }) {
  const toast = useToast();
  const a = useApi<ResumeAnalysis>(`/candidate/resumes/${resumeId}/analysis`);
  const [picked, setPicked] = useState<string[]>([]);

  const { reload } = a;
  const status = a.data?.status;
  useEffect(() => {
    if (status !== "pending") return;
    const t = setTimeout(() => void reload(), 2500);
    return () => clearTimeout(t);
  }, [status, reload, a.data]);

  if (!a.data) return <p className="meta">Loading…</p>;
  if (a.data.status === "pending") return <p className="meta">The CV agent is reading this file…</p>;
  if (a.data.status === "failed") return (
    <div>
      <ErrorNote error={a.data.error ?? "Could not read this file."} />
      <button className="small" onClick={async () => { const { task_id } = await api<{ task_id: string }>(`/candidate/resumes/${resumeId}/parse`, { method: "POST" }); await waitForTask(task_id); a.reload(); }}>Try again</button>
    </div>
  );
  const d = a.data;
  async function apply() {
    try {
      await api(`/candidate/resumes/${resumeId}/apply-skills`, { method: "POST", ...json({ skills: picked }) });
      toast(`Added ${picked.length} skill(s) to your profile.`);
      setPicked([]);
      onApplied();
      a.reload();
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "err");
    }
  }
  return (
    <div className="grid grid-2" style={{ marginTop: 10 }}>
      <div>
        <h3 style={{ marginTop: 0 }}>Found in this CV</h3>
        <p style={{ margin: 0 }}>{d.years_experience ?? "?"} years of experience · {d.skills?.length ?? 0} skills</p>
        {d.certifications?.length ? <ul className="plain">{d.certifications.map((c) => <li key={c}>{c}</li>)}</ul> : <p className="meta">No certifications recognised.</p>}
        <h3>Suggested skills (not yet in your profile)</h3>
        {d.suggested_skills?.length ? (
          <>
            <div className="check-row">
              {d.suggested_skills.map((s) => (
                <label key={s.name}>
                  <input type="checkbox" checked={picked.includes(s.name)}
                         onChange={(e) => setPicked(e.target.checked ? [...picked, s.name] : picked.filter((x) => x !== s.name))} />
                  {s.name}
                </label>
              ))}
            </div>
            <button className="small primary" style={{ marginTop: 8 }} disabled={!picked.length} onClick={apply}>Add selected to my skills</button>
            <p className="note">Nothing is added unless you select it.</p>
          </>
        ) : <p className="meta">None. Your inventory already covers this CV.</p>}
      </div>
      <div>
        <h3 style={{ marginTop: 0 }}>Demand in your job matches</h3>
        <p className="meta">Across {d.demand?.jobs_considered ?? 0} active jobs</p>
        <label>Your strengths</label>
        <div className="chips">{d.demand?.strengths.map((s) => <span key={s.skill} className="chip good">{s.skill} · {s.jobs}</span>)}</div>
        <label>Often asked, not in your profile</label>
        <div className="chips">{d.demand?.missing_in_demand.map((s) => <span key={s.skill} className="chip bad">{s.skill} · {s.jobs}</span>)}</div>
      </div>
    </div>
  );
}
