"""
dashboard.py

A small read-only Flask dashboard showing scan and notification history.
Runs as a separate process from main.py — it only reads the SQLite
database, so it can be restarted independently without affecting scanning.

Run with:  python dashboard.py
"""

from __future__ import annotations

from flask import Flask, render_template_string

from config import load_app_config
from database import Database

config = load_app_config()
db = Database(config.database_path)
app = Flask(__name__)

TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>LinkedIn Job Alerts Dashboard</title>
  <meta http-equiv="refresh" content="30">
  <style>
    body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 2rem; background: #f7f7f8; color: #1a1a1a; }
    h1 { margin-bottom: 0.25rem; }
    .subtitle { color: #666; margin-bottom: 2rem; }
    .stats { display: flex; gap: 1rem; margin-bottom: 2rem; flex-wrap: wrap; }
    .card { background: white; border-radius: 8px; padding: 1rem 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); min-width: 180px; }
    .card .value { font-size: 1.8rem; font-weight: 600; }
    .card .label { color: #666; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.03em; }
    table { width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    th, td { text-align: left; padding: 0.6rem 1rem; border-bottom: 1px solid #eee; font-size: 0.9rem; }
    th { background: #fafafa; color: #555; }
    tr:last-child td { border-bottom: none; }
    a { color: #0a66c2; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .status-sent { color: #1a7f37; }
    .status-failed { color: #cf222e; }
    h2 { margin-top: 2.5rem; }
  </style>
</head>
<body>
  <h1>LinkedIn Job Alerts</h1>
  <p class="subtitle">Auto-refreshes every 30s &middot; Last scan: {{ last_scan or "never" }}</p>

  <div class="stats">
    <div class="card"><div class="value">{{ total_checked }}</div><div class="label">Jobs checked (all time)</div></div>
    <div class="card"><div class="value">{{ total_new }}</div><div class="label">New jobs found (all time)</div></div>
    <div class="card"><div class="value">{{ total_jobs }}</div><div class="label">Jobs in database</div></div>
  </div>

  <h2>Recent scans</h2>
  <table>
    <tr><th>Time (UTC)</th><th>Search</th><th>Jobs checked</th><th>New found</th><th>Error</th></tr>
    {% for s in scans %}
    <tr>
      <td>{{ s.scan_time }}</td>
      <td>{{ s.search_name }}</td>
      <td>{{ s.jobs_checked }}</td>
      <td>{{ s.new_jobs_found }}</td>
      <td>{{ s.error or "" }}</td>
    </tr>
    {% endfor %}
  </table>

  <h2>Notification history</h2>
  <table>
    <tr><th>Sent (UTC)</th><th>Status</th><th>Title</th><th>Company</th><th>Location</th><th>Link</th></tr>
    {% for n in notifications %}
    <tr>
      <td>{{ n.sent_at }}</td>
      <td class="status-{{ n.status }}">{{ n.status }}</td>
      <td>{{ n.title }}</td>
      <td>{{ n.company }}</td>
      <td>{{ n.location }}</td>
      <td><a href="{{ n.url }}" target="_blank" rel="noopener">Open</a></td>
    </tr>
    {% endfor %}
  </table>
</body>
</html>
"""


@app.route("/")
def index() -> str:
    total_checked, total_new = db.scan_totals()
    return render_template_string(
        TEMPLATE,
        last_scan=db.last_scan_time(),
        total_checked=total_checked,
        total_new=total_new,
        total_jobs=db.total_jobs(),
        scans=db.recent_scans(limit=20),
        notifications=db.recent_notifications(limit=50),
    )


if __name__ == "__main__":
    app.run(host=config.dashboard_host, port=config.dashboard_port, debug=False)
