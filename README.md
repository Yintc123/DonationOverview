# JKODonation

2026 全端面試作業（web）— 捐款項目列表（公益團體）。

> 設計稿：Figma《2026 全端面試作業 - web》

## 結構

本 repo 為**專案層級總目錄**，`frontend/` 與 `backend/` 各自為獨立 git repo。

| 子專案 | 技術棧 | README |
|---|---|---|
| `frontend/` | TypeScript · Next.js 16（App Router）· TailwindCSS · BFF | [frontend/README.md](./frontend/README.md) |
| `backend/` | TypeScript · Fastify · Prisma · PostgreSQL · Redis | [backend/README.md](./backend/README.md) |

## 文件

- [`docs/decisions/`](./docs/decisions/) — 專案級 ADR（架構決策紀錄）
- [`docs/prompts/`](./docs/prompts/) — 與 AI 的對話紀錄（raw + 精選版）
- [`CLAUDE.md`](./CLAUDE.md) — Claude Code 專案級指示

## AI 使用聲明

開發過程使用 [Claude Code](https://claude.com/claude-code)（Opus 4.7）輔助。
各子專案 README 內有更細的負責範圍說明。
