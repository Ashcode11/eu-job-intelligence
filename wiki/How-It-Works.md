# How It Works

> **Status:** this page describes the full design. Today the foundation and **job discovery**
> are working. Matching, visa, salary and application agents come in Phase 3.
> See the [Roadmap](Roadmap.md).

## The big picture

```
 Job boards ──► Discovery ──► Clean up ──► Remove duplicates ──► Match ──► Visa check
                                                                            │
 Dashboard ◄── Notify ◄── Save ◄── Rank ◄── Salary check ◄──────────────────┘
```

A coordinator (built with **LangGraph**) runs these steps in order. If a step fails,
it retries and records what happened.

## The six agents

| Agent | In one sentence |
|---|---|
| **Job Discovery** | Collects jobs from public job boards every day and skips duplicates. |
| **CV Intelligence** | Reads your PDF/DOCX resume and builds your skills list. |
| **Job Matching** | Scores every job from 0 to 100 against your profile. |
| **Visa Intelligence** | Reads the job post for visa and relocation evidence. |
| **Salary Intelligence** | Converts salaries to yearly EUR and estimates take-home pay and savings. |
| **Application Prep** | Drafts a tailored CV, cover letter and interview notes. It never sends them. |

## How job discovery works (live today)

1. **Every 5 minutes** the scheduler checks your saved searches. A search runs when its
   schedule is due (default: daily at 06:00 UTC).
2. **Each source is fetched politely**: it checks robots.txt, waits between requests and
   retries if the site is busy. If one source fails, the others still run.
3. **Only relevant jobs are kept**:
   - the title must contain all words of one of your keywords (in any order), so
     "cloud architect" matches "Senior Cloud **Solutions** Architect"
   - the country must be one of yours. Europe-wide remote jobs ("Remote, EMEA") are kept.
4. **No duplicates**:
   - the same job seen again is updated, never added twice
   - the same role posted on two boards is shown once
5. **Old jobs disappear**:
   - a job removed from a company's board is marked **closed**
   - a job not seen for 21 days, or past its deadline, is marked **expired**
6. Every run is recorded: how many jobs were fetched, kept or skipped, and why.

## How a job is scored

| Part | Weight |
|---|---|
| Technical skills | 30% |
| Relevant experience | 25% |
| Job responsibilities | 15% |
| Seniority | 10% |
| Location and relocation | 10% |
| Salary | 10% |

You can change these weights. The score comes mainly from fixed rules plus meaning-based
text comparison (embeddings), not from the AI's opinion. The AI adds explanations.

The "interview likelihood" is labelled as an **estimate**, not a prediction.

## The five visa categories

1. **Explicit sponsorship available**: the post clearly says so.
2. **Sponsorship potentially available**: positive signals, but not explicit.
3. **EU work authorization required**: the post asks for existing permission to work.
4. **Sponsorship not mentioned**: the post says nothing.
5. **Not suitable**: the evidence rules it out.

Every result stores the exact quote and link it was based on. A company is **never**
treated as a sponsor just because it employs people from other countries.

## Salary: real vs estimated

- **Real** = numbers written in the job post, converted to yearly EUR.
- **Estimated** = calculated from benchmarks when the post has no salary.

They are stored separately, and every estimate lists its assumptions (tax, rent, exchange rate).

## What runs where

| Container | Job |
|---|---|
| `backend` | the API you talk to |
| `job-discovery-worker` | fetches jobs in the background |
| `scheduler` | starts searches on time and expires old jobs |
| `postgres` | stores everything (plus pgvector for AI search) |
| `redis` | the queue between the API and the workers |
| `migrate` | sets up the database tables, then stops |
| `ollama` | the local AI model (optional) |

More detail: [Architecture](../docs/architecture.md).
