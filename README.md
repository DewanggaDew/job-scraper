# 🎯 Job Scraper — Personal Job Hunting Dashboard

> Automatically scrapes LinkedIn, JobStreet, Glints, Indeed, and Kalibrr every 4 hours, scores each job against your CV using AI, and emails you the best matches. Fully hosted for free.

![Architecture](https://img.shields.io/badge/Scraper-GitHub_Actions-2088FF?logo=github-actions&logoColor=white)
![Database](https://img.shields.io/badge/Database-Supabase-3ECF8E?logo=supabase&logoColor=white)
![Dashboard](https://img.shields.io/badge/Dashboard-Vercel-000000?logo=vercel&logoColor=white)
![Email](https://img.shields.io/badge/Email-Resend-000000?logo=mail.ru&logoColor=white)

---

## ✨ Features

| Feature | Details |
|---|---|
| **5 Job Sources** | LinkedIn, JobStreet (MY/ID), Glints (SEA), Indeed (MY/ID), Kalibrr (ID) |
| **AI Match Scoring** | `sentence-transformers` semantic similarity — runs locally, free |
| **Dual CV Routing** | Auto-suggests SWE/Dev CV or PM CV per job |
| **Score Breakdown** | Skills (40%) · Seniority (25%) · Recency (20%) · Title (15%) |
| **Posting Date** | Scraped and normalised from every source |
| **Email Alerts** | Beautiful HTML email with score bars, sent via Resend |
| **Application Tracker** | Kanban + list view — Saved → Applied → Interview → Offer |
| **Deduplication** | Same job on two platforms = one entry |
| **Free Hosting** | GitHub Actions + Supabase + Vercel = $0/month |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────┐
│  GitHub Actions  (free, runs every 4 hours)      │
│  ① Scrape all 5 job boards via Playwright        │
│  ② Score each job against your 2 CVs (AI)       │
│  ③ Deduplicate & save to Supabase                │
│  ④ Email strong matches via Resend               │
└───────────────────┬─────────────────────────────┘
                    │ writes
                    ▼
┌─────────────────────────────────────────────────┐
│  Supabase  (free 500 MB PostgreSQL)             │
│  jobs · cv_profiles · scrape_runs               │
└───────────────────┬─────────────────────────────┘
                    │ reads / writes
                    ▼
┌─────────────────────────────────────────────────┐
│  Vercel  (free hobby tier)                      │
│  Next.js dashboard — browse, filter, track       │
└─────────────────────────────────────────────────┘
```

---

## 📋 Prerequisites

- [GitHub](https://github.com) account (free)
- [Supabase](https://supabase.com) account (free)
- [Vercel](https://vercel.com) account (free)
- [Resend](https://resend.com) account (free — 100 emails/day)
- Python 3.11+ (for local testing only — Actions handles the cloud runs)
- Node.js 18+ (for the dashboard)

---

## 🚀 Setup Guide

### Step 1 — Fork / clone this repository

```bash
git clone https://github.com/YOUR_USERNAME/job-scraper.git
cd job-scraper
```

Push it to your own GitHub repository. The GitHub Actions workflow reads from your repo's secrets.

---

### Step 2 — Set up Supabase

1. Go to [supabase.com](https://supabase.com) → **New project**
2. Give it a name (e.g. `job-scraper`) and choose a region closest to you (Singapore for SEA)
3. Once the project is ready, go to **SQL Editor** in the left sidebar
4. Open `supabase/schema.sql` from this repo, paste the entire contents, and click **Run**
   - This creates the `jobs`, `cv_profiles`, and `scrape_runs` tables
   - It also seeds your CV profile data so scoring works from day one
5. Go to **Project Settings → API** and note down:
   - **Project URL** (looks like `https://xyzabc.supabase.co`)
   - **anon / public key** (for the dashboard)
   - **service_role key** (for the GitHub Actions scraper — keep this secret!)

---

### Step 3 — Upload your CVs

Place your PDF CVs in `scraper/cv/`:

```
scraper/cv/
├── swe_cv.pdf    ← your Software Engineer / Developer CV
└── pm_cv.pdf     ← your Product Manager CV
```

Commit and push these files. The scraper will parse them automatically on each run to enrich the skill matching.

> **Note:** If you don't upload PDFs, the scraper falls back to the skills listed in `scraper/config.yaml` — which are already pre-filled with your profile from your CVs.

---

### Step 4 — Configure your preferences (optional)

Open `scraper/config.yaml` — it's already pre-configured with your preferences from LinkedIn:

```yaml
job_preferences:
  titles:
    - "Software Engineer"
    - "Web Developer"
    - "Product Manager"
    # ... add or remove titles as needed

  locations:
    on_site:
      - "Selangor, Malaysia"
      - "Jakarta, Indonesia"
    remote:
      - "Malaysia"
      - "Indonesia"
```

You can also tune the scoring weights and notification threshold here.

---

### Step 5 — Set up GitHub Secrets

Go to your GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**

Add each of these:

| Secret Name | Where to find it | Required? |
|---|---|---|
| `SUPABASE_URL` | Supabase → Project Settings → API → Project URL | ✅ Yes |
| `SUPABASE_KEY` | Supabase → Project Settings → API → **service_role** key | ✅ Yes |
| `RESEND_API_KEY` | resend.com → API Keys | ✅ Yes |
| `NOTIFY_EMAIL` | The email address to send alerts to | ✅ Yes |
| `LINKEDIN_EMAIL` | Your LinkedIn login email | ✅ Yes |
| `LINKEDIN_PASSWORD` | Your LinkedIn password | ✅ Yes |
| `LINKEDIN_COOKIES` | (Optional) JSON cookies for Playwright fallback | ❌ Optional |
| `DASHBOARD_URL` | Your Vercel dashboard URL (add after Step 7) | ❌ Optional |

> ⚠️ **Security note:** Never commit these values to the repo. GitHub Secrets are encrypted at rest and only exposed to Actions workflows in your own repo.

---

### Step 6 — Get your Resend API key

1. Go to [resend.com](https://resend.com) → Sign up (free)
2. Go to **API Keys** → **Create API Key**
3. Copy the key and add it as `RESEND_API_KEY` in GitHub Secrets
4. Add `NOTIFY_EMAIL` as the email address you want alerts sent to

> **Free tier:** 100 emails/day — with 6 scrape runs/day you'll never hit the limit.

---

### Step 7 — Deploy the dashboard to Vercel

1. Go to [vercel.com](https://vercel.com) → **Add New Project**
2. Import your GitHub repository
3. Set the **Root Directory** to `dashboard`
4. Under **Environment Variables**, add:
   ```
   NEXT_PUBLIC_SUPABASE_URL     = https://your-project-ref.supabase.co
   NEXT_PUBLIC_SUPABASE_ANON_KEY = your-supabase-anon-key
   ```
   _(Use the **anon** key here, not the service_role key)_
5. Click **Deploy**
6. Once deployed, copy the URL (e.g. `https://job-scraper-xyz.vercel.app`) and add it as `DASHBOARD_URL` in GitHub Secrets so it appears in email notifications

---

### Step 8 — Trigger your first scrape

Go to your GitHub repo → **Actions** tab → **Job Scraper** workflow → **Run workflow** → **Run workflow**

Watch the logs in real time. A successful run looks like:

```
=================================================================
  🚀  Job Scraper  —  2025-01-15 08:00 UTC
=================================================================

📄  Loading config …
📋  Parsing CV profiles …
  [SWE CV] PDF parsed — 2847 chars, +3 extra skills
  [PM  CV] PDF parsed — 2531 chars, +2 extra skills

🗄️   Fetching existing job IDs from Supabase …
  0 jobs already in database.

🔍  Running scrapers …
  ── LinkedIn ──────────────────────────────────────────
  [Linkedin]  Authenticating with linkedin-api …
  [Linkedin]  Found 18 jobs for 'Software Engineer' in 'Selangor, Malaysia'
  ✅  Linkedin: 42 jobs scraped

  ── Jobstreet ─────────────────────────────────────────
  ✅  Jobstreet: 38 jobs scraped
  ...

🏆  Scoring 87 new jobs …
  [  1/ 87] 🟢  91.4  Senior Software Engineer @ Grab           ...
  [  2/ 87] 🟢  88.2  Full Stack Developer @ Shopee             ...
  [  3/ 87] 🟡  67.8  Product Manager @ GoTo                    ...
  ...

📧  Sending email for 12 matches …
  ✅  Email sent → dewangga.indera@gmail.com  (8 strong, 4 decent)

=================================================================
  📊  Run Summary
=================================================================
  Total scraped   : 194
  New jobs        : 87
  Duplicates      : 107
  Strong matches  : 8
  Decent matches  : 4
  Low matches     : 75
  Email sent      : Yes ✅
  Elapsed         : 312.4s
=================================================================
```

---

### Step 9 — Open your dashboard

Navigate to your Vercel URL. You should see all scraped jobs ranked by match score.

---

## 📊 Dashboard Features

### Job Feed (`/`)
- Jobs sorted by match score (highest first) by default
- Filter by: Source · Match Label · Status · Location Type · Free text search
- Sort by: Best Match · Newest Posted · Recently Scraped · Company A–Z
- Stats bar: Total · Strong · Decent · New Today · Applied · Interviewing
- Score mini-bars on each card (Skills · Seniority · Recency · Title)

### Job Detail (`/jobs/[id]`)
- Full score breakdown with visual progress bars
- Which CV to use (SWE or PM), with an explanation per dimension
- One-click Apply button (Easy Apply highlighted with ⚡)
- Application status selector + notes field
- Full job description (expandable)

### Tracker (`/tracker`)
- **Kanban view** — drag-free pipeline: Saved → Applied → Interviewing → Offer → Rejected
- **List view** — sortable table with quick inline status updates
- **Conversion funnel** — interview rate and offer rate automatically calculated

---

## 🧠 Scoring Algorithm

Every job is scored against both CVs and the better score is used:

```
Final Score (0–100) =
    Skills Score    × 40%   (semantic similarity via sentence-transformers)
  + Seniority Score × 25%   (entry/mid/senior level alignment)
  + Recency Score   × 20%   (today=100, 30+ days=0)
  + Title Score     × 15%   (vs your preferred titles)
```

| Label | Score Range | Meaning |
|---|---|---|
| 🟢 Strong | 75 – 100 | High chance — apply ASAP |
| 🟡 Decent | 50 – 74 | Worth reviewing |
| 🔴 Low | 0 – 49 | Unlikely fit |

The `sentence-transformers` model (`all-MiniLM-L6-v2`, ~80 MB) runs inside GitHub Actions and is **cached between runs** so it only downloads once.

---

## 🔧 Local Development

### Run the scraper locally

```bash
cd scraper

# Create a .env file with your secrets
cp /dev/null .env
echo "SUPABASE_URL=https://your-project.supabase.co" >> .env
echo "SUPABASE_KEY=your-service-role-key" >> .env
echo "LINKEDIN_EMAIL=your@email.com" >> .env
echo "LINKEDIN_PASSWORD=yourpassword" >> .env
echo "RESEND_API_KEY=re_xxxx" >> .env
echo "NOTIFY_EMAIL=your@email.com" >> .env

# Install dependencies
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
playwright install chromium

# Run
python main.py
```

### Run the dashboard locally

```bash
cd dashboard

# Install dependencies
npm install

# Copy and fill in your env file
cp .env.local.example .env.local
# Edit .env.local with your Supabase URL and anon key

# Start dev server
npm run dev
# Open http://localhost:3000
```

---

## 🔄 Scraping Schedule

The GitHub Actions cron runs at:

| UTC | Malaysia (MYT, UTC+8) | Indonesia (WIB, UTC+7) |
|---|---|---|
| 00:00 | 08:00 | 07:00 |
| 04:00 | 12:00 | 11:00 |
| 08:00 | 16:00 | 15:00 |
| 12:00 | 20:00 | 19:00 |
| 16:00 | 00:00 | 23:00 |
| 20:00 | 04:00 | 03:00 |

You'll get email alerts at local morning, noon, and evening — catching freshly posted jobs quickly.

---

## 🛠️ Troubleshooting

### Scraper returns 0 jobs from LinkedIn
LinkedIn may have updated their internal API. Try:
1. Go to **Actions → Job Scraper → Run workflow** to trigger a manual run with fresh cookies
2. Export your LinkedIn session cookies from a browser (use a browser extension like "EditThisCookie"), serialize them as JSON, and add as `LINKEDIN_COOKIES` secret
3. The scraper will automatically fall back to Playwright mode using those cookies

### Playwright times out on a scraper
Some sites do A/B tests that change their DOM structure. The scrapers use multiple fallback selectors but may occasionally miss new layouts. You can:
1. Check the **Playwright trace** artifact uploaded on failure in the Actions run
2. Update the relevant CSS selectors in `scraper/scrapers/<source>.py`

### Dashboard shows no data
1. Confirm the Supabase schema was run (`supabase/schema.sql`)
2. Check that `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY` are set correctly in Vercel
3. Verify the `jobs` table exists in Supabase → Table Editor

### Email not sending
1. Verify `RESEND_API_KEY` is correct in GitHub Secrets
2. Check that `NOTIFY_EMAIL` is set
3. On Resend's free tier you can only send to the email address you signed up with (until you verify a domain)

---

## 📁 Project Structure

```
job-scraper/
├── .github/workflows/
│   └── scrape.yml              # Cron job — runs every 4 hours
│
├── scraper/                    # Python package (runs in GitHub Actions)
│   ├── main.py                 # Orchestrator
│   ├── config.yaml             # YOUR preferences, weights, CV data
│   ├── requirements.txt
│   ├── cv/
│   │   ├── swe_cv.pdf          # ← Place your SWE CV here
│   │   └── pm_cv.pdf           # ← Place your PM CV here
│   ├── core/
│   │   ├── models.py           # Pydantic data models
│   │   ├── database.py         # Supabase client + queries
│   │   ├── date_parser.py      # Normalises "2 days ago" → datetime
│   │   ├── deduplicator.py     # SHA-256 job ID hashing
│   │   └── notifier.py         # Resend HTML email builder
│   ├── ranking/
│   │   ├── cv_parser.py        # PDF + config → CVProfile
│   │   ├── job_parser.py       # Job description → skills, seniority
│   │   ├── embeddings.py       # sentence-transformers wrapper
│   │   └── scorer.py           # Weighted scoring engine
│   └── scrapers/
│       ├── base.py             # Abstract base with Playwright helpers
│       ├── linkedin.py         # linkedin-api + Playwright fallback
│       ├── jobstreet.py        # JobStreet MY + ID
│       ├── glints.py           # Glints MY + ID
│       ├── indeed.py           # Indeed MY + ID
│       └── kalibrr.py          # Kalibrr ID
│
├── dashboard/                  # Next.js 14 app (deployed to Vercel)
│   ├── app/
│   │   ├── page.tsx            # Job feed with filters + stats
│   │   ├── jobs/[id]/page.tsx  # Job detail + score breakdown
│   │   └── tracker/page.tsx    # Kanban application pipeline
│   ├── lib/supabase.ts         # Supabase client
│   ├── types/index.ts          # TypeScript types + helper functions
│   └── package.json
│
└── supabase/
    └── schema.sql              # Run this first in Supabase SQL Editor
```

---

## 💡 Tips

- **Increase `max_jobs_per_source`** in `config.yaml` to scrape more jobs per run (default: 50)
- **Adjust scoring weights** to prioritise what matters to you — e.g. raise `recency` if you want the freshest postings at the top
- **Add new titles** to `config.yaml` → `job_preferences.titles` as your preferences change
- **Export jobs to CSV** by running a query in Supabase SQL Editor:
  ```sql
  COPY (SELECT title, company, location, source, url, match_score, match_label, suggested_cv, posted_at FROM jobs ORDER BY match_score DESC) TO STDOUT WITH CSV HEADER;
  ```

---

## 📄 License

MIT — personal use. Do not use to spam job boards or violate their terms of service.