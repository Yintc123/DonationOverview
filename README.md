# JKODonation

2026 全端面試作業（web）— 捐款項目列表（公益團體）。

> 設計稿：Figma《2026 全端面試作業 - web》

## AI 使用聲明

本專案（含 `frontend/`、`backend/`、`infra/`）開發過程使用 AI 工具輔助。

### 使用的 AI 工具
- Claude（[Claude Code](https://claude.com/claude-code) CLI，模型：Opus 4.8）

### AI 角色
技術選型討論、ADR 撰寫、骨架生成、code review、按規格 TDD 實作。

### 人工角色
需求理解、架構決策、實作驗收、安全審查、跨 spec 一致性把關。

### Prompt 紀錄
保存於 [`docs/prompts/`](./docs/prompts/)（raw JSONL + 精選 Markdown）。各子專案 README 內有更細的負責範圍說明。

## 結構

本 repo 為**專案層級總目錄**，`frontend/` 與 `backend/` 各自為獨立 git repo；`infra/` 與專案級文件（`docs/`、`CLAUDE.md`）則直接屬於本 repo。

| 子專案 | 技術棧 | Repo |
|---|---|---|
| `frontend/` | TypeScript · Next.js 16（App Router）· TailwindCSS · BFF（iron-session + Redis + CSRF） | [DonationFrontend ↗](https://github.com/Yintc123/DonationFrontend/) |
| `backend/` | TypeScript · Fastify · Prisma · PostgreSQL · Redis · S3 | [DonationBackend ↗](https://github.com/Yintc123/DonationBackend/) |
| `infra/` | Docker Compose（PG + Redis on EC2）· Flask healthcheck（CI/CD pilot） | 本 repo `infra/` |

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
- **CI/CD**：`frontend` / `backend` 各自 repo 有自己的 GHA workflow；本 repo 則承載 `infra/` 與 healthcheck 的部署 workflow（`.github/workflows/deploy-healthcheck.yml`）。三者共用同一套部署模式（per-service IAM role + OIDC + ECR + ECS rolling deploy）
- **詳細決策**：見 [ADR 008](./docs/decisions/008-ecs-cicd-pipeline.md)

## 文件

- [`docs/decisions/`](./docs/decisions/) — 專案級 ADR（架構決策紀錄）
- [`docs/prompts/`](./docs/prompts/) — 與 AI 的對話紀錄（raw + 精選版）
- [`docs/tech/`](./docs/tech/) — 技術清單（AWS 服務與月費估算、瀏覽器 secure-context / HTTPS 需求）
- [`CLAUDE.md`](./CLAUDE.md) — Claude Code 專案級指示

