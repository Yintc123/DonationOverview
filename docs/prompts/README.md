# Prompts 紀錄

本資料夾保留專案開發過程中與 AI 工具（主要為 Claude）的對話紀錄。

對應作業要求《Coding with AI》C 項：提供 2–3 個代表性 Prompt 對話。

---

## 結構

```
docs/prompts/
├── README.md                     # 本檔
├── raw/                          # 全量 session 紀錄（原始 JSONL + 可讀 markdown）
│   ├── YYYY-MM-DD-session-<id>.jsonl
│   └── YYYY-MM-DD-session-<id>.readable.md
└── NNN-<topic>.md                # 精選的代表性 prompt（人工挑選 + 加註）
```

## 工作流程

1. **平時**：每次 Claude Code session 結束後，將 `~/.claude/projects/<project>/*.jsonl` 複製進 `raw/`
2. **繳交前**：從 `raw/` 中挑 2–3 段最具代表性的對話，寫成 `NNN-<topic>.md`，加上：
   - 情境（為何需要這段對話）
   - 我的 Prompt
   - AI 產出摘要
   - 我的判斷與後續調整
3. 精選版才是給審閱者看的；`raw/` 是審閱者若想驗證的全量證據

## 精選候選（待整理）

- Figma MCP 選型（社群版 vs 官方）
- BFF 架構決策（Next.js 為何也兼當 BFF）
- 文件結構重組（specs / brief / architecture / README 的職責劃分）

## 已完成

- [004-orm-prisma-vs-typeorm.md](004-orm-prisma-vs-typeorm.md) — ORM 選型補正(對應 ADR 007)
- [005-bff-infrastructure.md](005-bff-infrastructure.md) — BFF Spec 001 整套 TDD 實作 + audit + 修正(對應 frontend/docs/specs/001-*)
- [006-ecs-cicd-pilot.md](006-ecs-cicd-pilot.md) — Flask healthcheck 跑通 GHA → ECR → ECS Fargate pipeline(對應 ADR 008)

## 命名規則

精選檔：`NNN-<kebab-topic>.md`，例：
- `001-figma-mcp-selection.md`
- `002-bff-architecture-decision.md`
- `003-docs-structure.md`

raw 檔：`YYYY-MM-DD-session-<id>.{jsonl,readable.md}`
