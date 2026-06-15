#  精選 Prompt:Donation Order 完整領域落地(spec review → 補洞 → ADR → 4-phase 實作 → admin auth → spec 020 §5)

日期:2026-06-15

對應 ADR:
- [013-donation-order-model.md](../decisions/013-donation-order-model.md) — OrderLine pattern + polymorphic FK + 訂單匿名 + Clock 注入 + Order immutability

對應 spec(均位於 `backend/docs/specs/`):
- [021-donation-order-data-model.md](../../backend/docs/specs/021-donation-order-data-model.md) v0.7 — Order header + OrderLine + 5 enum
- [022-donation-order-api.md](../../backend/docs/specs/022-donation-order-api.md) v0.7 — 10 endpoints(6 public + 4 admin)
- [020-donation-write-api.md](../../backend/docs/specs/020-donation-write-api.md) v0.2 §5.1-§5.3 admin write endpoints(本 session 落地實作部分)

對應 backend 實作:
- `src/lib/clock.ts`、`src/domain/order/*`、`src/schemas/order/*`、`src/routes/v1/donation/orders/*`、`src/routes/v1/admin/orders/*`、`src/routes/v1/donation/{charities,donation-projects,sale-items}/admin.ts`、`src/domain/donation-item/{charity,project,sale-item}-write.ts`、`src/lib/cache/invalidate-donation.ts`、`src/lib/auth/role.ts` + `requireAdmin`、Prisma `Account.role` migration

---

## 情境

session 起手是「**目前還未 commit 的規格書足夠完整開發嗎?**」— 表面是 self-review,實際展開成一整套 **spec-driven 完整工程鏈**:

```
1. spec review(顧問:檢出 6 個小空白)
   ↓ 「以最佳實踐修正」
2. spec patch(v0.6 → v0.7,加 clock 注入 / additionalProperties: false / ...)
   ↓ 「commit」
3. 進入 implementation
   ↓ 「根據規格書先從 model 的部分以最佳實踐開發」
4. Phase 1 — schema + migration + clock + validators + next-charge-at
   ↓ 「繼續」
5. Phase 2 — TypeBox bodies + 3 public create endpoints + serializer
   (中途撞到 vi.useFakeTimers() 卡死 Fastify async 的 bug,改 toFake: ['Date'])
   (中途撞到 Fastify Ajv removeAdditional: 'all' 預設使 additionalProperties: false 失效)
   ↓ 「繼續」
6. Phase 3 — GET / confirm-payment / cancel + state machine + idempotency
   ↓ 「繼續」
7. Phase 4 卡關:admin endpoints 需要 admin auth,但 spec 020 v0.2 是 docs only
   ↓ AskUserQuestion「Phase 4 方向?」用戶選 A「先落地 admin auth model」
8. Phase 4-A — Account.role + role.ts + signAccessToken role claim + requireAdmin + seed admin
   Phase 4-B — admin order list / detail / patch / delete + cursor 分頁
   ↓ 「commit + push」
9. 進度報告 → 「實作 2, 3」(ADR + 18 個 admin write endpoints)
   ↓
10. ADR 013(6 個決策 + 風險表)
    spec 020 §5.1-§5.3 落地(Charity/Project/SaleItem 各 6 endpoints)
    共用層:invalidate-donation pure function + lifecycle-actions factory
```

整段對話展示了 **「spec self-review → 補洞 → spec patch → 4 phase TDD-ish 實作 → admin auth 中斷 → AskUserQuestion 收斂方向 → 全 phase 收尾 → ADR 補洞 → admin write API 全套落地」**,核心方法論是:**「規格不夠不寫 code;ADR 不夠不 commit feature;有實測 bug 馬上回去寫 ADR / spec 規約(unfaketimers cookbook → spec 022 §4.0;Ajv removeAdditional → app.ts 註解)」**。

---

## 我的代表性 Prompts

### 1. 起手:spec self-review

> 目前還未 commit 的規格書足夠完整開發嗎?

(預期 AI 把 spec 021 + 022 兩份從頭讀,跟 backend CLAUDE.md 對齊,列出未涵蓋的 dev 細節)

### 2. 收斂:不要列選項,執行最佳實踐

> 以最佳實踐修正

(AI 列了 6 個缺漏 + 各自最佳實踐選項;我直接要它套上,不要再分支)

### 3. 進入 implementation

> 根據規格書先從 model 的部分以最佳實踐開發

(這句話含三層約束:**(a) 規格書是 SoT**;**(b) 從 model 開始**(不是 service 也不是 route);**(c) 最佳實踐自己決定** — 不要列 3 個 option)

### 4. 連續推進 — 「繼續」

> 繼續

(每次 phase 收尾後用,逼 AI 自己 plan 下一 phase 並開動)

### 5. 卡關 → 用 AskUserQuestion 收斂方向

> 繼續

session 進 Phase 4 時,AI 主動發 AskUserQuestion 列三條路:

```
A. 先落地 admin auth model(推薦)— 範圍中等 1-2 hr
B. service 先寫,gate 留 TODO — 半成品風險
C. 停在 Phase 3,先 commit 收尾 — Phase 4 不在 Figma 截圖範圍
```

我選 A,AI 自己列出 5 個子任務(schema + role.ts + signAccessToken + requireAdmin + seed bootstrap)並逐個動工。

> **學到的:** 當 AI 卡在「跨 spec 依賴」這種重大邏輯分支時,主動拋 3 條路給用戶決定,比硬寫下去好太多。

### 6. 完成後的進度報告 + 用戶 cherry-pick

session 接近尾聲時,AI 自發列了「仍待做」清單:
1. spec 020 §3 admin write endpoints(18 個)
2. ADR 013 補洞
3. Prompts 紀錄
4. Frontend 整合

我回:

> 實作 2, 3

(AI 知道 2+3 是哪兩項 — ADR 013 與 spec 020 §3。**不需要再問**)

### 7. session 結尾繼續

> 繼續

(剩下 4 → Category 5 endpoints + Prompts 紀錄寫成 NNN-009)

---

## AI 產出摘要

**Spec 021 + 022 v0.7 patch**(2 commit on backend):
- 6 個 dev gap 一次補齊:Clock 注入規約、admin list inflate 行為、`isAnonymous` default 落點、SALE_ITEM 拒 `receiptOption` 改 schema-level 擋、`note` trim 在 service 層、cancel 風險表
- 移除 v0.5 加的 `RECEIPT_OPTION_NOT_APPLICABLE`(改用 `VALIDATION_FAILED`,單一 source of truth)
- 30 個 spec 修正全部一次 commit,無 incremental noise

**Implementation 4 phase**(`a8d1c67` 一個整合 commit):
- Phase 1: schema(Order + OrderLine + 5 enum + reverse relation)+ migration + trgm re-assert + `lib/clock.ts` + `domain/order/{validators,next-charge-at}` + 57 unit tests
- Phase 2: TypeBox bodies(strict `additionalProperties: false`)+ `domain/order/{line-builder,include,serialize,create-services}` + 3 public POST endpoints + 21 integration tests
- Phase 3: `domain/order/{query,lifecycle}-services` + GET / confirm-payment / cancel + atomic conditional update + 12 integration tests
- Phase 4-A: `Account.role` migration + `lib/auth/{role,bearer}` + `signAccessToken` role claim + `requireAdmin` + seed admin
- Phase 4-B: `domain/order/admin-services` + 4 admin endpoints + 19 integration tests

**ADR 013**(`53c899d` on root):6 個決策 + 風險/緩解表,把本 session 學到的「`vi.useFakeTimers()` 卡 Fastify async 是實測 bug → J 是學費換來的決策」明確寫進文件。

**Spec 020 §5.1-§5.3 admin write endpoints**(`1bda568` on backend):
- 共用層:3 個 error codes + `lib/cache/invalidate-donation.ts`(純函式列出 DEL 鍵 + 11 unit tests)+ `domain/donation-item/lifecycle-actions.ts` generic factory
- 18 個 endpoints(Charity / Project / SaleItem 各 6 動作)
- 30 個 entity-specific integration tests

**Test 累積成果**:556 unit / 302 integration(20 file),typecheck + lint clean。

---

## 我的判斷與後續調整

### 1. spec patch 前一定先 review

「足夠完整開發嗎?」這個 prompt 是本 session 最高 ROI 的一句。**AI 列出的 6 個 gap 全部命中**,如果直接進 code 會在 Phase 2 全部撞到(particularly clock 注入跟 additionalProperties: false 兩個 — 兩個都是 Phase 2 開發時 reproduce 出來 bug 才回頭補的)。

### 2. 不要列 option,要結論

每次只問「最佳實踐是哪個」AI 都會列 3 個 option + 推薦,但這浪費時間。**「以最佳實踐修正」這種 prompt** 直接逼結論,效率高 3-5 倍。

### 3. 「繼續」可以推進但不能取代決策

「繼續」適合 phase 收尾後推進下一 phase。但**跨 spec 依賴**這種重大分支(Phase 4 需要 spec 020 admin auth),AI 自己 trigger AskUserQuestion 是正確的 — 我不能假設 AI 認得「先落地依賴」是當前最佳路徑。

### 4. 撞 bug 馬上回去補 spec / ADR

`vi.useFakeTimers()` 卡 Fastify async 是 Phase 2 跑 integration test 才發現的,我**沒有放著等下次撞**,而是立刻:
- 把 `{ toFake: ['Date'] }` 寫進 spec 022 §4.0
- 把 Clock 注入決策的「為什麼選 J」寫進 ADR 013(把 1.5 hr 學費明確標出)
- spec 022 §10 加進 integration test case 表(下次 review 時看到)

同理 Fastify Ajv `removeAdditional: 'all'` → app.ts 加註解 + spec 022 §4.0 規約。

**規約跟著 code 走,而不是反過來** — code 先撞到的事,規約沒有就是規約沒寫完,馬上補。

### 5. 一個 spec 跨 session 落地時,精選 prompt 主題挑「整套工程鏈」

008-cache-strategy.md 教我的:精選 prompt 不要選「單一決策點」,要挑「**從規格疑問 → ADR → spec → TDD → 順手修 bug → commit/push** 整套鏈條」,因為這才能展現 AI 與規格制度配合的方法論價值。本次 009 比 008 還長一個量級(4 phase + 2 個 spec + 1 個 ADR + 18 個 admin endpoints),但主軸一樣:**規格驅動,撞 bug 回補,ADR 鎖決策,TDD 鎖實作**。

---

## 學到的(meta-process)

1. **「足夠完整開發嗎?」是 spec 階段最有價值的 prompt**。它強制 AI 把 spec 與 CLAUDE.md / 既有 code 做 diff,列出未明確的點。比直接進 code 省非常多時間。
2. **不要讓 AI 一直列 option** — 用 「以最佳實踐修正 / 開發」這種 prompt,逼它從選項收斂到決策。
3. **AskUserQuestion 是 AI 該主動發 trigger 的訊號** — 跨 spec 依賴 / 範圍爆炸 / 不確定方向的時候,讓使用者決定,不要硬寫下去。
4. **整合 commit + 結構化 message** 比強切多 commit 對 demo / review 更友善,只要 message body 列清楚每 phase 範圍。本次 commit `a8d1c67` 跨 4 phase 一次落地,reviewer 看 message 就能精準導航。
5. **ADR 補洞要把實測 bug 寫進去**(本次「`useFakeTimers` 卡 Fastify async 是 1.5 hr 學費」明文記錄)。未來如果有人想優化 clock 注入回 `new Date()`,這段註解會擋住。
