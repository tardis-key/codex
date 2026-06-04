#!/usr/bin/env python3
"""
Daily Briefing — posts to tardis-key/codex repo
1. Reads "坐骑" note from Apple Notes
2. Checks vehicle insurance/maintenance deadlines
3. Fetches verl repo PRs/issues
4. Saves structured markdown to repo + creates GitHub Issue
"""

import json
import os
import re
import ssl
import subprocess
import sys
import urllib.request
from datetime import datetime, date, timedelta

# -- Paths ----------------------------------------------------------
REPO_DIR = os.path.expanduser("~/Documents/GitHub/codex")
BRIEFINGS_DIR = os.path.join(REPO_DIR, "briefings")
DATA_DIR = os.path.join(REPO_DIR, "data")
TOKEN_FILE = os.path.expanduser("~/.codex/github_token")

# -- Config ---------------------------------------------------------
GITHUB_REPO = "verl-project/verl"
OWNER_REPO = "tardis-key/codex"
DAYS_LOOKAHEAD = 30
PR_ISSUE_HOURS = 24

# -- Maintenance intervals (months) ---------------------------------
MAINTENANCE_INTERVALS = {
    "机油": 6, "换机油": 6,
    "保养": 12, "大保养": 12,
    "刹车油": 24, "冷却液": 12,
    "雨刷": 12, "电池": 12,
}

def classify_item(desc):
    if "险" in desc:
        return ("insurance", None)
    for kw, months in MAINTENANCE_INTERVALS.items():
        if kw in desc:
            return ("maintenance", months)
    return ("maintenance", 12)

# -- GitHub helpers --------------------------------------------------
def get_token():
    token = os.environ.get("CODEX_GITHUB_TOKEN", "")
    if not token and os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            token = f.read().strip()
    return token

def gh_api(method, path, body=None):
    token = get_token()
    if not token:
        return None
    url = f"https://api.github.com{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {token}",
        "User-Agent": "Codex-Daily-Briefing/1.0",
        "Accept": "application/vnd.github+json",
    }, method=method)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        return json.loads(resp.read().decode())

def fetch_json(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Codex-Daily-Briefing/1.0",
        "Accept": "application/vnd.github+json"
    })
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        return json.loads(resp.read().decode())

def git(*args):
    return subprocess.run(["git", "-C", REPO_DIR] + list(args),
                          capture_output=True, text=True)

# -- Read note ------------------------------------------------------
def read_note():
    result = subprocess.run(
        ["osascript", "-e",
         'tell application id "com.apple.Notes" to get body of note "坐骑"'],
        capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return result.stdout

# -- Parse -----------------------------------------------------------
def parse_note(html):
    vehicles = []
    h2_pat = re.compile(r'<h2>(.+?)</h2>')
    li_pat = re.compile(r'<li>(.+?)</li>')
    ul_pat = re.compile(r'<ul>(.+?)</ul>', re.DOTALL)
    date_pat = re.compile(r'(\d{4})\.(\d{1,2})\.(\d{1,2})')

    names = []
    for m in h2_pat.finditer(html):
        clean = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        if clean and clean != '坐骑':
            names.append(clean)

    uls = list(ul_pat.finditer(html))
    for idx, name in enumerate(names):
        section = uls[idx].group(1) if idx < len(uls) else ""
        items = []
        for m in li_pat.finditer(section):
            text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            dm = date_pat.search(text)
            d = date(int(dm[1]), int(dm[2]), int(dm[3])) if dm else None
            items.append({"desc": text, "date": d})
        vehicles.append({"vehicle": name, "items": items})
    return vehicles

# -- Consolidate -----------------------------------------------------
def consolidate(vehicles):
    superseding = {
        "大保养": ["机油", "换机油", "刹车油", "冷却液", "雨刷", "电池"],
        "保养":   ["机油", "换机油"],
    }
    for v in vehicles:
        best_date, best_subs = None, []
        for item in v["items"]:
            if not item["date"]:
                continue
            for svc, subs in superseding.items():
                if svc in item["desc"]:
                    if not best_date or item["date"] > best_date:
                        best_date, best_subs = item["date"], subs
                    break
        if not best_date:
            continue
        for item in v["items"]:
            if item["date"] and item["date"] < best_date:
                if any(kw in item["desc"] for kw in best_subs):
                    item["date"] = best_date
                    item["rebase"] = True
    return vehicles

# -- Check urgency ---------------------------------------------------
def check_dates(vehicles):
    today = date.today()
    cutoff = today + timedelta(days=DAYS_LOOKAHEAD)
    overdue, upcoming = [], []

    for v in vehicles:
        for item in v["items"]:
            if not item["date"]:
                continue
            d = item["date"]
            cat, interval = classify_item(item["desc"])
            if cat == "insurance":
                eff = d
            else:
                total = d.year * 12 + d.month + interval
                y, m = total // 12, total % 12
                if m == 0:
                    y, m = y - 1, 12
                eff = date(y, m, min(d.day, 28))

            entry = {
                "vehicle": v["vehicle"],
                "desc": item["desc"],
                "recorded": d.isoformat(),
                "effective": eff.isoformat(),
                "category": cat,
            }
            if eff < today:
                overdue.append(entry)
            elif eff <= cutoff:
                entry["days_left"] = (eff - today).days
                upcoming.append(entry)

    overdue.sort(key=lambda x: x["effective"])
    upcoming.sort(key=lambda x: x["effective"])
    return {"overdue": overdue, "upcoming": upcoming}

# -- Fetch verl -----------------------------------------------------
def fetch_verl():
    since = (datetime.now() - timedelta(hours=PR_ISSUE_HOURS)).isoformat() + "Z"
    prs, issues = [], []
    try:
        for p in fetch_json(
            f"https://api.github.com/repos/{GITHUB_REPO}/pulls?state=all&sort=created&direction=desc&per_page=15"):
            if p.get("created_at", "") >= since:
                prs.append({"number": p["number"], "title": p["title"],
                            "user": p["user"]["login"], "state": p["state"],
                            "url": p["html_url"]})
    except Exception as e:
        print(f"  Warning: PRs fetch failed: {e}", file=sys.stderr)
    try:
        for iss in fetch_json(
            f"https://api.github.com/repos/{GITHUB_REPO}/issues?state=all&sort=created&direction=desc&per_page=15"):
            if "pull_request" in iss:
                continue
            if iss.get("created_at", "") >= since:
                issues.append({"number": iss["number"], "title": iss["title"],
                               "user": iss["user"]["login"], "state": iss["state"],
                               "url": iss["html_url"]})
    except Exception as e:
        print(f"  Warning: Issues fetch failed: {e}", file=sys.stderr)
    return {"prs": prs, "issues": issues}

# -- Generate markdown -----------------------------------------------
def md_briefing(ts, alerts, gh):
    lines = [f"# 📋 Daily Briefing — {ts}", ""]

    lines.append("## 🚗 车辆提醒")
    lines.append("")
    lines.append("> 保险类：日期=到期日 ｜ 保养类：日期=上次执行日，按行业周期推算下次时间")
    lines.append("")

    if alerts["overdue"]:
        lines.append("### 🔴 需关注")
        lines.append("")
        lines.append("| 车辆 | 事项 | 记录日期 | 应于 |")
        lines.append("|------|------|----------|------|")
        for x in alerts["overdue"]:
            cat = "险" if x["category"] == "insurance" else "保"
            lines.append(f"| 🔴{cat} {x['vehicle']} | {x['desc']} | {x['recorded']} | **{x['effective']}** |")
        lines.append("")
    else:
        lines.append("### 🔴 需关注")
        lines.append("")
        lines.append("暂无")
        lines.append("")

    if alerts["upcoming"]:
        lines.append("### 🟡 即将到期")
        lines.append("")
        lines.append("| 车辆 | 事项 | 记录日期 | 到期日 | 剩余 |")
        lines.append("|------|------|----------|--------|------|")
        for x in alerts["upcoming"]:
            cat = "险" if x["category"] == "insurance" else "保"
            lines.append(f"| 🟡{cat} {x['vehicle']} | {x['desc']} | {x['recorded']} | {x['effective']} | {x['days_left']}天 |")
        lines.append("")
    else:
        lines.append("### 🟡 即将到期")
        lines.append("")
        lines.append("近期无忧")
        lines.append("")

    lines.append(f"## 🔧 verl — PR ({len(gh['prs'])}) + Issues ({len(gh['issues'])})")
    lines.append("")
    if gh["prs"]:
        lines.append("### Pull Requests")
        lines.append("")
        lines.append("| # | 标题 | 作者 | 状态 |")
        lines.append("|---|------|------|------|")
        for p in gh["prs"]:
            s = "🟢" if p["state"] == "open" else "🟣" if p["state"] == "merged" else "⚫"
            lines.append(f"| [#{p['number']}]({p['url']}) | {p['title']} | {p['user']} | {s} {p['state']} |")
        lines.append("")
    if gh["issues"]:
        lines.append("### Issues")
        lines.append("")
        lines.append("| # | 标题 | 作者 | 状态 |")
        lines.append("|---|------|------|------|")
        for iss in gh["issues"]:
            s = "🟢" if iss["state"] == "open" else "⚫"
            lines.append(f"| [#{iss['number']}]({iss['url']}) | {iss['title']} | {iss['user']} | {s} {iss['state']} |")
        lines.append("")

    lines.append("---")
    lines.append(f"*Auto-generated by Codex daily briefing at {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    return "\n".join(lines)

# -- Create GitHub Issue ---------------------------------------------
def create_issue(title, body):
    resp = gh_api("POST", f"/repos/{OWNER_REPO}/issues",
                  {"title": title, "body": body, "labels": ["daily-briefing"]})
    if resp:
        return resp.get("html_url")
    return None

# -- Main ------------------------------------------------------------
def main():
    today = date.today()
    ts = today.isoformat()
    print(f"Daily Briefing — {ts}")

    # 1. Vehicles
    print("Reading [坐骑]...")
    try:
        vehicles = consolidate(parse_note(read_note()))
        alerts = check_dates(vehicles)
    except Exception as e:
        print(f"  FAILED: {e}", file=sys.stderr)
        alerts = {"overdue": [], "upcoming": []}

    od, up = len(alerts["overdue"]), len(alerts["upcoming"])
    if od:
        print(f"  {od} items need attention")
        for x in alerts["overdue"]:
            print(f"    [{x['category'][:4]}] {x['vehicle']}: {x['desc']}")
    if up:
        print(f"  {up} items upcoming")
        for x in alerts["upcoming"]:
            print(f"    [{x['category'][:4]}] {x['vehicle']}: {x['desc']} ({x['days_left']}d)")
    if not od and not up:
        print("  All clear")

    # 2. GitHub
    print(f"Fetching verl ({GITHUB_REPO})...")
    gh = fetch_verl()
    print(f"  PRs: {len(gh['prs'])} | Issues: {len(gh['issues'])}")

    # 3. Generate markdown
    md = md_briefing(ts, alerts, gh)

    # 4. Save to repo
    ym = today.strftime("%Y/%m")
    brief_dir = os.path.join(BRIEFINGS_DIR, ym)
    os.makedirs(brief_dir, exist_ok=True)
    md_path = os.path.join(brief_dir, f"briefing_{ts}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"  Markdown saved: {md_path}")

    # 5. Save structured JSON
    os.makedirs(DATA_DIR, exist_ok=True)
    structured = {
        "date": ts,
        "vehicle_alerts": alerts,
        "github_activity": gh,
        "generated_at": datetime.now().isoformat(),
    }
    json_path = os.path.join(DATA_DIR, f"briefing_{ts}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(structured, f, ensure_ascii=False, indent=2)
    print(f"  JSON saved: {json_path}")

    # 6. Git commit & push
    print("Committing to repo...")
    git("add", "-A")
    git("commit", "-m", f"Daily briefing {ts}")
    result = git("push", "origin", "main")
    if result.returncode != 0:
        print(f"  Git push warning: {result.stderr.strip()}", file=sys.stderr)
    else:
        print("  Pushed to origin/main")

    # 7. Create GitHub Issue
    issue_title = f"📋 Daily Briefing — {ts}"
    issue_url = create_issue(issue_title, md)
    if issue_url:
        print(f"  Issue created: {issue_url}")
    else:
        print("  (GitHub token not configured — skipping issue creation)")
        print("  Set CODEX_GITHUB_TOKEN env var or place token in ~/.codex/github_token")

    print("Done!")

if __name__ == "__main__":
    main()
