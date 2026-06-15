# 決策:Donation Order 採 Order header + OrderLine 線項 + polymorphic FK,訂單不關聯 Account,Clock 從外部注入

日期:2026-06-15

## 背景

Figma 補件 IMG_4885 / 4886 / 4887 / 4888-4890 揭露三類「點擊捐款 / 購買 → modal → 確認 → 下一步」訂單流:對 Charity 單次或月扣捐款、對 DonationProject 同上、對 SaleItem 購買含數量 / 總計。三類訂單在 UI 是分明的端點,在資料層需要決定要不要共用同一個 `Order` 表、subject 多型用 typed FK 還是 opaque reference、訂單要不要關聯使用者 Account、`nextChargeAt` 等時間敏感欄位的計算流程要怎麼維持可測。

反覆出現的疑問:

1. Charity / Project 捐款只有 1 條 subject;SaleItem 購買也可能 N 條(雖然本期限 1)— 全部走同一個 `Order + OrderLine[]` 結構,還是讓 donation 把 entity FK 直接放在 Order 上、sale 用單獨 `OrderItem` 表?
2. OrderLine 多型怎麼接 3 個不同 entity?開三個 nullable typed FK 嗎,還是用 `subjectType + subjectId` 的 opaque reference?
3. 訂單要不要綁 Account?「end user 不登入也能捐」這個 UX 在 Figma 沒有 auth wall。
4. RECURRING 訂閱要不要立刻拆 `RecurringDonation` 表 + cron 自動扣款?本期沒實作扣款 cron。
5. `nextChargeAt` 計算用什麼 clock?`new Date()` 直接 call 會讓「同一日 vs 同月已過」邊界的測試只能靠 `vi.useFakeTimers` 全域 mock,而 `useFakeTimers` 預設也 fake `setImmediate` / `queueMicrotask`,實測會卡死 Fastify async 啟動。
6. 訂單成立後 `nextChargeAt` / `amountTwd` / `lines` 可不可以改?admin PATCH 是否允許?

問題 1-2 是「資料結構是否未來可擴」的取捨;3 是業務 / UX 對齊;4-6 是「為演進保留接點而不過度設計」。本 ADR 把這六條一次定錨,讓 spec 021 / 022 的所有規約有據可循。

候選方案需滿足的約束:

- 不違反 backend ADR 002(Fastify + 端到端型別)— polymorphic 設計不能拋棄 Prisma client 的型別保障
- 不違反 backend ADR 006(lifecycle / cascading visibility)— Subject 表已 archived 時下單必須 404
- 不違反 backend CLAUDE.md「可 mock 時間 / 隨機:vi.useFakeTimers、注入 clock / id 產生器」測試政策
- 不為本期不會發生的場景(cron 扣款、cart 多 line)過度設計

## 選項評估

### 1. Order 結構:OrderLine pattern vs Order 直帶 entity FK

| 方案 | 描述 | 利 | 弊 |
|---|---|---|---|
| A. Order 直接帶 `charityId? / donationProjectId? / saleItemId?` + sale 走另一張 `OrderItem` 表 | donation 1 條 FK 在 header,sale 開 OrderItem | 對 donation 看似最直觀 | ❌ donation 與 sale 在資料層走兩種 shape;❌ 加新 subject type(EventTicket / Membership)要同時改 Order 表 + 5 處 code(invariant / validator / create-service / API body / OpenAPI);❌ 未來開 cart 混合單(donation + sale 同單)= 結構重寫 |
| **B. Order header + OrderLine 線項**(採用) | Order 變 entity-agnostic header,所有 subject 走 `OrderLine.subjectType` + polymorphic FK | ✅ 三類訂單同一個 shape,response / detail / admin list 邏輯收斂;✅ 加新 subject type 摩擦集中於 OrderLine 一個表;✅ 未來 cart 多 line + 混合單只需放寬 schema 約束(`lines.length` 上限),不重構 |  Phase 1 OrderLine 上限為 1 條,1 對 1 看起來「過度抽象」;但這只是暫時,未來 cart 落地就值回 |

→ **採方案 B**。A 的代價在每加一個 subject 都散在多檔,B 的「暫時 1 對 1」成本只是一個 invariant assertion(spec 021 §7.4)。

### 2. OrderLine 多型對應:typed nullable FK vs opaque subjectId

| 方案 | 描述 | 利 | 弊 |
|---|---|---|---|
| **C. 3 個 nullable typed FK + `subjectType` discriminator**(採用) | `charityId? + donationProjectId? + saleItemId? + subjectType: enum` | ✅ DB FK constraint 保 integrity(寫不存在的 subjectId 直接 reject);✅ ON DELETE Restrict 防止 charity hard delete 後 OrderLine 變孤兒;✅ Prisma client 自動推導出 `line.charity / line.donationProject / line.saleItem` 三個 typed accessor,inflate 不需 polymorphic dispatcher;✅ admin list 查「這間 charity 收到多少訂單」直接 `where: { charityId }`,有 index 命中 | 加新 subject type 仍需 schema migration(加 nullable FK + enum value);但摩擦集中在 OrderLine 一個表 |
| D. Opaque reference:`subjectType + subjectId: string` | 沒 FK,application-level integrity | 加 subject type 不需動 schema | ❌ DB 不擋寫到不存在的 subjectId;❌ 沒 ON DELETE 行為,parent 表 hard delete 後 OrderLine 變孤兒;❌ Prisma client 失去型別,polymorphic dispatcher 散在 read path;❌ cascading visibility 邏輯(spec 015 §3.3)要全應用層手寫補 |

→ **採方案 C**。D 適合「subject 類型超頻繁變動」的 SaaS 多租戶情境,本作業的 3 種 subject 集合穩定,FK 帶來的 DB 級保障值得 schema migration 成本。

### 3. 訂單與 Account 的關聯:綁定 vs 完全匿名

| 方案 | 描述 | 利 | 弊 |
|---|---|---|---|
| E. 訂單 FK 到 Account,end user 必須註冊登入 | `Order.accountId` NOT NULL | 訂單有歸屬 | ❌ 與 Figma 揭露的「點下捐款 → 馬上填 modal → 下一步」UX 直接衝突(無 auth wall);❌ 強制註冊會嚴重壓低小額單次捐款轉換率;❌ 演示作業引入 user account 管理(忘記密碼 / 收據寄送)→ 範圍爆炸 |
| **F. 完全匿名,`donorName` 自由字串**(採用) | Order 不引用 Account,僅存 `donorName VarChar(120) + isAnonymous Boolean`;Account 表此後只服務 admin(role=0) | ✅ 對齊 Figma UX 與 demo 範圍;✅ admin auth model(spec 020 v0.2)落地後 Account 表只剩單一用途,語意清楚;✅ 未來真要 end-user 帳號,加 `Order.accountId String?`(nullable)+ 漸進 migration 即可 | 同名捐款者無法區分(管理面);訂單查詢需要分享 orderId(UUID 不可枚舉,§2.1 風險) |

→ **採方案 F**。E 推翻整個 demo 流程設計;F 把「end-user 帳號」這個高複雜度議題遞延到未來真有 retention 需求時。

### 4. RECURRING 訂閱:獨立表 + cron vs 同 OrderLine 兩欄

| 方案 | 描述 | 利 | 弊 |
|---|---|---|---|
| G. 新建 `RecurringDonation` 表 + 每月 cron 自動扣款 | 訂閱拆獨立 entity,衍生 Order 反引用 | 完整訂閱模型 | ❌ 本期沒實作扣款 cron;訂閱表沒有真正的下游 transaction;❌ 為「本期不會發生的事」建模型,structure 跑在前面 |
| **H. OrderLine 上加 `donationFrequency + billingDay`**(採用) | 訂閱用 `frequency=RECURRING + billingDay=DAY_26` 表達 | ✅ 完整表達使用者意圖(IMG_4886 確實只有「每月哪天扣」);✅ 一個 row = 一個訂閱意圖,沒有空表;✅ 未來真做扣款時升 `RecurringDonation` 表 + cron service,本期 schema 不破壞性變動 |  RECURRING 與 ONE_TIME 共用同一 OrderLine shape(`billingDay` 用 nullable 區分),invariant assertion 多一條(spec 021 §7.2) |

→ **採方案 H**。G 的成本立刻發生但收益要等 cron 落地。H 用兩個欄位完整表達意圖,演進路徑清晰。

### 5. Clock 來源:`new Date()` 直接呼 vs 注入

| 方案 | 描述 | 利 | 弊 |
|---|---|---|---|
| I. service 內 `new Date()` 直接呼 | 與既有 `getCachedCharityById` 的 `now: new Date()` 慣例一致 | 寫起來最短 | ❌ `computeNextChargeAt(now, billingDay)` 的 4 邊界 case(spec 021 §7.7 表)需要固定時間才能測;❌ 唯一可 mock 路徑是 `vi.useFakeTimers()` 全域,但其預設 fake `setImmediate / queueMicrotask`,實測會卡死 Fastify async 啟動(Phase 2 開發時撞到);❌ 即使切到 `vi.useFakeTimers({ toFake: ['Date'] })` 也是「全域注入」,任一忘了 reset 會污染後續 test |
| **J. service 函式接 `deps.clock: () => Date`**(採用) | production 由 Fastify decorator `app.clock = systemClock`,test 直接傳 fixed `Date`(`vi.useFakeTimers({ toFake: ['Date'] })` 仍可選用於 e2e level)| ✅ 純函式 `computeNextChargeAt` 接純資料,單 test 不需 mock 全域;✅ 對齊 backend CLAUDE.md「可 mock 時間 / 隨機:注入 clock」;✅ 未來把 cron 拆出來時直接傳一個會 advance 的 clock 跑 simulation 測試 | 多一個 `app.clock` decorator + service signature 多一個 deps;成本一次性 |

→ **採方案 J**。實際 Phase 2 開發時用 I 路線觸過 `useFakeTimers` 卡死整個 fastify route registration 的 bug,J 是 1.5 hr 的學費換來的決策。

### 6. Order immutability:`nextChargeAt` / `amountTwd` / `lines` 是否允許 admin PATCH

| 方案 | 描述 | 利 | 弊 |
|---|---|---|---|
| K. admin PATCH 可改任何欄位 | 包含 amountTwd / lines / nextChargeAt | 最大彈性 | ❌ 訂單是會計事實紀錄,「事後改金額」會破壞統計與稽核基礎;❌ `nextChargeAt` 是 derived 欄位(`computeNextChargeAt` 公式),admin 直接改會與下次 cron 計算結果不一致;❌ `lines` 是 1 對多 child rows,partial update 邏輯複雜且 race-prone |
| **L. PATCH 限制白名單 7 欄;`amountTwd / lines / nextChargeAt / id / createdAt / updatedAt` 不可改**(採用) | admin 只能改 `status / donorName / isAnonymous / note / receiptOption / paidAt / cancelledAt`;`nextChargeAt` 由 create 算一次後 immutable | ✅ 訂單成立後內容不可動,符合會計常規;✅ admin 仍可修正客戶姓名 / 改 status 處理退款 / 更正收據;✅ 未來真要改金額走 DELETE + 重建(留 audit trail) | admin UI 看似限制多;但 demo 不需要 |

→ **採方案 L**。`nextChargeAt` 的「只算一次,任何 PATCH 都不重算」規約寫進 spec 021 §7.7 v0.6 + invariant assertion(§7.6)— 違反 = 500 InvariantError。

## 決定

採用 **B + C + F + H + J + L** 組合(下稱「donation order 標準模型」):

1. **Order header + OrderLine 線項**(B):Order 為 entity-agnostic header,所有 subject 細節下到 OrderLine,本期 line.length === 1 但 schema future-proof
2. **OrderLine polymorphic typed FK + discriminator**(C):`charityId? / donationProjectId? / saleItemId? + subjectType` enum,DB FK 保 integrity,Prisma 客戶端自動 type
3. **訂單匿名,Account 表只服務 admin**(F):`donorName` 自由字串 + `isAnonymous` boolean;backend response 一律回原樣,anonymisation 由 BFF / UI 端
4. **RECURRING 同 OrderLine 兩欄表達**(H):`donationFrequency + billingDay`;`nextChargeAt` 由 service 算一次,本期不做 cron
5. **Clock 從外部注入**(J):`src/lib/clock.ts` 暴露 `systemClock`,Fastify `app.clock` decorator 注入 production,test 走 fixed Date
6. **Order immutability**:admin PATCH 限白名單 7 欄;amount / nextChargeAt / lines 不可動

實作落地於:
- `prisma/schema.prisma` Order + OrderLine + 5 enum(spec 021 §3)
- `prisma/migrations/20260615082106_add_donation_orders/migration.sql`
- `src/lib/clock.ts`
- `src/domain/order/` — validators / next-charge-at / line-builder / include / serialize / create-services / lifecycle-services / query-services / admin-services
- `src/schemas/order/` — body / response / admin schemas
- `src/routes/v1/donation/orders/` 與 `src/routes/v1/admin/orders/`(spec 022)

## 為什麼這個組合

| 取捨 | 結論的核心理由 |
|---|---|
| OrderLine pattern | 三類訂單 + 未來 cart 混合單一個 shape 走到底,避免每加 subject 就重構 |
| Polymorphic typed FK | DB integrity 與 Prisma 型別不能拋棄;subject 集合穩定,migration 成本可接受 |
| 訂單匿名 | Figma 沒 auth wall;捐款場景 conversion rate 決定不能加註冊步驟;Account 表只服務 admin 後語意更乾淨 |
| RECURRING 兩欄 | 完整表達使用者意圖,未來 cron 落地不破壞 schema |
| Clock 注入 | 純函式 + DI;`useFakeTimers` 卡 Fastify async 是實測 bug,J 是學費換來的;對齊 CLAUDE.md 測試政策 |
| Order immutability | 訂單是會計事實紀錄;`nextChargeAt` 為 derived 不能繞過 service 寫 |

## 風險與緩解

| 風險 | 緩解 |
|---|---|
| 加新 subject type(EventTicket / Membership)仍需 schema migration | 摩擦集中在 OrderLine 一個表 + validators 一個 switch case,比方案 A 散在 5 處可接受 |
| Phase 1 line.length === 1 看起來「過度抽象」 | spec 021 §7.4 invariant assertion 鎖死,違反 = 500;未來放寬只需刪這條 assertion |
| Account 表未來真要服務 end-user 時 | 加 `Order.accountId String?` nullable + 應用層 link logic,既有匿名訂單不受影響 |
| `useFakeTimers` 全域 fake 仍可能在 e2e / integration test 用錯模式 | spec 022 §4.0 / spec 021 §7.7 範本 + Phase 2 / Phase 3 integration test 內全部用 `{ toFake: ['Date'] }` |
| admin PATCH 白名單漏欄位 → 不能修正某些客戶問題 | 走 DELETE + 重建 + audit log;極端情況 admin 直接 DB 改(留 manual audit) |

## 適用範圍

- 本 ADR 鎖定 Donation Order 領域,**不**影響既有 Account / Charity / DonationProject / SaleItem / Category 的設計
- spec 015 / 016 / 017 的 lifecycle cascading visibility 規約對 OrderLine FK 仍適用:create-service 在 lookup subject 時用 `whereLive` / `whereLiveWithParent`,subject expired → 404
- 未來真實 payment gateway 落地時,本 ADR 的 J(Clock 注入)直接適用於 webhook handler(signature 驗證 + idempotency window 都需要 deterministic time)
