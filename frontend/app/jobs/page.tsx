"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Card, Empty, ErrorNote, Loading, ScoreRing, VisaBadge, useToast } from "@/components/ui";
import {
  COUNTRY_NAME, STATUS_LABEL, VISA_LABEL, ago, api, json, type JobSummary, type Page, type VisaClass,
} from "@/lib/api";
import { useApi } from "@/lib/hooks";

const PAGE_SIZE = 25;

export default function JobsPage() {
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [country, setCountry] = useState("");
  const [visa, setVisa] = useState("");
  const [minScore, setMinScore] = useState("");
  const [minSalary, setMinSalary] = useState("");
  const [sort, setSort] = useState("match_score");
  const [bookmarked, setBookmarked] = useState(false);
  const [page, setPage] = useState(1);
  const toast = useToast();

  useEffect(() => {
    const t = setTimeout(() => setDebounced(q), 300);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => setPage(1), [debounced, country, visa, minScore, minSalary, sort, bookmarked]);

  const path = useMemo(() => {
    const p = new URLSearchParams({ sort, page: String(page), page_size: String(PAGE_SIZE) });
    if (debounced) p.set("q", debounced);
    if (country) p.set("country", country);
    if (visa) p.set("visa", visa);
    if (minScore) p.set("min_score", minScore);
    if (minSalary) p.set("min_salary_eur", minSalary);
    if (bookmarked) p.set("bookmarked", "true");
    return `/jobs?${p}`;
  }, [debounced, country, visa, minScore, minSalary, sort, bookmarked, page]);

  const jobs = useApi<Page<JobSummary>>(path);

  async function save(job: JobSummary) {
    try {
      await api("/applications", { method: "POST", ...json({ job_id: job.id }) });
      toast(`Saved “${job.title}” to your applications.`);
      jobs.reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
    }
  }

  const total = jobs.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <>
      <h1>Job Explorer</h1>
      <p className="sub">{total} jobs · the same role on several boards is shown once</p>
      <Card>
        <div className="filters">
          <input type="search" placeholder="Search title, company or description" value={q}
                 onChange={(e) => setQ(e.target.value)} aria-label="Search" />
          <select value={country} onChange={(e) => setCountry(e.target.value)} aria-label="Country">
            <option value="">All countries</option>
            {Object.entries(COUNTRY_NAME).map(([c, n]) => <option key={c} value={c}>{n}</option>)}
          </select>
          <select value={visa} onChange={(e) => setVisa(e.target.value)} aria-label="Visa">
            <option value="">Any visa status</option>
            {(Object.keys(VISA_LABEL) as VisaClass[]).map((v) => <option key={v} value={v}>{VISA_LABEL[v]}</option>)}
          </select>
          <select value={minScore} onChange={(e) => setMinScore(e.target.value)} aria-label="Minimum score">
            <option value="">Any score</option>
            <option value="50">Score ≥ 50</option>
            <option value="65">Score ≥ 65</option>
            <option value="75">Score ≥ 75</option>
          </select>
          <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort">
            <option value="match_score">Best match</option>
            <option value="posted_at">Newest</option>
            <option value="salary">Highest salary</option>
            <option value="discovered_at">Recently found</option>
          </select>
        </div>
        <div className="row" style={{ marginBottom: 8 }}>
          <input type="number" min={0} step={5000} placeholder="Min salary (EUR/yr)" value={minSalary}
                 onChange={(e) => setMinSalary(e.target.value)} aria-label="Minimum salary" style={{ width: 190 }} />
          <label className="row" style={{ color: "var(--text)" }}>
            <input type="checkbox" checked={bookmarked} onChange={(e) => setBookmarked(e.target.checked)}
                   aria-label="Saved only" />
            Saved only
          </label>
        </div>

        <ErrorNote error={jobs.error} />
        {!jobs.data && !jobs.error && <Loading />}
        {jobs.data && jobs.data.items.length === 0 && <Empty>No jobs match these filters.</Empty>}
        {jobs.data && jobs.data.items.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Match</th><th>Job</th><th>Location</th><th>Visa</th><th>Salary</th><th>Posted</th><th></th>
                </tr>
              </thead>
              <tbody>
                {jobs.data.items.map((j) => (
                  <tr key={j.id}>
                    <td style={{ width: 56 }}><ScoreRing score={j.match_score} /></td>
                    <td>
                      <Link href={`/jobs/${j.id}`} className="job-title">{j.title}</Link>
                      <div className="meta">{j.company_name ?? "Unknown company"}{j.source_key === "sample" ? " · sample data" : ""}</div>
                    </td>
                    <td>
                      {[j.city, j.country].filter(Boolean).join(", ") || "Europe-wide"}
                      <div className="meta">{j.remote_type !== "unknown" ? j.remote_type : ""}</div>
                    </td>
                    <td><VisaBadge value={j.visa_classification} /></td>
                    <td className="meta">
                      {j.salary_max ? `${j.salary_currency ?? ""} ${Math.round(j.salary_min ?? j.salary_max).toLocaleString("en-GB")}–${Math.round(j.salary_max).toLocaleString("en-GB")}` : "Not stated"}
                    </td>
                    <td className="meta">{ago(j.posted_at)}</td>
                    <td>
                      {j.application_status
                        ? <span className="badge info">{STATUS_LABEL[j.application_status]}</span>
                        : <button className="small" onClick={() => save(j)}>Save</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="pager">
          <button className="small" disabled={page <= 1} onClick={() => setPage(page - 1)}>← Previous</button>
          <span className="meta">Page {page} of {pages}</span>
          <button className="small" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next →</button>
        </div>
      </Card>
    </>
  );
}
