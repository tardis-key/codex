# Codex Daily Briefing

Automated daily briefing system. Every day at 9:00 AM:

- 🚗 Reads vehicle maintenance/insurance records from Apple Notes ("坐骑")
- 🔧 Monitors [verl](https://github.com/verl-project/verl) repository for new PRs and issues
- 📋 Posts a structured briefing as a GitHub Issue
- 📁 Archives all briefings in `briefings/YYYY/MM/`

## Structure

```
codex/
├── scripts/daily_briefing.py   # The automation script
├── briefings/YYYY/MM/          # Daily markdown briefings
├── data/                       # Structured JSON data
└── README.md
```

## Setup

### 1. GitHub Token (for Issue creation)

Create a [GitHub Personal Access Token](https://github.com/settings/tokens) with `repo` scope.

```bash
# Option A: Environment variable
export CODEX_GITHUB_TOKEN=ghp_xxxxxxxx

# Option B: Token file
echo "ghp_xxxxxxxx" > ~/.codex/github_token
chmod 600 ~/.codex/github_token
```

### 2. Launchd schedule

The script runs daily at 9:00 AM via macOS launchd:

```bash
# Check status
launchctl list com.codex.daily-briefing

# Manual run
python3 scripts/daily_briefing.py
```
