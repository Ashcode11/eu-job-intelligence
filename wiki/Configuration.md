# Configuration

All settings live in `.env` (copy it from `.env.example`). Never commit `.env`.

| Setting | Default | What it does |
|---|---|---|
| `API_PORT` | `8081` | Port for the API on your computer |
| `POSTGRES_PORT` | `5433` | Database port on your computer |
| `REDIS_PORT` | `6380` | Redis port on your computer |
| `POSTGRES_PASSWORD` | — | Database password (set it before the first start) |
| `REDIS_PASSWORD` | — | Redis password |
| `API_KEYS` | — | Your API password(s), comma-separated |
| `CORS_ORIGINS` | `http://localhost:3001` | Websites allowed to call the API (the dashboard) |
| `RATE_LIMIT_DEFAULT` | `120/minute` | Maximum API calls per key |
| `MAX_UPLOAD_MB` | `10` | Maximum resume file size |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Where the AI model runs |
| `LLM_CHAT_MODEL` | `llama3.2:3b` | AI model for text |
| `LLM_EMBEDDING_MODEL` | `nomic-embed-text` | AI model for meaning-based search |
| `JOB_EXPIRY_DAYS` | `21` | Mark a job expired if it hasn't been seen for this many days |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | empty | Optional free [Adzuna](https://developer.adzuna.com/) key. After adding it, enable the `adzuna` source |
| `LOG_JSON` | `true` | Structured JSON logs (`false` = human-readable) |

## Ports already in use?

Change `API_PORT`, `POSTGRES_PORT` or `REDIS_PORT`, then run `docker compose up -d`.
If you change the database or Redis port, update `DATABASE_URL` / `REDIS_URL` in `.env` too.

## Picking an AI model

| Your computer's free RAM | Suggested model |
|---|---|
| 6–8 GB | `llama3.2:3b` |
| 12–16 GB | `qwen2.5:7b` or `llama3.1:8b` |
| NVIDIA GPU with 8 GB+ | any 7–8B model, much faster |

## Important: the database password

Postgres saves the password the **first** time it starts. Changing `POSTGRES_PASSWORD`
later will not work unless you reset the data with `docker compose down -v`, which deletes everything.
