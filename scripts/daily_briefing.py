#!/usr/bin/env python3
"""
Codex Daily Briefing
Monitors verl + slime repos, checks vehicle maintenance, posts to tardis-key/codex.
All generated content is signed as "Codex".
"""

import json, os, re, ssl, subprocess, sys, urllib.request
from datetime import datetime, date, timedelta

# ── Paths ─────────────────────────────────────────────────────────
REPO_DIR      = os.path.expanduser("~/Documents/GitHub/codex")
BRIEFINGS_DIR = os.path.join(REPO_DIR, "briefings")
DATA_DIR      = os.path.join(REPO_DIR, "data")
TOKEN_FILE    = os.path.expanduser("~/.codex/github_token")

# ── Config ────────────────────────────────────────────────────────
AT_USER       = "tardis-key"  # GitHub username to @mention in daily issues
MONITORED_REPOS = [
    {"name": "verl",  "repo": "verl-project/verl"},
    {"name": "slime", "repo": "THUDM/slime"},
]
OWNER_REPO     = "tardis-key/codex"
DAYS_LOOKAHEAD = 30
PR_ISSUE_HOURS = 24

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
#  GitHub helpers
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
    with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
        return json.loads(resp.read().decode())

def fetch_json(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Codex-Daily-Briefing/2.0",
        "Accept": "application/vnd.github+json"
    })
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
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
    h2 = re.compile(r"<h2>(.+?)</h2>")
    li = re.compile(r"<li>(.+?)</li>")
    ul = re.compile(r"<ul>(.+?)</ul>", re.DOTALL)
    dt = re.compile(r"(\d{4})\.(\d{1,2})\.(\d{1,2})")
    names = [re.sub(r"<[^>]+>", "", m.group(1)).strip()
             for m in h2.finditer(html)
             if re.sub(r"<[^>]+>", "", m.group(1)).strip()
             and re.sub(r"<[^>]+>", "", m.group(1)).strip() != "坐骑"]
    uls = list(ul.finditer(html))
    vehicles = []
    for idx, name in enumerate(names):
        section = uls[idx].group(1) if idx < len(uls) else ""
        items = []
        for m in li.finditer(section):
            text = re.sub(r"<[^>]+>", "", m.group(1)).strip()
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
    interval = 12
    for kw, mo in INTERVALS.items():
        if kw in item["desc"]:
            interval = mo
            break
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
#  Step 4 — Fetch repos (with PR descriptions + diff stats)
# ═══════════════════════════════════════════════════════════════════

def _summarize_pr_body(body, max_len=200):
    """Extract first meaningful paragraph from PR/issue body."""
    if not body:
        return ""
    # Remove HTML comments
    cleaned = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)
    # Remove markdown images and links (keep link text)
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", cleaned)
    cleaned = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", cleaned)
    # Remove markdown headers
    cleaned = re.sub(r"^#{1,4}\s.*$", "", cleaned, flags=re.MULTILINE)
    # Remove checklist items
    cleaned = re.sub(r"^\s*[-*]\s*\[[ x]\]\s.*$", "", cleaned, flags=re.MULTILINE)
    # Collapse excessive whitespace
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    # Get first non-empty, non-header paragraph
    paras = [p.strip() for p in cleaned.split("\n\n") if p.strip()]
    if not paras:
        return ""
    summary = paras[0][:max_len].replace("\n", " ").replace("\r", "")
    if len(paras[0]) > max_len:
        summary += "..."
    return summary

def _clean_title(title):
    """Remove common prefixes like [feat], [fix], [ci] from display."""
    return re.sub(r"^\[.*?\]\s*", "", title).strip()

def fetch_repo_activity(monitor):
    """Fetch PRs and issues for one monitored repo, with summaries."""
    repo = monitor["repo"]
    since = (datetime.now() - timedelta(hours=PR_ISSUE_HOURS)).isoformat() + "Z"
    prs, issues = [], []

    # Fetch PRs
    try:
        pr_data = fetch_json(
            f"https://api.github.com/repos/{repo}/pulls?state=all&sort=created&direction=desc&per_page=12")
        for p in pr_data:
            if p.get("created_at", "") < since:
                continue
            # PR list response already includes body, additions, deletions
            summary = _summarize_pr_body(p.get("body") or "")

            prs.append({
                "number": p["number"],
                "title": p["title"],
                "user": p["user"]["login"],
                "state": p["state"],
                "url": p["html_url"],
                "summary": summary,
            })
    except Exception as e:
        print(f"  ! {repo} PRs: {e}", file=sys.stderr)

    # Fetch Issues
    try:
        iss_data = fetch_json(
            f"https://api.github.com/repos/{repo}/issues?state=all&sort=created&direction=desc&per_page=12")
        for iss in iss_data:
            if iss.get("created_at", "") < since:
                continue
            if "pull_request" in iss:
                continue
            body_text = (iss.get("body") or "")
            summary = _summarize_pr_body(body_text, max_len=150)
            issues.append({
                "number": iss["number"],
                "title": iss["title"],
                "user": iss["user"]["login"],
                "state": iss["state"],
                "url": iss["html_url"],
                "summary": summary,
            })
    except Exception as e:
        print(f"  ! {repo} Issues: {e}", file=sys.stderr)

    return {"name": monitor["name"], "repo": repo, "prs": prs, "issues": issues}

# ═══════════════════════════════════════════════════════════════════
#  Step 5 — Check own repo issues
# ═══════════════════════════════════════════════════════════════════

def check_repo_issues():
    try:
        all_issues = gh_api("GET", f"/repos/{OWNER_REPO}/issues?state=open&per_page=20")
        if not all_issues:
            return []
        unresponded = []
        for iss in all_issues:
            title = iss.get("title", "")
            if "Daily Briefing" in title:
                continue
            comments = gh_api("GET", f"/repos/{OWNER_REPO}/issues/{iss['number']}/comments?per_page=10") or []
            has_codex = any("codex" in c.get("body", "").lower() for c in comments)
            if not has_codex:
                unresponded.append({
                    "number": iss["number"], "title": title,
                    "user": iss["user"]["login"],
                    "body": (iss.get("body") or "")[:300],
                    "url": iss["html_url"],
                })
        return unresponded
    except Exception as e:
        print(f"  ! Repo issues: {e}", file=sys.stderr)
        return []

# ═══════════════════════════════════════════════════════════════════
#  Step 6 — Generate Markdown
# ═══════════════════════════════════════════════════════════════════

def md_briefing(ts, all_vehicles, alerts, repos, repo_issues):
    L = []
    L.append(f"# 📋 Daily Briefing — {ts}")
    L.append("")
    L.append(f"> @{AT_USER} 早上好，今日简报已送达。")
    L.append("")

    # ── Vehicles ──
    L.append("## 🚗 车辆提醒")
    L.append("")
    L.append("> **保险** — 日期为到期日 ｜ **保养** — 日期为上次执行日，按行业周期推算下次时间")
    L.append("")

    L.append("### 📊 车辆总览")
    L.append("")
    L.append("| 车辆 | 状态 |")
    L.append("|------|------|")
    for vname in all_vehicles:
        v_items = []
        for x in alerts["overdue"]:
            if x["vehicle"] == vname:
                v_items.append("🔴 " + x["desc"])
        for x in alerts["upcoming"]:
            if x["vehicle"] == vname:
                v_items.append(f"🟡 {x['desc']}（{x['days_left']}天后）")
        L.append(f"| {vname} | {' · '.join(v_items) if v_items else '✅ 正常'} |")
    L.append("")

    if alerts["overdue"]:
        L.append("### 🔴 需关注")
        L.append("")
        L.append("| 类型 | 车辆 | 事项 | 记录日期 | 应于 |")
        L.append("|:----:|------|------|:----------:|:----:|")
        for x in alerts["overdue"]:
            em = "🛡️" if x["category"] == "insurance" else "🔧"
            L.append(f"| {em} | {x['vehicle']} | {x['desc']} | {x['recorded']} | **{x['effective']}** |")
        L.append("")

    if alerts["upcoming"]:
        L.append("### 🟡 即将到期 (30天内)")
        L.append("")
        L.append("| 类型 | 车辆 | 事项 | 记录日期 | 到期日 | 剩余 |")
        L.append("|:----:|------|------|:----------:|:----:|:----:|")
        for x in alerts["upcoming"]:
            em = "🛡️" if x["category"] == "insurance" else "🔧"
            L.append(f"| {em} | {x['vehicle']} | {x['desc']} | {x['recorded']} | {x['effective']} | {x['days_left']} 天 |")
        L.append("")

    # ── Monitored repos ──
    for r in repos:
        name = r["name"]
        prs = r["prs"]
        issues = r["issues"]
        repo_url = r["repo"]

        L.append(f"## 🔧 {name} · PR ({len(prs)}) + Issues ({len(issues)})")
        L.append("")
        L.append(f"> [{repo_url}](https://github.com/{repo_url}) · 过去 24 小时")
        L.append("")

        if prs:
            L.append("### Pull Requests")
            L.append("")
            L.append("| # | 标题 | 作者 | 概述 |")
            L.append("|---|------|------|------|")
            for p in prs:
                s_map = {"open": "🟢", "merged": "🟣", "closed": "⚫"}
                s = s_map.get(p["state"], "")
                summary = (p.get("summary", "") or "—").replace("\n", " ").replace("\r", "")
                L.append(f"| {s} #{p['number']} | {p['title']} | {p['user']} | {summary} |")
            L.append("")

        if issues:
            L.append("### Issues")
            L.append("")
            L.append("| # | 标题 | 作者 | 概述 |")
            L.append("|---|------|------|------|")
            for iss in issues:
                s = "🟢" if iss["state"] == "open" else "⚫"
                summary = (iss.get("summary", "") or "—").replace("\n", " ").replace("\r", "")
                L.append(f"| {s} #{iss['number']} | {iss['title']} | {iss['user']} | {summary} |")
            L.append("")

        if not prs and not issues:
            L.append("过去 24 小时无新动态。")
            L.append("")

    # ── Own repo issues ──
    if repo_issues:
        L.append("## 📬 待回复的 Issue")
        L.append("")
        for ri in repo_issues:
            L.append(f"- #{ri['number']} [{ri['title']}]({ri['url']}) — by @{ri['user']}")
        L.append("")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    L.append("---")
    L.append("")
    L.append(f"<sub>🤖 由 **Codex** 自动生成 · {now_str} · 非人工发布</sub>")
    return "\n".join(L)

# ═══════════════════════════════════════════════════════════════════
#  Actions
# ═══════════════════════════════════════════════════════════════════

def create_issue(title, body):
    resp = gh_api("POST", f"/repos/{OWNER_REPO}/issues", {
        "title": title, "body": body,
        "labels": ["daily-briefing", "auto-generated"]
    })
    return resp.get("html_url") if resp else None

def respond_to_issue(num, body):
    return gh_api("POST", f"/repos/{OWNER_REPO}/issues/{num}/comments", {"body": body})

# ═══════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════

def main():
    today = date.today()
    ts = today.isoformat()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    print(f"Codex Daily Briefing — {ts}")

    # 1. Vehicles
    print("\n[坐骑]...")
    all_names = []
    try:
        vehicles = consolidate(parse_note(read_note()))
        all_names = [v["vehicle"] for v in vehicles]
        alerts = check_dates(vehicles)
    except Exception as e:
        print(f"  FAILED: {e}", file=sys.stderr)
        alerts = {"overdue": [], "upcoming": []}

    od, up = len(alerts["overdue"]), len(alerts["upcoming"])
    for x in alerts["overdue"]:
        print(f"  🔴 {x['vehicle']}: {x['desc']}")
    for x in alerts["upcoming"]:
        print(f"  🟡 {x['vehicle']}: {x['desc']} ({x['days_left']}d)")
    if not od and not up:
        print("  All clear")

    # 2. Monitored repos
    repos = []
    for m in MONITORED_REPOS:
        print(f"\n[{m['repo']}]...")
        r = fetch_repo_activity(m)
        repos.append(r)
        print(f"  PRs: {len(r['prs'])} | Issues: {len(r['issues'])}")

    # 3. Own repo issues
    print(f"\n[{OWNER_REPO}]...")
    repo_issues = check_repo_issues()
    print(f"  Pending: {len(repo_issues)}")

    # 4. Generate
    print("\nGenerating...")
    md = md_briefing(ts, all_names, alerts, repos, repo_issues)

    # 5. Save to repo
    ym = today.strftime("%Y/%m")
    d = os.path.join(BRIEFINGS_DIR, ym)
    os.makedirs(d, exist_ok=True)
    mp = os.path.join(d, f"{ts}.md")
    with open(mp, "w", encoding="utf-8") as f:
        f.write(md)

    os.makedirs(DATA_DIR, exist_ok=True)
    jp = os.path.join(DATA_DIR, f"{ts}.json")
    with open(jp, "w", encoding="utf-8") as f:
        json.dump({
            "date": ts, "vehicles": all_names, "alerts": alerts,
            "repos": repos, "repo_issues": repo_issues,
            "generated_at": now_str, "generator": "Codex"
        }, f, ensure_ascii=False, indent=2)

    # 6. Git
    print("\nCommitting...")
    git("add", "-A")
    git("commit", "-m", f"{ts} daily briefing [Codex]")
    r = git("push", "origin", "main")
    if r.returncode != 0:
        print(f"  ! Push: {r.stderr.strip()}", file=sys.stderr)
    else:
        print("  ✓ Pushed")

    # 7. Issue
    print("\nCreating Issue...")
    url = create_issue(f"📋 Daily Briefing — {ts}", md)
    if url:
        print(f"  ✓ {url}")
    else:
        print("  No token — skipped")

    # 8. Respond to pending issues
    for ri in repo_issues:
        print(f"\nReplying to #{ri['number']}...")
        respond_to_issue(ri["number"],
            f"👋 你好 @{ri['user']}，Codex 已收到这条 Issue。\n\n"
            f"我会在后续的对话中跟进处理。\n\n"
            f"---\n"
            f"<sub>🤖 由 **Codex** 自动回复 · {now_str}</sub>")
        print(f"  ✓ Replied")

    print(f"\n✨  Done — {now_str}")

if __name__ == "__main__":
    main()
