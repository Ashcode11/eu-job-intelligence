# Roadmap

| Phase | What | Status |
|---|---|---|
| 1 | **Foundation**: database, API, profile, job list, application tracker, Docker setup | ✅ Done |
| 2 | **Job discovery**: Greenhouse, Lever, Adzuna, Arbeitnow and RSS connectors, duplicate removal, expiry, daily schedule | ✅ Done (87 tests passing) |
| 3 | **AI agents**: CV reading, matching, visa and salary analysis, application drafts, LangGraph workflow | ✅ Done (145 tests passing) |
| 4 | **Dashboard**: Next.js web app with all pages | ✅ Done |
| 5 | **Kubernetes**: k3d cluster, Helm chart, scaling workers | 🔨 Next |
| 6 | **Monitoring and quality**: Grafana dashboards, failure tests, end-to-end tests | ⏳ |

## Job sources

| Source | Type | Notes |
|---|---|---|
| Greenhouse | public company job boards | ✅ no key needed; 12 companies preloaded |
| Lever | public company job boards | ✅ no key needed; 2 companies preloaded |
| Arbeitnow | public job API | ✅ no key needed, Germany-focused |
| Adzuna | job search API | ✅ built; needs a free key; covers DE, NL, BE, AT, FR and others (not IE, Nordics or LU) |
| RSS | any job feed | ✅ add your own |
| EURES | EU job portal | no open public API; only added if an official one is available |

## Notifications

- ✅ Dashboard alerts: high matches, visa sponsorship offers, new jobs (each sent once)
- ⏳ Email digest and Telegram alerts (Phase 6)
