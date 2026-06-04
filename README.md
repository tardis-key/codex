# 📋 Codex Daily Briefing

<p align="center">
  <img src="https://img.shields.io/badge/generator-Codex-blue?style=flat-square" alt="Codex">
  <img src="https://img.shields.io/badge/schedule-daily%2009:00%20CST-green?style=flat-square" alt="Schedule">
  <img src="https://img.shields.io/badge/repo-tardis--key%2Fcodex-333?style=flat-square" alt="Repo">
</p>

---

自动化每日简报系统。由 **Codex** 生成并维护。

## 监控范围

| 模块 | 仓库 | 说明 |
|------|------|------|
| 🔧 **verl** | [verl-project/verl](https://github.com/verl-project/verl) | RL training framework |
| 🔧 **slime** | [THUDM/slime](https://github.com/THUDM/slime) | LLM post-training RL framework |
| 🚗 **车辆** | Apple Notes "坐骑" | 保险到期 / 保养周期提醒 |

PR 和 Issue 会展示标题、作者、代码变更量及内容概述。

## 车辆提醒逻辑

| 类型 | 语义 | 周期 |
|:----:|------|------|
| 🛡️ 保险 | 记录日期 = 到期日 | — |
| 🔧 机油 | 记录日期 = 上次执行日 | 6 个月 |
| 🔧 保养 | 记录日期 = 上次执行日 | 12 个月 |
| 🔧 大保养 | 覆盖机油 / 刹车油 / 冷却液 / 雨刷 / 电池 | 12 个月 |
| 🔧 刹车油 | 记录日期 = 上次执行日 | 24 个月 |

## 目录

```
codex/
├── README.md
├── scripts/
│   └── daily_briefing.py
├── briefings/YYYY/MM/
│   └── YYYY-MM-DD.md        ← 每日 Markdown
├── data/
│   └── YYYY-MM-DD.json       ← 结构化 JSON
└── .github/
```

## 身份标识

所有自动内容包含以下签名，与人工提交明确区分：

> 🤖 由 **Codex** 自动生成 · 非人工发布

---

<sub>🤖 由 **Codex** 自动维护 · 与 [@huxiaobo](https://github.com/huxiaobo) 共用账号</sub>
