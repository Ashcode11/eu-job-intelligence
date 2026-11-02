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
| 3. AI agents | Matching, visa, salary and application helpers | ⏳ Next |
| 4. Dashboard | Web interface | ⏳ Planned |
| 5. Kubernetes | Run on a local Kubernetes cluster | ⏳ Planned |
| 6. Monitoring | Grafana dashboards and more tests | ⏳ Planned |

Today it collects real cloud architect jobs from 15 public job sources every morning,
removes duplicates, closes jobs that disappear, and lets you browse them and track your
applications through the API. In its first live run it checked about 3,000 postings and
kept 18 relevant ones in the target countries.

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

**4. Open the API**

Go to **http://localhost:8081/docs**, click **Authorize** and paste one of your
`API_KEYS` from `.env`. You can now try every endpoint in the browser.

> The sample jobs are made up, for testing only.

**5. Find real jobs now** (otherwise it runs automatically every day at 06:00 UTC)

In the API page, run `POST /api/v1/discovery/run` with body `{}`. Then look at
`GET /api/v1/jobs` after about a minute.

---

## Learn more

The [wiki](wiki/Home.md) explains everything in simple steps:

- [Getting Started](wiki/Getting-Started.md): setup, explained step by step
- [How It Works](wiki/How-It-Works.md): the agents, in plain words
- [Your Profile](wiki/Your-Profile.md): what to fill in and why
- [Using the API](wiki/Using-the-API.md): common tasks with copy-paste commands
- [Configuration](wiki/Configuration.md): every setting in `.env`
- [Developer Guide](wiki/Developer-Guide.md): tests, migrations, project layout
- [Roadmap](wiki/Roadmap.md) and [FAQ](wiki/FAQ.md)

Technical deep-dives: [Architecture](docs/architecture.md) · [Troubleshooting](docs/troubleshooting.md)

---

## Built with

Python · FastAPI · PostgreSQL + pgvector · Redis · Celery · LangGraph · Ollama ·
Next.js · Docker · Kubernetes (k3d) · Helm · Prometheus · Grafana

## Responsible by design

- Uses only public job APIs and feeds. It respects each site's rules and never bypasses logins or CAPTCHAs.
- Never assumes your visa status or citizenship. You tell it.
- Every visa or salary conclusion shows its evidence or its assumptions.
