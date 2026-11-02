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

You should see `postgres`, `redis`, `backend` and `job-discovery-worker` as **healthy**.
`migrate` shows **exited (0)**. That is correct: it sets up the database once, then stops.

## Step 4: Load sample data

```bash
docker compose exec backend python -m scripts.seed
```

This loads a sample Cloud Architect profile and 8 **made-up** jobs, one per country.

## Step 5: Try it

Open **http://localhost:8081/docs** → click **Authorize** → paste your API key.
Try `GET /api/v1/candidate` and `GET /api/v1/jobs`.

## Optional: the local AI model

The AI agents (step 3 of the [Roadmap](Roadmap.md)) need Ollama:

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
