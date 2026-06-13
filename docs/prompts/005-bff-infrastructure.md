# 精選 Prompt：BFF 基礎建設整套實作

日期：2026-06-13
對應 spec：[001 BFF infrastructure](../../frontend/docs/specs/001-bff-infrastructure.md)（含 001a–001g 共 7 份子 spec）

## 情境

Spec 001 系列規畫了 BFF 層完整橫切議題（env config、errors、log、session store、CSRF、backend fetch、route handler wrapper、health/lifecycle endpoints），總計 7 個子 spec、約 2000 行規格。

要把它落成 code 並且確認真的能跑，需要：
1. **TDD 紅綠重構**節奏穩定（CLAUDE.md 強制：邏輯類絕不豁免）
2. **不偷工**——每個子 spec 的「驗收條件 + 測試清單」都要對得起
3. **不對 spec 言聽計從**——spec 可能自相矛盾或落實時暴露 runtime 風險，需要當下判斷
4. **跑得起來**——dev / production build / SIGTERM 都實測，不能只靠單測綠

最後想出來的成果要禁得起 audit：spec、code、runtime 三邊對齊。

## 我的 Prompt

> 依據 @docs/specs/ 以最佳實踐開始實作基礎架構模組

接著一路用「繼續」推進每個子 spec。完成後：

> 仔細審視程式碼和規格書是否有對齊並且運行是否正常？
>
> 以最佳實踐修正
>
> 目前 nextjs 專案能正常運行嗎？

## AI 產出摘要

**實作階段（001a → 001g）**

每個子 spec 各做一個 TDD pass：

1. 動手前先 `AskUserQuestion` 確認範圍（不要假設要做整套）
2. 對每個模組：先寫測試 → `pnpm test` 確認紅 → 寫實作 → 確認綠 → 下一個
3. 7 個子 spec 全部寫完時：**24 test files / 217 tests / lint + typecheck + 無業務字眼全綠**
4. 過程中主動撞到 / 解掉幾個技術坑：
   - `server-only` 套件在 vitest 環境會丟例外 → 加 alias 到 `server-only/empty.js`
   - `Origin` / `Referer` 是 forbidden header，`new Request({ headers: { origin } })` 會被靜默剝離 → 手刻 fake Request
   - iron-session 的 `s.destroy()` 是 `set('', { maxAge: 0 })` 不是 `delete()` → fake cookie store 要模擬瀏覽器語意
   - `vi.hoisted` + getter 切 USE_MOCK 在同檔案測 mock-mode 與 real-fetch
   - 5 並發 refresh 用 InMemoryStore 模擬分散式鎖去重，driving the dedup invariant

**Audit 階段**

完成後並行派 3 個 sub-agent 分別審視 001a-c / 001d-e / 001f-g。設計成「自己不先翻完所有 code」，讓 audit 拿著規格走、找 drift / missing / weak test。

報告整合後找出：
- **2 個真實 bug**：refresh() 沒在 backend 401 UNAUTHORIZED 時 destroy；iron-session 在 USE_MOCK=1 仍需 SESSION_SECRET（規格漏寫）
- **5 條 spec drift**：request-id 用了 base36 不是 base64url；TTLs 硬寫；shutdown deadline 硬寫；log event 名字不對；refresh internal 沒顯式 `session: null`
- **1 條 runtime risk**：`applyNoStore` 用 `res.text()` 會 buffer body
- **3 條 spec **文字**自相矛盾**：001b §5 EXPIRE vs §3 PEXPIRE；001c §3 「回 503」但 001a §2.1 沒有 503；001f §2.3 step 9 「沒 Cache-Control 才補」vs §5.4 「強制覆寫」

**修正階段**

逐條修，同時更新測試。**220 tests** 過綠（增了 3 條：refresh-rejection 整合、ECONNREFUSED/ENOTFOUND classification）。

**Runtime 驗證**

`pnpm dev` → curl `/api/health/live`、`/api/health`、`/api/csrf`、`POST /api/dev/login` → cookie 跑通 → 用 cookie 再打 csrf 看到 `set-cookie` 被 re-issue（驗證 createRoute step 10 `touch()`）→ SIGTERM 觀察到 `bff.shutdown.begin`/`bff.shutdown.clean` 3ms 結束。

`pnpm build` 先失敗（config superRefine 擋 dev 配置進 production，**這是 spec 設計的功能**），shell 覆寫 `ALLOWED_ORIGINS=https://example.com ENABLE_DEV_LOGIN=0` 後成功。

## 我的判斷與後續調整

**判斷一：分批請使用者確認範圍**

啟動時用 `AskUserQuestion` 問「整套 vs 只做 001a」、TDD 嚴格度。217 tests 規模的工作沒對齊就動手會炸。Claude 自己也要習慣這種 cost-aware 對齊。

**判斷二：審視階段並行外包給 sub-agent**

我修完 code 後自己「再讀一遍」效益低（同個腦袋容易看不到自己的盲點）。並行 3 個 sub-agent，每個拿到不同子 spec 範圍，能用 fresh-eyes 找出我自己漏掉的 drift。重點是給每個 agent 「具體要看什麼不變式」，不是丟「幫我 review」。

**判斷三：spec 不是聖經**

Audit 找出的「3 條 spec 自相矛盾」，code 都跟對的那一邊（acceptance criteria 比 prose 重要）。修正後**回頭更新 spec 文字**，避免下個讀者跟著錯。spec 文字漂移如果留著，下次有人改 code 會「按 spec 改回去」反而把 bug 引回來。

**判斷四：runtime 驗證 ≠ 跑單測**

`pnpm test 220 passing` 不代表 dev server 起得來。果然 `pnpm dev` 撞到 iron-session 缺 password（spec 自己沒對齊：USE_MOCK=1 寫 SESSION_SECRET 可缺，但 cookie 路徑一律需要）。如果只信單測就漏抓了。

**判斷五：production build 也要試**

`pnpm build` 額外暴露 superRefine 在 prod 模式守門（dev .env.local 直接 build 會被擋）。這其實是 spec 期望行為，但**沒實際跑過會以為 build 壞掉**。順手加了 `.env.production.example` 範本，讓未來部署有 reference。

## 展示重點

這段工作想呈現的工程判斷：

1. **TDD 不是儀式而是節奏**：紅綠重構保證每個改動都被一個失敗測試「拽出來」，而不是「先寫一大段、最後一次跑」
2. **Sub-agent 是 review 工具**：不是「讓 AI 寫更多 code」，是「讓 AI 用 fresh-eyes 找 review pass 才會抓到的問題」
3. **Spec drift 是雙向問題**：code 可能偏離 spec、spec 文字也可能偏離自己的 acceptance criteria。兩邊都要修
4. **Runtime ≠ 單測**：dev / build / SIGTERM 三段都實測過，才有資格說「能正常運行」

## 相關檔案

實作層（`frontend/`）：
- `src/lib/{api,errors,log,mock,schemas,security,session}/` — Spec 001 全部模組（含 colocated tests）
- `src/lib/lifecycle.ts` + `src/instrumentation.ts`
- `src/app/api/{csrf,health,health/live,dev/login}/route.ts`
- `tests/contracts/session-store.contract.ts`、`tests/helpers/{cookie-store,csrf,backend-mock}.ts`
- `.env.example` / `.env.production.example`

Spec 層（`frontend/docs/specs/`）：
- `001-bff-infrastructure.md`、`001a-foundations.md` ... `001g-routes-and-lifecycle.md`（drift 修正後）

決策層（`docs/decisions/`）：
- ADR 004（auth token strategy）、005（iron-session）、006（Redis-backed session）— 本次實作所依賴
