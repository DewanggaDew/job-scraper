# Job Scraper

Scrapes LinkedIn, JobStreet, Glints, Indeed, and Kalibrr every 4 hours, scores each job against your CV with a local AI model, and emails the best matches. Runs entirely on free tiers (GitHub Actions + Supabase + Vercel).

## Features

| Feature | Details |
|---|---|
| 5 job sources | LinkedIn, JobStreet (MY/ID), Glints (SEA), Indeed (MY/ID), Kalibrr (ID) |
| AI match scoring | `sentence-transformers` semantic similarity, runs locally |
| Dual CV routing | Auto-suggests SWE/Dev CV or PM CV per job |
| Score breakdown | Skills 40% · Seniority 25% · Recency 20% · Title 15% |
| Email alerts | HTML email with score bars, sent via Resend |
| Application tracker | Kanban + list view: Saved → Applied → Interview → Offer |
| Deduplication | Same job across platforms collapses to one entry |

## Architecture

```
GitHub Actions (every 4 hours)
  1. Scrape 5 job boards via Playwright
  2. Score each job against your 2 CVs
  3. Deduplicate and save to Supabase
  4. Email strong matches via Resend
        │ writes
        ▼
Supabase (free PostgreSQL)
  jobs · cv_profiles · scrape_runs
        │ reads / writes
        ▼
Vercel (Next.js dashboard — browse, filter, track)
```

## Prerequisites

- GitHub, Supabase, Vercel, and Resend accounts (all free)
- Python 3.11+ (local testing only)
- Node.js 18+ (dashboard)

## Setup

### 1. Clone and push to your own repo

```bash
git clone https://github.com/YOUR_USERNAME/job-scraper.git
cd job-scraper
```

The GitHub Actions workflow reads from your repo's secrets, so push to your own GitHub repository.

### 2. Set up Supabase

1. Create a new project at [supabase.com](https://supabase.com) (pick the region closest to you).
2. In **SQL Editor**, paste and run `supabase/schema.sql`. This creates the `jobs`, `cv_profiles`, and `scrape_runs` tables and seeds your CV profile.
3. From **Project Settings → API**, note the **Project URL**, **anon key** (dashboard), and **service_role key** (scraper — keep secret).

### 3. Upload your CVs

```
scraper/cv/
├── swe_cv.pdf    # Software Engineer / Developer CV
└── pm_cv.pdf     # Product Manager CV
```

Commit and push them; the scraper parses them on each run. If omitted, scoring falls back to the skills in `scraper/config.yaml`.

### 4. Configure preferences (optional)

Edit `scraper/config.yaml` to adjust job titles, locations, scoring weights, and the notification threshold:

```yaml
job_preferences:
  titles:
    - "Software Engineer"
    - "Web Developer"
    - "Product Manager"
  locations:
    on_site:
      - "Selangor, Malaysia"
      - "Jakarta, Indonesia"
    remote:
      - "Malaysia"
      - "Indonesia"
```

### 5. Add GitHub Secrets

Repo → **Settings → Secrets and variables → Actions**:

| Secret | Source | Required |
|---|---|---|
| `SUPABASE_URL` | Project Settings → API → Project URL | Yes |
| `SUPABASE_KEY` | Project Settings → API → service_role key | Yes |
| `RESEND_API_KEY` | resend.com → API Keys | Yes |
| `NOTIFY_EMAIL` | Address to send alerts to | Yes |
| `LINKEDIN_EMAIL` | LinkedIn login email | Yes |
| `LINKEDIN_PASSWORD` | LinkedIn password | Yes |
| `LINKEDIN_COOKIES` | JSON cookies for Playwright fallback | No |
| `DASHBOARD_URL` | Vercel dashboard URL (add after step 6) | No |

### 6. Deploy the dashboard to Vercel

1. Import your repo at [vercel.com](https://vercel.com).
2. Set **Root Directory** to `dashboard`.
3. Add environment variables (use the **anon** key, not service_role):
   ```
   NEXT_PUBLIC_SUPABASE_URL      = https://your-project-ref.supabase.co
   NEXT_PUBLIC_SUPABASE_ANON_KEY = your-supabase-anon-key
   ```
4. Deploy, then add the resulting URL as `DASHBOARD_URL` in GitHub Secrets so it appears in emails.

### 7. Run the first scrape

Repo → **Actions → Job Scraper → Run workflow**. Then open your Vercel URL to see jobs ranked by match score.

## Dashboard

- **Job Feed (`/`)** — jobs sorted by match score; filter by source, label, status, location, or text; stats bar; per-card score mini-bars.
- **Job Detail (`/jobs/[id]`)** — full score breakdown, suggested CV with per-dimension explanation, apply button, status selector + notes, expandable description.
- **Tracker (`/tracker`)** — Kanban pipeline (Saved → Applied → Interviewing → Offer → Rejected), sortable list view, and an auto-calculated conversion funnel.

## Scoring

Each job is scored against both CVs; the higher score wins:

```
Final Score (0–100) =
    Skills    × 40%   (semantic similarity, sentence-transformers)
  + Seniority × 25%   (level alignment)
  + Recency   × 20%   (today = 100, 30+ days = 0)
  + Title     × 15%   (vs preferred titles)
```

| Label | Range | Meaning |
|---|---|---|
| Strong | 75–100 | Apply ASAP |
| Decent | 50–74 | Worth reviewing |
| Low | 0–49 | Unlikely fit |

The model (`all-MiniLM-L6-v2`, ~80 MB) runs inside Actions and is cached between runs.

## Local development

Scraper:

```bash
cd scraper
# Create .env with: SUPABASE_URL, SUPABASE_KEY, LINKEDIN_EMAIL,
#                   LINKEDIN_PASSWORD, RESEND_API_KEY, NOTIFY_EMAIL
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
playwright install chromium
python main.py
```

Dashboard:

```bash
cd dashboard
npm install
cp .env.local.example .env.local   # fill in Supabase URL + anon key
npm run dev                          # http://localhost:3000
```

## Schedule

The cron runs every 4 hours (00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC), covering local morning, noon, and evening for Malaysia (UTC+8) and Indonesia (UTC+7).

## Troubleshooting

- **LinkedIn returns 0 jobs** — LinkedIn likely changed its internal API. Export your session cookies as JSON, add them as `LINKEDIN_COOKIES`, and the scraper falls back to Playwright.
- **Playwright times out** — sites A/B-test their DOM. Check the Playwright trace artifact on the failed run and update selectors in `scraper/scrapers/<source>.py`.
- **Dashboard shows no data** — confirm `schema.sql` ran, the `jobs` table exists, and the Vercel env vars are correct.
- **Email not sending** — verify `RESEND_API_KEY` and `NOTIFY_EMAIL`. On Resend's free tier you can only send to your signup address until you verify a domain.

## Project structure

```
job-scraper/
├── .github/workflows/scrape.yml   # Cron — every 4 hours
├── scraper/                       # Python package (runs in Actions)
│   ├── main.py                    # Orchestrator
│   ├── config.yaml                # Preferences, weights, CV data
│   ├── cv/                        # swe_cv.pdf, pm_cv.pdf
│   ├── core/                      # models, database, date_parser, deduplicator, notifier
│   ├── ranking/                   # cv_parser, job_parser, embeddings, scorer
│   └── scrapers/                  # base + linkedin, jobstreet, glints, indeed, kalibrr
├── dashboard/                     # Next.js app (Vercel)
│   ├── app/                       # page.tsx, jobs/[id]/page.tsx, tracker/page.tsx
│   ├── lib/supabase.ts
│   └── types/index.ts
└── supabase/schema.sql            # Run first in Supabase SQL Editor
```

## Tips

- Raise `max_jobs_per_source` in `config.yaml` to scrape more per run (default 50).
- Adjust scoring weights to match your priorities.
- Export to CSV from the Supabase SQL Editor:
  ```sql
  COPY (SELECT title, company, location, source, url, match_score, match_label, suggested_cv, posted_at
        FROM jobs ORDER BY match_score DESC) TO STDOUT WITH CSV HEADER;
  ```

## License

MIT — personal use. Do not use to spam job boards or violate their terms of service.
