# Getting Started

## What you need

| Item | Why |
|---|---|
| Docker Desktop | runs the database, API and workers |
| 4 GB memory for Docker | minimum for the base system |
| Ollama (optional, for the AI agents) | runs the AI model locally, for free |

On a Mac with Apple Silicon, install Ollama directly on the Mac (not in Docker) so it
can use the GPU.

## Step 1: Download

```bash
git clone https://github.com/Ashcode11/eu-job-intelligence.git
cd eu-job-intelligence
```

## Step 2: Create your settings

```bash
cp .env.example .env
```

Open `.env` and replace every `CHANGE_ME`. To generate a strong random value:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

The value of `API_KEYS` is your password for the API. Keep it safe.

## Step 3: Start

```bash
docker compose up -d --build
```

Check that everything is healthy:

```bash
docker compose ps
```

You should see `postgres`, `redis`, `backend`, `frontend`, `job-discovery-worker`,
`agent-orchestrator`, `matching-worker`, `visa-worker` and `application-worker` as
**healthy**, and `scheduler` as **running**.
`migrate` shows **exited (0)**. That is correct: it sets up the database once, then stops.

## Step 4: Load sample data

```bash
docker compose exec backend python -m scripts.seed
```

This loads a sample Cloud Architect profile, 16 real job sources (Greenhouse, Lever,
Arbeitnow, Adzuna) and 8 **made-up** jobs, one per country.

Real jobs are collected every day at 06:00 UTC. To collect them now, see
[Using the API](Using-the-API.md#find-new-jobs-right-now).

## Step 5: Open the dashboard

Open **http://localhost:3001** and paste your API key (the value of `API_KEYS` in `.env`).

| Page | What you do there |
|---|---|
| **Overview** | Totals, top matches, alerts, and the **Find & analyse jobs now** button |
| **Job Explorer** | Search and filter (country, visa, score, salary), sort, and save jobs |
| **Job details** | Score breakdown, matched and missing skills, visa evidence, salary and take-home |
| **Applications** | Board from Saved to Offer, with drafts to review, edit and approve, and a tailored CV to download |
| **Profile** | Your details, work authorization, countries, salary, match weights, skills and resumes |
| **Agents** | What every agent did, run history, and turning job sources on or off |

The API with interactive docs is at **http://localhost:8081/docs**.

## Optional: the local AI model

Everything works without it. With Ollama, matching also compares meaning (embeddings),
unclear visa wording is checked by the AI, and application drafts read better.

```bash
brew install ollama
ollama serve
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

## Stopping and starting

```bash
docker compose stop      # pause; your data is kept
docker compose start     # resume
docker compose down -v   # delete everything, including your data
```
