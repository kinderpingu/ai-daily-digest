<div align="center">

# 📰 Daily Digest Agent

**Your personal AI newspaper, delivered every morning.**

Powered by [Hermes Agent](https://nousresearch.com/hermes/) · Built on [OpenRouter](https://openrouter.ai) · Delivered by [Resend](https://resend.com)

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![OpenRouter](https://img.shields.io/badge/OpenRouter-Free_Tier-6B4EFF?style=flat-square)](https://openrouter.ai)
[![License](https://img.shields.io/badge/License-MIT-22C55E?style=flat-square)](LICENSE)
[![Challenge](https://img.shields.io/badge/Hermes_Agent-Challenge_2026-FF6B35?style=flat-square)](https://dev.to/challenges/hermes-agent-2026-05-15)

</div>

---

Every day, this agent researches the global AI landscape, reads the most relevant available sources, spots the patterns, and sends a clean digest to your inbox. Coverage includes frontier models, research, safety, regulation, open source, infrastructure, robotics, startups and developer tools across multiple ecosystems.

It doesn't just call an LLM once. Hermes runs a real agentic loop — planning, searching, reading, reasoning — and gets smarter with every run.

---

## What it looks like

```
=== Daily Digest Agent starting — Friday, May 29 2026 ===
Hermes iteration 1/20
  Tool call: web_search → "artificial intelligence news May 29 2026" → 10 results
Hermes iteration 2/20  
  Tool call: web_fetch  → reading techcrunch.com/...
Hermes iteration 3/20
  Tool call: web_search → "Indian startup funding round May 2026" → 10 results
...
Digest saved to output/digest_Friday_May_29_2026.md
Email sent to you@gmail.com ✓
```

And in your inbox:

```
📰 Daily Digest — Friday, May 29 2026

Executive Summary
Three sentences on what actually mattered today...

## Artificial Intelligence
- Headline → one-sentence insight. [Source]

## Indian Startups  
- Headline → one-sentence insight. [Source]

Connections & Trends
What's linking these stories together...

Worth Watching
One thing to keep an eye on this week.
```

---

## Why this is different

Most "AI digest" tools are a single prompt with a list of URLs hardcoded in. This one isn't.

**Hermes drives the entire loop.** It decides what to search. It picks which articles are worth reading. It notices when results are thin and tries a different query. It knows when it has enough to write. It stops itself.

**It compounds over time.** After each run, a skill memory log is updated. After ~5 runs, Hermes starts receiving its own past patterns as context — which searches worked, which topics ran dry — and adjusts strategy on its own. The digest on day 30 is noticeably sharper than day 1.

**It can run at very low cost.** Google News RSS requires no search API key and Resend handles transactional delivery. OpenRouter's free plan currently allows 50 model requests per day, so repeated manual test runs can exhaust the daily quota.

---

## How it works

```
main.py
  └── HermesRunner              ← the agentic loop
        ├── web_search()        ← Google News RSS, no API key
        ├── web_fetch()         ← full article extraction
        └── SkillMemory         ← GEPA-style run log
  └── send_digest_email()       ← Markdown → clean HTML → inbox
```

Hermes gets a system prompt, a list of your topics, and two tools. It runs until it decides it's done — no fixed number of steps, no hardcoded structure. The loop terminates when Hermes emits `<<<DIGEST_COMPLETE>>>`.

The skill memory writes two files after every run:
- `memory/skill_log.json` — full history of every run
- `memory/learned_skills.md` — patterns Hermes has built up over time

---

## Setup

### 1. Clone & install

```bash
git clone https://github.com/your-username/daily-digest-agent
cd daily-digest-agent
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Get an OpenRouter key

Sign up at [openrouter.ai](https://openrouter.ai) — no credit card needed. Go to **Keys** and create one.

### 3. Configure local execution

```bash
cp .env.example .env
```

Fill in these five lines:

```env
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=openrouter/free
DIGEST_TOPICS=global AI news, AI research, open source AI
DELIVERY_MODE=artifact
```

For local artifact generation, no email credentials are required. Generic SMTP
delivery is also supported with `DELIVERY_MODE=smtp`.

### 5. Run

```bash
python main.py
```

Digest in your inbox in ~90 seconds.

### 5. GitHub Actions (recommended)

The repository includes `.github/workflows/daily-digest.yml`. Add these repository
Secrets under **Settings → Secrets and variables → Actions**:

```text
OPENROUTER_API_KEY   OpenRouter API key
RESEND_API_KEY       Resend API key
EMAIL_TO             email address associated with the Resend account
```

The workflow uses `DELIVERY_MODE=resend` and sends from
`onboarding@resend.dev`. With Resend's onboarding sender, the recipient must be
the email address associated with the Resend account. A verified custom domain
is needed to send to other recipients.

The workflow can be started manually and is scheduled daily at 18:00 UTC
(approximately 20:00 in Italy during daylight saving time). Generated artifacts
are retained for 7 days as a diagnostic backup.

Optional repository variables are `OPENROUTER_MODEL`, `DIGEST_TOPICS`, and
`TIMEZONE`. The default timezone is `Europe/Rome`.

### 6. Local scheduling (optional)

**Linux/Mac:**
```bash
crontab -e
# Add:
0 7 * * * cd /path/to/daily-digest-agent && .venv/bin/python main.py
```

**Windows:**
```powershell
schtasks /create /tn "DailyDigest" /tr "C:\path\to\.venv\Scripts\python.exe C:\path\to\main.py" /sc daily /st 07:00
```

---

## Configuration reference

| Variable | Description | Default |
|---|---|---|
| `OPENROUTER_API_KEY` | OpenRouter key | required |
| `OPENROUTER_MODEL` | OpenRouter model ID | `openrouter/free` |
| `DIGEST_TOPICS` | Comma-separated topics | `AI, open source, dev tools` |
| `RESEND_API_KEY` | Resend API key when using Resend | required for Resend |
| `RESEND_FROM` | Resend sender | `onboarding@resend.dev` |
| `EMAIL_TO` | Recipient | required |
| `MAX_ARTICLES_PER_TOPIC` | Stories per topic | `3` |
| `SAVE_MARKDOWN` | Save digest to `output/` | `true` |
| `DELIVERY_MODE` | `artifact`, `smtp` or `resend` | `artifact` |
| `MAX_ITERATIONS` | LLM loop limit | `16` |
| `MAX_SEARCHES` | Search tool budget | `12` |
| `MAX_FETCHES` | Article fetch budget | `18` |
| `TIMEZONE` | Timezone used for the report date | `Europe/Rome` |

---

## Stack

- **Hermes 3** (via OpenRouter free tier) — the reasoning engine
- **Python 3.10+** with `httpx` for async HTTP
- **Google News RSS** — real-time news, no API key
- **trafilatura** — article text extraction
- **Resend API** — transactional email delivery

---

## License

MIT — do whatever you want with it.

---

<div align="center">
Built for the <a href="https://dev.to/challenges/hermes-agent-2026-05-15">Hermes Agent Challenge</a> · <a href="https://dev.to">dev.to</a>
</div>
