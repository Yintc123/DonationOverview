# ADR 012：Frontend 與 Backend payload / enum 命名統一

- **狀態**：Accepted
- **日期**：2026-06-15
- **決策者**：yiqazwsx123@gmail.com (full-stack)
- **影響範圍**：frontend specs 008 / 009 系列；frontend `src/app/checkout/**`；未來 BFF route handler

---

## 1. 背景

Backend spec 020 / 021 / 022（捐款 / 購買 order data model + API）跟 Frontend spec 008（捐款 / 購買 bottom-sheet）+ 009（confirm 頁）在 v0.1〜v0.6 各自獨立演進，造成 6 處 contract drift：

| 概念 | FE v0.6 命名 | BE v0.7 命名 |
|---|---|---|
| 訂單頻率 | `donationType: 'monthly' \| 'oneTime'` | `donationFrequency: 'ONE_TIME' \| 'RECURRING'` |
| 扣款日 | `chargeDay: 6 \| 16 \| 26` (int) | `billingDay: 'DAY_6' \| 'DAY_16' \| 'DAY_26'` (string enum) |
| 收據選項 | 中文 literal 3 值 | `ReceiptOption` 5 值（`NONE` / `INDIVIDUAL` / `CORPORATE` / `GOVERNMENT_DONATION` / `DEFER`） |
| 捐款人姓名 | `donor.name`（nested） | `donorName`（top-level） |
| 匿名旗標 | `donor.isAnonymous`（只 purchase 有） | `isAnonymous`（top-level，三類訂單共用） |
| Endpoint | 單一 `/checkout/donation` 涵蓋 charity+project | 拆三條 endpoint（`/charity-donation`, `/project-donation`, `/sale-item-purchase`） |

額外邏輯 drift：「下次扣款日期」FE 用 client local time + `>=`（含當天），BE 用 UTC + `<`（嚴格小於、當天視已過），每月有 3 天（6/16/26）會錯位。

## 2. 決策

**FE 一律對齊 BE 命名 / enum 值 / payload shape，不引入 BFF mapping 層**。

具體：
- FE form state、reducer Action、URL query params、submit payload 一律使用 BE Prisma enum 字串值（`ONE_TIME` / `RECURRING` / `DAY_6/16/26` / `CHARITY` / `DONATION_PROJECT` / `NONE` / `INDIVIDUAL` / `CORPORATE` / `GOVERNMENT_DONATION` / `DEFER`）
- FE payload field 命名一律對齊 BE 022 body（`donorName` / `amountTwd` / `isAnonymous` / `saleItemId` / `quantity` / `receiptOption` / `donationFrequency` / `billingDay`）
- FE confirm payload 攜帶 FE-side `_endpoint` discriminator，BFF route handler 看 discriminator 路由到對應 BE endpoint、forward 前移除該欄位（BE TypeBox 嚴格 `additionalProperties: false`）
- `nextChargeAt` 計算邏輯對齊 BE 021 §7.7（UTC + 嚴格 `<`），FE confirm 頁顯示用 client function；接 BE 後改用 BE response `nextChargeAt` 為準
- FE 未在 Figma 出現的 BE 欄位（`note`、charity / project 流程的 `isAnonymous` UI）暫不擴 UI、payload 固定送 default（`null` / `false`）

## 3. 考慮過的替代方案

### A. 不動 spec、繼續分歧（lowest cost）
brief.md 寫「不接金流」、submit 只是 `console.log + toast`，drift 在「未來接 BE 時 BFF mapping」階段才需 reconcile，當前 demo 不踩。

**否決理由**：把 mapping 工作延後到「接金流」那個 deadline 最緊的時間點才處理；mapping 層需要為每個欄位寫雙向轉換 + 測試，比一次到位多出 6〜8 個 mapping 函式 + 一輪 review。FE form 命名也跟 BE 文件對不上，bug report / debug 時要在腦中翻譯。

### B. FE specs 加 BE drift 註記、不動命名（medium cost）
保留 FE 既有 `monthly` / `chargeDay` 等命名，在每處出現 drift 的 spec 段落用 footnote 註明「對應 BE XXX」。

**否決理由**：spec 註記容易過期、不會被 lint 守護；實作者跟著 spec 寫 code 時仍然會用 FE 命名，到 BFF route handler 仍需要 mapping。比 A 多了 spec 維護成本但沒解決根本問題。

### C. FE 完全對齊 BE 命名（本決策，highest upfront cost）
本決策採取。upfront 改 6 份 spec（008 + 008b + 008c + 009 + 009a + 009b），現有 8 個 UI primitive 不受影響（純展示、不持業務命名）。

**接受理由**：
- BFF route handler 收到 form payload 後可直接 forward 給 BE，**零 mapping 層**
- spec / FE code / BE code 三邊命名一致，未來新人不需要在心中翻譯 `chargeDay ↔ billingDay`
- FE 測試斷言寫 `expect(payload.donationFrequency).toBe('RECURRING')` 跟 BE integration test 完全平行
- BE Prisma enum 已從 `@prisma/client` 自動產出 TS 字串 union（[BE 022 §4.0](../../backend/docs/specs/022-donation-order-api.md)），FE 沿用同字串即可

## 4. 後果

### Positive
- 零 mapping 層：BFF 不需要為 6 處 drift 寫雙向轉換
- 命名一致：spec / FE / BE 三邊讀同一份字典
- 接金流摩擦更小：未來改 `console.log + toast` → `fetch BFF → forward BE` 只需要加 `_endpoint` 移除邏輯
- BE 已決定的邊界條件（quantity ≤ 100、amountTwd ≤ 1_000_000、donorName 1-120）FE 一次到位，避免 client-side gate 跟 BE constraint 不一致
- nextChargeAt 計算解掉每月 3 天的錯位 bug

### Negative
- 8 個 UI primitive 已 implementation（QtyStepper 預設 `max=99`）；轉 100 需要更新 spec 008c §4.2 + 之後的 component code（單元改動小）。UI primitive 本身（已 commit `2843163`）的 default 仍是 100；spec 008c 對齊一致
- Figma 4888 / 4889 沒「我要匿名捐款」UI 但 BE 三類訂單共用 `isAnonymous`，FE 在捐款流程固定送 `false`；未來 design 補 UI 時需要拉掉 hardcode
- FE 中文文化 literal（「都不需要」「個人」「公司」）改為 value + label 分離（`{ value: 'NONE', label: '都不需要' }`），表達上稍重一點但 i18n-friendly

### Neutral
- FE confirm page URL query params 跟一般 URL design conventions（lower-camel）一致，無變更
- FE path 仍為 `/checkout/donation` + `/checkout/purchase` 兩條，不為了對應 BE 3 條 endpoint 而強行 1:1 拆分（charity / project 共用 UI，由 `targetType` 區分）

## 5. 修訂的 spec 版本

| Spec | 變更前 | 變更後 |
|---|---|---|
| [008 index](../../frontend/docs/specs/008-donation-checkout-sheets.md) | v0.6 | v0.7 |
| [008b DonationSettingsSheet](../../frontend/docs/specs/008b-donation-settings-sheet.md) | v0.4 | v0.5 |
| [008c PurchaseQtySheet](../../frontend/docs/specs/008c-purchase-qty-sheet.md) | v0.4 | v0.5 |
| [009 index](../../frontend/docs/specs/009-checkout-confirm.md) | v0.2 | v0.3 |
| [009a DonationConfirm](../../frontend/docs/specs/009a-donation-confirm.md) | v0.3 | v0.4 |
| [009b PurchaseConfirm](../../frontend/docs/specs/009b-purchase-confirm.md) | v0.3 | v0.4 |

BE 020 / 021 / 022 不動，已穩定於 v0.7。

## 6. 後續工作

- 實作 008b / 008c business sheets + 009a / 009b confirm pages 時依此 ADR 命名
- BFF route handler（`src/app/api/checkout/*`，尚未實作）按 `_endpoint` discriminator route 到 BE
- 接金流時的 mapping 層完全不需要存在
