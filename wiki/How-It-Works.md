# How It Works

> **Status:** all six agents and the coordinator work today. The web dashboard comes next.
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

## One pipeline run, step by step

| Step | What happens | Uses AI? |
|---|---|---|
| Discover | Fetch new jobs (see below) | No |
| Select | Pick jobs that are new or changed. Unchanged jobs are skipped | No |
| Embed | Turn your profile and each new job into vectors for meaning-based matching | Only if Ollama runs |
| Match | List the skills each job asks for | No |
| Visa | Classify the visa stance with evidence | Only for unclear wording |
| Salary | Advertised salary in EUR, estimates, take-home pay, savings | No |
| Rank | Final score, reasons, interview-likelihood estimate | No |
| Notify | Dashboard alerts for high matches and sponsorship offers | No |

Every step is logged (`GET /api/v1/agents/summary`). If one job fails, the others continue.
If Ollama is not running, the pipeline still completes.

## How job discovery works

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

You can change these weights. The score comes from fixed rules plus, when Ollama runs,
meaning-based text comparison (embeddings). The AI never decides the score.

Hard limits:
- If you need sponsorship and the post requires existing EU work authorization, the score
  is capped at 35 and the job is not recommended.
- If the post requires a specific citizenship or a security clearance, the score is capped
  at 20.

If you haven't said whether you need sponsorship, nothing is capped. The reasons list
reminds you to fill it in.

The "interview likelihood" is labelled as an **estimate**, not a prediction.

## The five visa categories

1. **Explicit sponsorship available**: the post clearly says so.
2. **Sponsorship potentially available**: positive signals, but not explicit.
3. **EU work authorization required**: the post asks for existing permission to work.
4. **Sponsorship not mentioned**: the post says nothing.
5. **Not suitable**: the evidence rules it out.

Every result stores the exact quote and link it was based on. The AI is only asked when the
text mentions visas in words the rules don't recognise. Its answer is thrown away unless
the sentence it quotes really appears in the job post. Each visa result also lists the
official work-permit routes for that country (for example EU Blue Card, or Highly Skilled
Migrant in the Netherlands). A company is **never**
treated as a sponsor just because it employs people from other countries.

## Salary: real vs estimated

- **Real** = numbers written in the job post, converted to yearly EUR.
- **Estimated** = calculated from benchmarks when the post has no salary.

They are stored separately, and every estimate lists its assumptions (tax, rent, exchange rate).
Whether a job meets your minimum is decided only from a **real** salary, never an estimate.
The reference numbers are rough and editable in `data/salary_reference.json`.

## What runs where

| Container | Job |
|---|---|
| `backend` | the API you talk to |
| `job-discovery-worker` | fetches jobs in the background |
| `scheduler` | starts searches on time and expires old jobs |
| `agent-orchestrator` | runs the pipeline (all agents in order) |
| `matching-worker` | reads uploaded CVs |
| `visa-worker` | re-checks visa results when needed |
| `application-worker` | writes application drafts |
| `postgres` | stores everything (plus pgvector for AI search) |
| `redis` | the queue between the API and the workers |
| `migrate` | sets up the database tables, then stops |
| `ollama` | the local AI model (optional) |

More detail: [Architecture](../docs/architecture.md).
