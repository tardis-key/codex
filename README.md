# 📋 Codex Daily Briefing

<p align="center">
  <img src="https://img.shields.io/badge/generator-Codex-blue?style=flat-square" alt="Codex">
  <img src="https://img.shields.io/badge/schedule-daily%209:00%20AM-green?style=flat-square" alt="Schedule">
  <img src="https://img.shields.io/badge/repo-tardis--key%2Fcodex-333?style=flat-square" alt="Repo">
</p>

---

自动化每日简报系统。由 **Codex** 生成并维护，内容与人工提交明确区分。

## 功能

| 模块 | 说明 |
|------|------|
| 🚗 **车辆提醒** | 读取 Apple Notes "坐骑"，判断保险到期 / 保养周期 |
| 🔧 **verl 监控** | 跟踪 [verl](https://github.com/verl-project/verl) 仓库 24h 内新增 PR & Issue |
| 📮 **Issue 自动发布** | 每日简报以 Issue 形式发布，标注 `daily-briefing` 标签 |
| 💬 **Issue 响应** | 自动检测仓库中未回复的 Issue 并标记为"已收到" |

## 目录结构

```
codex/
├── README.md
├── scripts/
│   └── daily_briefing.py     ← 自动化主脚本
├── briefings/
│   └── YYYY/MM/
│       └── YYYY-MM-DD.md     ← 每日简报 (Markdown)
├── data/
│   └── YYYY-MM-DD.json       ← 结构化数据 (JSON)
└── .github/
    └── labels.yml            ← Issue 标签配置
```

## 车辆提醒逻辑

- **保险类**（含"险"字）：记录日期 = 到期日。过期立即提醒。
- **保养类**：记录日期 = 上次执行日，按行业周期推算：
  - 机油 / 换机油 → 6 个月
  - 保养 / 大保养 → 12 个月
  - 刹车油 → 24 个月
  - 电池 / 雨刷 / 冷却液 → 12 个月
- **合并规则**："大保养"覆盖机油 / 刹车油 / 冷却液 / 雨刷 / 电池；"保养"覆盖机油。避免重复提醒。

## 身份标识

所有自动生成的内容均包含以下标识，与人工操作明确区分：

> <sub>🤖 由 **Codex** 自动生成 · 非人工发布</sub>

## 配置

### GitHub Token

创建 [Personal Access Token](https://github.com/settings/tokens)，勾选 `repo` 权限：

```bash
echo "github_pat_xxx" > ~/.codex/github_token
chmod 600 ~/.codex/github_token
```

### 调度

通过 macOS `launchd` 每日 9:00 执行：

```bash
# 状态
launchctl list com.codex.daily-briefing

# 手动执行
python3 scripts/daily_briefing.py
```

---

<sub>🤖 本仓库由 **Codex** 自动维护 · 与 [@huxiaobo](https://github.com/huxiaobo) 共用账号</sub>
