# JKODonation

2026 全端面試作業（web）— 捐款項目列表（公益團體）。

> 設計稿：Figma《2026 全端面試作業 - web》

## 結構

本 repo 為**專案層級總目錄**，`frontend/` 與 `backend/` 各自為獨立 git repo。

| 子專案 | 技術棧 | README |
|---|---|---|
| `frontend/` | TypeScript · Next.js 16（App Router）· TailwindCSS · BFF | [frontend/README.md](./frontend/README.md) |
| `backend/` | TypeScript · Fastify · Prisma · PostgreSQL · Redis | [backend/README.md](./backend/README.md) |
| `infra/` | Docker Compose（PG + Redis on EC2）· Flask healthcheck（CI/CD pilot） | — |

## 部署架構

```
                  GitHub (此 repo / frontend / backend)
                              │ push main
                              ▼
                  ┌───────────────────────┐
                  │   GitHub Actions      │
                  │  CI (test + build) →  │
                  │  CD (OIDC → ECR →     │
                  │       ECS Fargate)    │
                  └───────────┬───────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
       ECS service       ECS service     ECS service
       jko-frontend      jko-backend     jko-healthcheck
              │               │               │
              └───────────────┴───────────────┘
                              │ 同 VPC、私網
                              ▼
                  ┌───────────────────────┐
                  │   EC2 (Ubuntu ARM64)  │
                  │   Docker Compose:     │
                  │   ├── PostgreSQL 16   │
                  │   └── Redis 7         │
                  └───────────────────────┘
```

- **資料層**：EC2 self-host PG + Redis（`infra/docker-compose.yml`），開放給 ECS 走 SG-to-SG 規則的 VPC 私網連線
- **應用層**：三個 ECS Fargate service 共用單一 `jko-cluster`
- **CI/CD**：每個 repo 各有自己的 GHA workflow，三個 repo 共用同一套部署模式（per-repo IAM role + OIDC + ECR + ECS rolling deploy）
- **詳細決策**：見 [ADR 008](./docs/decisions/008-ecs-cicd-pipeline.md)

## 文件

- [`docs/decisions/`](./docs/decisions/) — 專案級 ADR（架構決策紀錄）
- [`docs/prompts/`](./docs/prompts/) — 與 AI 的對話紀錄（raw + 精選版）
- [`docs/tech/`](./docs/tech/) — 技術清單（AWS 服務、設定、月費估算）
- [`CLAUDE.md`](./CLAUDE.md) — Claude Code 專案級指示

## AI 使用聲明

開發過程使用 [Claude Code](https://claude.com/claude-code)（Opus 4.7）輔助。
各子專案 README 內有更細的負責範圍說明。
