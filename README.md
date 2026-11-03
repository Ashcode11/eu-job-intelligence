# EU Job Intelligence

**A personal AI job-search assistant for European cloud jobs that runs on your own computer.**

It is being built to:

1. **Find** cloud architect jobs across Europe (Germany, Netherlands, Ireland, the Nordics, Benelux and more).
2. **Score** each job against your skills and experience.
3. **Check visa sponsorship**, but only from evidence written in the job post, never from guesses.
4. **Compare salaries**, keeping real advertised numbers separate from estimates.
5. **Help you apply** by drafting CVs, cover letters and interview notes.

**You stay in control.** It never applies, sends messages or changes your profile on its own.
**It's free to run.** It uses local AI models (Ollama), so no paid AI API is needed.

---

## Where it stands today

| Step | What it does | Status |
|---|---|---|
| 1. Foundation | Database, API, profile, job list, application tracker | ✅ Working and tested |
| 2. Job discovery | Collect jobs from public job boards every day | ✅ Working and tested |
| 3. AI agents | CV reading, matching, visa, salary and application helpers | ✅ Working and tested |
| 4. Dashboard | Web interface | ✅ Working and tested |
| 5. Kubernetes | Run on a local Kubernetes cluster (k3d + Helm) | ✅ Working and tested |
| 6. Monitoring | Grafana dashboards, email/Telegram alerts, more tests | ⏳ Next |

Today, every morning it:

- collects cloud architect jobs from 15 public job sources and removes duplicates
- scores each job from 0 to 100 against your profile, with reasons for and against
- reads the post for visa sponsorship and saves the exact sentence as evidence
- converts salaries to yearly EUR and estimates take-home pay and savings
- alerts you about high matches and sponsorship offers

On request it reads your CV, suggests skills (added only when you approve) and drafts a
tailored CV, cover letter, recruiter message and interview prep. Drafts are never sent.

Everything works **without** an AI model. With [Ollama](wiki/Getting-Started.md#optional-the-local-ai-model)
running, it also uses meaning-based matching and writes better drafts.

---

## Start it in 5 minutes

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/).

**1. Get the code and create your settings file**

```bash
git clone https://github.com/Ashcode11/eu-job-intelligence.git
```

```bash
cd eu-job-intelligence && cp .env.example .env
```

Open `.env` and replace every `CHANGE_ME` with your own password or key.

**2. Start everything**

```bash
docker compose up -d --build
```

**3. Load the sample profile, the job sources and sample jobs**

```bash
docker compose exec backend python -m scripts.seed
```

**4. Open the dashboard**

Go to **http://localhost:3001** and paste one of your `API_KEYS` from `.env`. The key is
kept only in your browser.

You can also use the API directly at **http://localhost:8081/docs**: click **Authorize** and
paste the same key.

> The sample jobs are made up, for testing only.

**5. Find real jobs now** (otherwise it runs automatically every day at 06:00 UTC)

Click **Find & analyse jobs now** on the dashboard. After about a minute the Job Explorer
lists jobs ranked by match score.

**6. Tell it about you.** Open **Profile** in the dashboard and fill in your visa situation,
minimum salary and CV (see [Your Profile](wiki/Your-Profile.md)). Until then, visa and salary fit stay "unknown".

---

## Learn more

The [wiki](wiki/Home.md) explains everything in simple steps:

- [Getting Started](wiki/Getting-Started.md): setup, explained step by step
- [How It Works](wiki/How-It-Works.md): the agents, in plain words
- [Your Profile](wiki/Your-Profile.md): what to fill in and why
- [Using the API](wiki/Using-the-API.md): common tasks with copy-paste commands
- [Configuration](wiki/Configuration.md): every setting in `.env`
- [Developer Guide](wiki/Developer-Guide.md): tests, migrations, project layout
- [Kubernetes](wiki/Kubernetes.md): run it on a local k3d cluster with Helm
- [Roadmap](wiki/Roadmap.md) and [FAQ](wiki/FAQ.md)

Operating it: **[Runbook](docs/runbook.md)** (daily checks, routine tasks, incident playbooks)

Technical deep-dives: [Architecture](docs/architecture.md) · [Troubleshooting](docs/troubleshooting.md)

---

## Built with

Python · FastAPI · PostgreSQL + pgvector · Redis · Celery · LangGraph · Ollama ·
Next.js · Docker · Kubernetes (k3d) · Helm · Prometheus · Grafana

## Responsible by design

- Uses only public job APIs and feeds. It respects each site's rules and never bypasses logins or CAPTCHAs.
- Never assumes your visa status or citizenship. You tell it.
- Every visa or salary conclusion shows its evidence or its assumptions.
