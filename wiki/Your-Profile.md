# Your Profile

The agents can only be as good as your profile. Fill these in once and update them any time.

## What the system will never guess

These start **empty** on purpose. The visa agent needs them, and it will not assume them:

| Field | Example |
|---|---|
| `citizenship` | `["IN"]` (two-letter country codes) |
| `has_eu_work_authorization` | `true` / `false` |
| `requires_visa_sponsorship` | `true` / `false` |
| `open_to_relocation` | `true` / `false` |
| `current_country` | `"IN"` |
| `min_salary_eur` | `80000` |

`GET /api/v1/candidate` shows a `profile_completeness` list of what is still missing.

## Update your profile

```bash
curl -X PATCH -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  http://localhost:8081/api/v1/candidate \
  -d '{"full_name":"Your Name","citizenship":["IN"],"has_eu_work_authorization":false,
       "requires_visa_sponsorship":true,"open_to_relocation":true,"min_salary_eur":80000}'
```

Only the fields you send are changed.

## Skills

```bash
# add
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  http://localhost:8081/api/v1/candidate/skills -d '{"name":"ArgoCD","proficiency":3}'
# list
curl -H "X-API-Key: $KEY" http://localhost:8081/api/v1/candidate/skills
```

Proficiency runs from 1 (basic) to 5 (expert). Skill names are unique, ignoring upper/lower case.

## Resumes

```bash
curl -H "X-API-Key: $KEY" -F file=@my-cv.pdf -F version_label=main \
  http://localhost:8081/api/v1/candidate/resumes
```

- PDF or DOCX only, checked by the file's real content rather than its name.
- Maximum 10 MB (change with `MAX_UPLOAD_MB`).
- You can keep several versions. One is marked **primary**.

## Countries and roles

The sample profile targets DE, NL, IE, SE, DK, FI, BE and LU, plus 10 cloud architect roles.
Add any country with its two-letter code, for example `"AT"` for Austria.

## Match weights

```bash
curl -X PATCH -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  http://localhost:8081/api/v1/candidate -d '{"match_weights":{"technical_skills":0.35,
  "experience":0.25,"responsibilities":0.10,"seniority":0.10,"location":0.10,"compensation":0.10}}'
```

The weights must add up to 1.0.
