#!/usr/bin/env python3
"""
Codex Daily Briefing
Posts structured daily reports to tardis-key/codex.
All generated content is signed as "Codex" to distinguish from user-authored content.
"""

import json
import os
import re
import ssl
import subprocess
import sys
import urllib.request
from datetime import datetime, date, timedelta

# ── Paths ─────────────────────────────────────────────────────────
REPO_DIR     = os.path.expanduser("~/Documents/GitHub/codex")
BRIEFINGS_DIR = os.path.join(REPO_DIR, "briefings")
DATA_DIR     = os.path.join(REPO_DIR, "data")
TOKEN_FILE   = os.path.expanduser("~/.codex/github_token")

# ── Config ────────────────────────────────────────────────────────
VERL_REPO    = "verl-project/verl"
OWNER_REPO   = "tardis-key/codex"
DAYS_LOOKAHEAD = 30
PR_ISSUE_HOURS = 24

# ── Maintenance intervals (months) ────────────────────────────────
INTERVALS = {
    "机油": 6, "换机油": 6,
    "保养": 12, "大保养": 12,
    "刹车油": 24, "冷却液": 12,
    "雨刷": 12, "电池": 12,
}

SUPERSEDING = {
    "大保养": ["机油", "换机油", "刹车油", "冷却液", "雨刷", "电池"],
    "保养":   ["机油", "换机油"],
}

# ═══════════════════════════════════════════════════════════════════
#  GitHub Helpers
# ═══════════════════════════════════════════════════════════════════

def get_token():
    t = os.environ.get("CODEX_GITHUB_TOKEN", "")
    if not t and os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            t = f.read().strip()
    return t

def gh_api(method, path, body=None):
    token = get_token()
    if not token:
        return None
    url = f"https://api.github.com{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {token}",
        "User-Agent": "Codex-Daily-Briefing/2.0",
        "Accept": "application/vnd.github+json",
    }, method=method)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        return json.loads(resp.read().decode())

def fetch_json(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Codex-Daily-Briefing/2.0",
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

# ═══════════════════════════════════════════════════════════════════
#  Step 1 — Read Apple Notes
# ═══════════════════════════════════════════════════════════════════

def read_note():
    r = subprocess.run(
        ["osascript", "-e",
         'tell application id "com.apple.Notes" to get body of note "坐骑"'],
        capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return r.stdout

# ═══════════════════════════════════════════════════════════════════
#  Step 2 — Parse + Consolidate
# ═══════════════════════════════════════════════════════════════════

def parse_note(html):
    vehicles = []
    h2 = re.compile(r'<h2>(.+?)</h2>')
    li = re.compile(r'<li>(.+?)</li>')
    ul = re.compile(r'<ul>(.+?)</ul>', re.DOTALL)
    dt = re.compile(r'(\d{4})\.(\d{1,2})\.(\d{1,2})')

    names = [re.sub(r'<[^>]+>', '', m.group(1)).strip()
             for m in h2.finditer(html)
             if re.sub(r'<[^>]+>', '', m.group(1)).strip()
             and re.sub(r'<[^>]+>', '', m.group(1)).strip() != '坐骑']
    uls = list(ul.finditer(html))

    for idx, name in enumerate(names):
        section = uls[idx].group(1) if idx < len(uls) else ""
        items = []
        for m in li.finditer(section):
            text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            dm = dt.search(text)
            items.append({
                "desc": text,
                "date": date(int(dm[1]), int(dm[2]), int(dm[3])) if dm else None
            })
        vehicles.append({"vehicle": name, "items": items})
    return vehicles

def consolidate(vehicles):
    for v in vehicles:
        best_date, best_subs = None, []
        for item in v["items"]:
            if not item["date"]:
                continue
            for svc, subs in SUPERSEDING.items():
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

# ═══════════════════════════════════════════════════════════════════
#  Step 3 — Urgency Check
# ═══════════════════════════════════════════════════════════════════

def classify(desc):
    if "险" in desc:
        return "insurance"
    for kw in INTERVALS:
        if kw in desc:
            return "maintenance"
    return "maintenance"

def effective_date(item):
    d = item["date"]
    cat = classify(item["desc"])
    if cat == "insurance":
        return d
    interval = INTERVALS.get(
        next((kw for kw in INTERVALS if kw in item["desc"]), "保养"), 12)
    total = d.year * 12 + d.month + interval
    y, m = total // 12, total % 12
    if m == 0:
        y, m = y - 1, 12
    return date(y, m, min(d.day, 28))

def check_dates(vehicles):
    today = date.today()
    cutoff = today + timedelta(days=DAYS_LOOKAHEAD)
    overdue, upcoming = [], []

    for v in vehicles:
        for item in v["items"]:
            if not item["date"]:
                continue
            eff = effective_date(item)
            cat = classify(item["desc"])
            entry = {
                "vehicle": v["vehicle"], "desc": item["desc"],
                "recorded": item["date"].isoformat(), "effective": eff.isoformat(),
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

# ═══════════════════════════════════════════════════════════════════
#  Step 4 — Fetch verl Activity
# ═══════════════════════════════════════════════════════════════════

def fetch_verl():
    since = (datetime.now() - timedelta(hours=PR_ISSUE_HOURS)).isoformat() + "Z"
    prs, issues = [], []
    try:
        for p in fetch_json(f"https://api.github.com/repos/{VERL_REPO}/pulls?state=all&sort=created&direction=desc&per_page=15"):
            if p.get("created_at", "") >= since:
                prs.append({"number": p["number"], "title": p["title"],
                            "user": p["user"]["login"], "state": p["state"],
                            "url": p["html_url"]})
    except Exception as e:
        print(f"  ⚠ verl PRs: {e}", file=sys.stderr)
    try:
        for iss in fetch_json(f"https://api.github.com/repos/{VERL_REPO}/issues?state=all&sort=created&direction=desc&per_page=15"):
            if "pull_request" in iss:
                continue
            if iss.get("created_at", "") >= since:
                issues.append({"number": iss["number"], "title": iss["title"],
                               "user": iss["user"]["login"], "state": iss["state"],
                               "url": iss["html_url"]})
    except Exception as e:
        print(f"  ⚠ verl Issues: {e}", file=sys.stderr)
    return {"prs": prs, "issues": issues}

# ═══════════════════════════════════════════════════════════════════
#  Step 5 — Check Repo Issues (for response)
# ═══════════════════════════════════════════════════════════════════

def check_repo_issues(today_str):
    """Fetch new issues in tardis-key/codex that are NOT daily briefings
    and have no response from Codex yet."""
    try:
        all_issues = gh_api("GET", f"/repos/{OWNER_REPO}/issues?state=open&per_page=20")
        if not all_issues:
            return []
        unresponded = []
        for iss in all_issues:
            title = iss.get("title", "")
            # Skip daily briefing issues
            if "Daily Briefing" in title:
                continue
            # Check if Codex already commented
            comments = gh_api("GET", f"/repos/{OWNER_REPO}/issues/{iss['number']}/comments?per_page=10") or []
            has_codex = any("codex" in c.get("body", "").lower() for c in comments)
            if not has_codex:
                unresponded.append({
                    "number": iss["number"],
                    "title": title,
                    "user": iss["user"]["login"],
                    "body": iss.get("body", "")[:300],
                    "url": iss["html_url"],
                })
        return unresponded
    except Exception as e:
        print(f"  ⚠ Repo issues: {e}", file=sys.stderr)
        return []

# ═══════════════════════════════════════════════════════════════════
#  Step 6 — Generate Markdown
# ═══════════════════════════════════════════════════════════════════

def md_briefing(ts, alerts, gh, repo_issues):
    lines = []
    lines.append(f"# 📋 Daily Briefing — {ts}")
    lines.append("")

    # ── Vehicle Alerts ──
    lines.append("## 🚗 车辆提醒")
    lines.append("")
    lines.append("> **保险** — 日期为到期日 ｜ **保养** — 日期为上次执行日，按行业周期推算下次时间")
    lines.append("")

    # Overdue
    ins_od = [x for x in alerts["overdue"] if x["category"] == "insurance"]
    mai_od = [x for x in alerts["overdue"] if x["category"] == "maintenance"]

    if alerts["overdue"]:
        lines.append("### 🔴 需关注")
        lines.append("")
        lines.append("| 类型 | 车辆 | 事项 | 记录日期 | 应于 |")
        lines.append("|:----:|------|------|:----------:|:----:|")
        for x in alerts["overdue"]:
            emoji = "🛡️" if x["category"] == "insurance" else "🔧"
            lines.append(
                f"| {emoji} | {x['vehicle']} | {x['desc']} "
                f"| {x['recorded']} | **{x['effective']}** |")
        lines.append("")

    # Upcoming
    ins_up = [x for x in alerts["upcoming"] if x["category"] == "insurance"]
    mai_up = [x for x in alerts["upcoming"] if x["category"] == "maintenance"]

    if alerts["upcoming"]:
        lines.append("### 🟡 即将到期 (30天内)")
        lines.append("")
        lines.append("| 类型 | 车辆 | 事项 | 记录日期 | 到期日 | 剩余 |")
        lines.append("|:----:|------|------|:----------:|:----:|:----:|")
        for x in alerts["upcoming"]:
            emoji = "🛡️" if x["category"] == "insurance" else "🔧"
            lines.append(
                f"| {emoji} | {x['vehicle']} | {x['desc']} "
                f"| {x['recorded']} | {x['effective']} | {x['days_left']} 天 |")
        lines.append("")

    if not alerts["overdue"] and not alerts["upcoming"]:
        lines.append("✅ 暂无待办事项，一切正常。")
        lines.append("")

    # ── verl Activity ──
    lines.append(f"## 🔧 verl · PR ({len(gh['prs'])}) + Issues ({len(gh['issues'])})")
    lines.append("")
    lines.append(f"> 数据来源：[{VERL_REPO}](https://github.com/{VERL_REPO}) · 过去 24 小时")
    lines.append("")

    if gh["prs"]:
        lines.append("### Pull Requests")
        lines.append("")
        lines.append("| # | 标题 | 作者 | 状态 |")
        lines.append("|---|------|------|:----:|")
        for p in gh["prs"]:
            s = "🟢 open" if p["state"] == "open" else "🟣 merged" if p["state"] == "merged" else "⚫ closed"
            lines.append(f"| [#{p['number']}]({p['url']}) | {p['title']} | {p['user']} | {s} |")
        lines.append("")

    if gh["issues"]:
        lines.append("### Issues")
        lines.append("")
        lines.append("| # | 标题 | 作者 | 状态 |")
        lines.append("|---|------|------|:----:|")
        for iss in gh["issues"]:
            s = "🟢 open" if iss["state"] == "open" else "⚫ closed"
            lines.append(f"| [#{iss['number']}]({iss['url']}) | {iss['title']} | {iss['user']} | {s} |")
        lines.append("")

    if not gh["prs"] and not gh["issues"]:
        lines.append("过去 24 小时无新动态。")
        lines.append("")

    # ── Repo Issues to answer ──
    if repo_issues:
        lines.append("## 📬 待回复的 Issue")
        lines.append("")
        for ri in repo_issues:
            lines.append(f"- [#{ri['number']}]({ri['url']}) — {ri['title']} (by @{ri['user']})")
        lines.append("")

    # ── Signature ──
    lines.append("---")
    lines.append("")
    lines.append(f"<sub>🤖 由 **Codex** 自动生成 · {datetime.now().strftime('%Y-%m-%d %H:%M')} · 非人工发布</sub>")
    return "\n".join(lines)

# ═══════════════════════════════════════════════════════════════════
#  Step 7 — Create Issue / Respond
# ═══════════════════════════════════════════════════════════════════

def create_issue(title, body):
    resp = gh_api("POST", f"/repos/{OWNER_REPO}/issues", {
        "title": title,
        "body": body,
        "labels": ["daily-briefing", "auto-generated"]
    })
    return resp.get("html_url") if resp else None

def respond_to_issue(issue_number, body):
    return gh_api("POST", f"/repos/{OWNER_REPO}/issues/{issue_number}/comments", {
        "body": body
    })

# ═══════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════

def main():
    today = date.today()
    ts = today.isoformat()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    print(f"╔══════════════════════════════════════════╗")
    print(f"║   Codex Daily Briefing — {ts}   ║")
    print(f"╚══════════════════════════════════════════╝")

    # 1. Vehicles
    print("\n🚗  Reading [坐骑] note...")
    try:
        vehicles = consolidate(parse_note(read_note()))
        alerts = check_dates(vehicles)
    except Exception as e:
        print(f"    ❌ Failed: {e}", file=sys.stderr)
        alerts = {"overdue": [], "upcoming": []}

    od, up = len(alerts["overdue"]), len(alerts["upcoming"])
    for x in alerts["overdue"]:
        print(f"    🔴 {x['vehicle']}: {x['desc']} (due {x['effective']})")
    for x in alerts["upcoming"]:
        print(f"    🟡 {x['vehicle']}: {x['desc']} ({x['days_left']}d)")
    if not od and not up:
        print("    ✅ All clear")

    # 2. verl
    print(f"\n🔧  Fetching {VERL_REPO}...")
    gh = fetch_verl()
    print(f"    PRs: {len(gh['prs'])} | Issues: {len(gh['issues'])}")

    # 3. Repo issues
    print(f"\n📬  Checking {OWNER_REPO} issues...")
    repo_issues = check_repo_issues(ts)
    if repo_issues:
        print(f"    {len(repo_issues)} issue(s) need response")
    else:
        print("    None pending")

    # 4. Generate
    print("\n📝  Generating briefing...")
    md = md_briefing(ts, alerts, gh, repo_issues)

    # 5. Save to repo
    ym = today.strftime("%Y/%m")
    d = os.path.join(BRIEFINGS_DIR, ym)
    os.makedirs(d, exist_ok=True)
    mp = os.path.join(d, f"{ts}.md")
    with open(mp, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"    ✓ Markdown → {mp}")

    os.makedirs(DATA_DIR, exist_ok=True)
    jp = os.path.join(DATA_DIR, f"{ts}.json")
    with open(jp, "w", encoding="utf-8") as f:
        json.dump({
            "date": ts, "alerts": alerts, "verl": gh,
            "repo_issues": repo_issues, "generated_at": now_str,
            "generator": "Codex"
        }, f, ensure_ascii=False, indent=2)
    print(f"    ✓ JSON → {jp}")

    # 6. Git
    print("\n📦  Committing...")
    git("add", "-A")
    git("commit", "-m", f"{ts} daily briefing [Codex]")
    r = git("push", "origin", "main")
    if r.returncode != 0:
        print(f"    ⚠ Push: {r.stderr.strip()}", file=sys.stderr)
    else:
        print("    ✓ Pushed to origin/main")

    # 7. Create Issue
    print("\n📮  Creating GitHub Issue...")
    url = create_issue(f"📋 Daily Briefing — {ts}", md)
    if url:
        print(f"    ✓ {url}")
    else:
        print("    ⚠ Token not configured — skipping")

    # 8. Respond to pending issues
    for ri in repo_issues:
        print(f"\n💬  Responding to #{ri['number']}...")
        resp_body = (
            f"👋 你好 @{ri['user']}，Codex 已收到这条 Issue。\n\n"
            f"我会在后续的对话中跟进处理。请留意回复通知。\n\n"
            f"---\n"
            f"<sub>🤖 由 **Codex** 自动回复 · {now_str}</sub>"
        )
        respond_to_issue(ri["number"], resp_body)
        print(f"    ✓ Replied to #{ri['number']}")

    print(f"\n✨  Done — {now_str}")

if __name__ == "__main__":
    main()
