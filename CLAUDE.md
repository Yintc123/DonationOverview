# CLAUDE.md — 專案級指示

本檔為 Claude Code 在本專案啟動時自動讀取的指示。

---

## 專案脈絡

- 名稱：JKODonation — 2026 全端面試作業（web）
- 結構：
  - `frontend/` — Next.js 16 (App Router, Turbopack, React Compiler) + BFF（獨立 git repo）
  - `backend/` — 預計 NodeJS + Express/Fastify + Prisma（獨立 git repo，未建立）
  - `docs/` — 專案層級文件（ADR、prompts）
- 設計稿：Figma《2026 全端面試作業 - web》，file key `0kx2Ne2rvndhfVr3uVUwad`
- 使用者對 Figma 檔案僅有 **Viewer + comment** 權限

## Figma 設計查詢

- 使用社群版 `figma-developer-mcp`（已透過 `.mcp.json` 設定，需 `FIGMA_API_KEY`）
- 不採用官方 Dev Mode MCP（需 Dev/Full seat，權限不符）
- 安裝決策見 `docs/decisions/001-figma-mcp.md`

## Prompts 紀錄（重要）

開發過程中與 AI 的對話依《Coding with AI》要求需保留：

1. **每次 session 結束**：將該 session 的 JSONL（位於 `~/.claude/projects/-Users-yintengching-Projects-JKODonation/*.jsonl`）複製到 `docs/prompts/raw/`，並以 `jq` 萃取為 `.readable.md`（指令範本見 `docs/prompts/README.md`）
2. **重大決策完成後**：主動建議使用者將該段對話寫成 `docs/prompts/NNN-<topic>.md`（含情境、Prompt、產出、判斷）
3. **平時不要打擾使用者**：raw 複製可以等到使用者主動要求或在 session 結束建議；精選版在「明顯的決策節點」後再提出

> 註：完整自動化（hook on Stop event）尚未設定；目前依靠 Claude（你）主動提醒。

## 文件結構約定

- `docs/decisions/` — 專案級 ADR（架構決策紀錄），作業要求至少 3 個
- `docs/prompts/` — Prompt 紀錄（raw + 精選）
- `docs/tech/` — 技術清單（AWS 服務清單、第三方依賴、成本估算等）
- `frontend/docs/brief.md` — 前端需求書（作業原文 + 範圍）
- `frontend/docs/architecture.md` — 前端架構（BFF、資料流）
- `frontend/docs/specs/` — 實作規格（API、UI 行為）
- `frontend/README.md` — 入口（含 AI 使用聲明）

新建文件前先檢查上表，避免內容放錯位置。

## 安全規則

- **絕對不要** 把 `FIGMA_API_KEY` 或任何 token 寫進可能被 commit 的檔案
- `.env`、`.mcp.json` 已在 `.gitignore`，但寫入文件 / README 仍是常見洩漏路徑——保持警覺
- 若發現使用者貼出 token，立刻提醒並建議 revoke

## 提交方式

- 兩個獨立 git repo（`frontend/`、`backend/`）
- 根目錄 git repo 保留專案層級文件（`docs/decisions/`、`docs/prompts/`、`CLAUDE.md`、`.mcp.json` 設定樣板等）
- commit message 使用簡短英文 imperative + Co-Authored-By Claude

## 行為偏好

- 回覆使用繁體中文（除非使用者改用其他語言）
- 簡潔直接，避免冗長前言
- 重要決策節點提醒使用者考慮：是否寫 ADR、是否更新 prompts 紀錄
