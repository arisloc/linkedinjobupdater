# LinkedIn Job Alerts

Monitors one or more LinkedIn Jobs search URLs and emails you the moment a
new matching job is posted. Runs a persistent scan loop (Playwright) plus a
small dashboard (Flask) showing scan/notification history.

## Important: LinkedIn Terms of Service

Automated access to LinkedIn (including scraping search results) violates
LinkedIn's User Agreement. This project is intended for personal, low-volume
use monitoring your own job search. LinkedIn does actively detect bot-like
browsing patterns and may rate-limit or temporarily restrict the IP/account
involved. Keep the scan interval at 60+ seconds as configured by default,
avoid running many searches in tight parallel, and expect that LinkedIn's
page markup will change occasionally, requiring selector updates in
`scraper.py`. Use your own judgment about the risk to your account.

## Setup

```bash
git clone <this project>
cd linkedin-job-alerts
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium

cp .env.example .env
# edit .env: fill in SMTP_USERNAME/SMTP_PASSWORD (Gmail App Password),
# EMAIL_FROM, EMAIL_TO

# Edit searches.json with your LinkedIn Jobs search URLs and keyword filters.
```

Get a Gmail App Password: enable 2-Step Verification on your Google
account, then visit https://myaccount.google.com/apppasswords and create
one for "Mail". Use that 16-character password as `SMTP_PASSWORD` (not your
normal Google password).

### Optional: scrape while logged in

By default the scraper uses LinkedIn's logged-out "guest" job search pages,
which show a limited but usable set of results. To see more results per
search, you can supply a logged-in session:

```bash
python -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto('https://www.linkedin.com/login')
    input('Log in manually in the opened window, then press Enter here...')
    page.context.storage_state(path='storage_state.json')
    browser.close()
"
```

Then set `LINKEDIN_STORAGE_STATE_PATH=storage_state.json` in `.env`. This
raises detection risk since scraping now happens as your actual account —
weigh that against the benefit before enabling it.

## Running

```bash
# Terminal 1: the scanner
python main.py

# Terminal 2: the dashboard
python dashboard.py
# open http://localhost:8000
```

## Configuring searches

Edit `searches.json`. Example:

```json
[
  {
    "name": "SWE Intern - Seattle",
    "url": "https://www.linkedin.com/jobs/search/?keywords=Software%20Engineering%20Intern&location=Seattle",
    "include_keywords": ["intern", "software"],
    "exclude_keywords": ["senior", "staff"]
  }
]
```

- `include_keywords`: a job title must contain at least one (case-insensitive) to notify. Leave empty (`[]`) to disable this filter.
- `exclude_keywords`: a job title containing any of these is skipped, even if it matched an include keyword.
- `main.py` re-reads this file every scan cycle, so you can edit it without restarting.

## Deploying to a VPS

```bash
sudo mkdir -p /opt/linkedin-job-alerts
sudo cp -r . /opt/linkedin-job-alerts
cd /opt/linkedin-job-alerts
python -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/playwright install --with-deps chromium

sudo useradd -r -s /bin/false jobalerts
sudo chown -R jobalerts:jobalerts /opt/linkedin-job-alerts

sudo cp deploy/job-alerts.service /etc/systemd/system/
sudo cp deploy/job-alerts-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now job-alerts job-alerts-dashboard
sudo systemctl status job-alerts
```

Logs: `journalctl -u job-alerts -f`

### Docker alternative

```bash
docker build -t linkedin-job-alerts -f deploy/Dockerfile .
docker run -d --env-file .env -v $(pwd)/job_alerts.db:/app/job_alerts.db --name job-alerts linkedin-job-alerts
```

### Why not GitHub Actions?

GitHub Actions scheduled workflows have a **5-minute minimum interval**
(your requirement is 1-2 minutes) and aren't designed for continuously
running processes — each run is a fresh, short-lived container, which also
means you'd lose the SQLite dedup database between runs unless you
persist it externally (e.g. commit it back to the repo or use an external
store), adding complexity for little benefit over a small always-on VPS
(a $4-6/mo box is plenty). If you want, this project can be adapted to run
one scan per invocation with the DB in a committed artifact — ask if you'd
like that variant.

## Project structure

```
config.py       Environment variables + searches.json loading
database.py     SQLite schema and all data access
scraper.py      Playwright scraping of LinkedIn job search pages
notifier.py     SMTP email sending
main.py         Orchestration loop (run this to start monitoring)
dashboard.py    Flask dashboard (run this to view stats in a browser)
searches.json   Your saved searches + keyword filters
deploy/         systemd unit files + Dockerfile
```

## Troubleshooting

- **0 jobs checked every scan**: LinkedIn likely changed its page markup.
  Run with `headless=False` in `main.py` temporarily and inspect the page,
  then update the selectors at the top of `scraper.py`.
- **No emails arriving**: check `journalctl -u job-alerts -f` or console
  output for SMTP errors; verify the Gmail App Password and that "Less
  secure app access" isn't the issue (App Passwords bypass that entirely).
- **Dashboard shows stale data**: it reads the same SQLite file as the
  scanner and auto-refreshes every 30s; confirm both processes point at the
  same `DATABASE_PATH`.
