# ADR 003：前端測試框架選用 Vitest

- **狀態**：Accepted
- **日期**：2026-06-13
- **影響範圍**：`frontend/` 單元 / 整合測試

---

## Context

`frontend/` 採 Next.js 16（App Router、Turbopack 預設、ESM-first）+ TypeScript + TanStack Query + Zod，並決定走 TDD 開發流程。

TDD 對 watch mode 速度極度敏感（一天上百次紅綠循環），測試框架選擇直接影響開發節奏。需要在 Vitest 與 Jest 之間擇一作為單元 / 整合測試的 runner。

E2E 測試獨立決定使用 Playwright，本決策不涉及。

---

## Decision

**採用 Vitest 作為單元 / 整合測試框架。**

搭配套件：
- `@vitejs/plugin-react`（JSX transform）
- `@testing-library/react` + `@testing-library/user-event` + `@testing-library/jest-dom`
- `happy-dom`（DOM 環境，較 jsdom 快約 2 倍）
- `@vitest/coverage-v8`（覆蓋率）
- `msw`（攔截 fetch，跨 unit / e2e 共用 handler）

---

## Rationale

### 與此專案高度匹配的關鍵維度

| 維度 | 影響 | Vitest | Jest |
|---|---|---|---|
| ESM 原生支援 | Next.js 16、TanStack Query、Zod 全 ESM | ✅ | ❌ 需 `--experimental-vm-modules` + transform 例外 |
| TypeScript 速度 | 7 天作業，編譯成本敏感 | esbuild，0 設定 | ts-jest 慢 / Babel 不檢查型別 |
| Watch mode 速度 | TDD 紅綠循環 50–200ms vs 1–3 秒 | ✅ Vite HMR-style | ❌ 慢 5–10 倍 |
| 設定成本 | 一份 `vitest.config.ts` 即可 | ✅ | 需 `jest.config` + transform 例外 + babel/ts-jest |
| 與 Next.js 16 範例 | 新版本社群範例 | ✅ 多 | 主流但成長停滯 |

### Vitest 額外加值
- **Jest API 相容**（`describe` / `it` / `expect` / `vi.fn()`），未來換回 Jest 成本低
- **Browser UI**（`vitest --ui`）— 即時測試樹、覆蓋率、單測 rerun
- **`expectTypeOf<T>()`** — 可寫型別測試（與 Zod schema 共用 TS 型別時有用）
- **MSW 支援成熟** — 對 BFF Route Handler 測試友好

### 為何不選 Jest
- Next.js 16 + Turbopack + ESM 環境下，Jest 需可觀的額外設定才能跑（transform 例外清單、`moduleNameMapper`、`testEnvironment` 調整）
- ts-jest 慢、Babel 不做型別檢查；二選一都不理想
- 在「短工期 + 想專注 TDD 節奏」的場景，Jest 的設定成本不值得

---

## Consequences

### 正面
- TDD 開發節奏快（watch mode 響應 < 200ms）
- 設定檔極簡，新人 onboarding 成本低
- 與 Next.js 16 + ESM 生態零摩擦
- API 相容 Jest，未來如需切換成本可控

### 負面 / 取捨
- 團隊熟悉度可能略低於 Jest（但 API 相容降低學習曲線）
- 跨檔案 module isolation 略弱於 Jest（極少情況下可能出現 cache 殘留，需 `vi.resetModules()`）
- Snapshot 在罕見 edge case 行為與 Jest 略異

### 後續工作
- 建立 `vitest.config.ts` 與 `vitest.setup.ts`
- 在 `frontend/CLAUDE.md` 寫入 TDD 規範與測試指令
- CI 加 `pnpm test --coverage` 並設 coverage 門檻

---

## Alternatives Considered

| 方案 | 選 / 不選原因 |
|---|---|
| **Jest** | Next.js 16 + ESM 需大量額外設定；watch 慢；不適合短工期 TDD |
| **Node test runner (`node:test`)** | API 太陽春，缺 mock / snapshot / coverage 整合 |
| **Bun test** | 速度快但對 Next.js / Node lib 相容性仍有變數 |

---

## References

- Vitest 官方文件：<https://vitest.dev>
- Next.js 16 testing 指南：<https://nextjs.org/docs/app/guides/testing>
- MSW：<https://mswjs.io>
