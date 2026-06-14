# 精選 Prompt:捐款項目資料模型演進(1 表 → 5 表 + 雙語系)

日期:2026-06-14
對應 ADR(均位於 `backend/docs/decisions/`):
- [001-donation-item-relations.md](../../backend/docs/decisions/001-donation-item-relations.md) — Charity / Project / SaleItem 的 1:N FK 關係
- [002-charity-category-model.md](../../backend/docs/decisions/002-charity-category-model.md) — Category M:N + 子表繼承 + 後續 `?category=<key>` 議題 A 收尾
- [004-i18n-storage-model.md](../../backend/docs/decisions/004-i18n-storage-model.md) — 雙語系 suffix columns 設計

對應 spec(均位於 `backend/docs/specs/`):
- [015-charity-data-model.md](../../backend/docs/specs/015-charity-data-model.md) v0.7
- [016-charity-list-api.md](../../backend/docs/specs/016-charity-list-api.md) v0.9
- [017-detail-apis.md](../../backend/docs/specs/017-detail-apis.md) v0.3

---

## 情境

這個 session 的命題很簡單:「根據 Figma 設計,寫資料表 + API 兩份規格書。」

但隨著對話展開,**需求一邊釐清一邊修正**。最終資料表從最初的 1 張變成 5 張,API endpoint 從 1 個變成 4 個,並補上 3 個 backend 級 ADR。整段對話展示了**面對需求變動時,如何用 ADR 把反覆討論的決策定錨**,避免同樣的問題在實作期再吵一次。

關鍵的「翻案」節點:

| # | 議題 | 翻案次數 |
|---|---|---|
| Tab 範圍 | brief 寫「另兩 tab 不切換內容」,後修正為三 tab 皆實作 | 1 |
| 三 entity 關聯 | 各自獨立 → FK → 各自獨立 → FK(回穩)| 3 |
| 分類模型 | 暫定 string → M:N 獨立 Category 表 + 子表繼承 | 1 |
| 分類選項 | 6 個暫定 key → 16 個截圖補件 | 1 |
| 多語系 | 「i18n 預留」開放問題 → suffix columns 實裝 | 1 |
| API filter | `?categoryId=<uuid>` → `?category=<key>` | 1 |

---

## 我的代表性 Prompts

### 1. 起手式

> 可以開始做業務邏輯,透過 figma mcp 會建議如何規劃資料表和 API 請各寫一份規格書

### 2. 第一次翻案(scope)

> 可是列表上方有三個 tab,公益團體 / 捐款專案 / 義賣商品,應該至少每個都需要一張表吧?

(後續發現 frontend brief 有誤、三 tab 皆需實作)

### 3. 第二次翻案(關聯)

> 我剛剛想了一下,這 3 個 tab 各自獨立

### 4. 第三次翻案(回穩)

> 我剛剛想了一下,這 3 個 tab 不是各自獨立,確實是公益團體是主表,有捐款專案和義賣商品兩個子表,再幫我重新仔細評估

### 5. 主動深化(M:N + 子表繼承)

> 點擊「全部」按鈕,會出現一個選單,裡面會有公益團體的分類,所以要新增一張表「公益團體類別」,這張表「公益團體類別」對「公益團體」是 多對多,一個公益類別可以有多個公益團體;一個公益團體可以有多個公益類別,這樣設計合理嗎?

### 6. 加料:多語系

> 資料表幫我考慮到多語系的部分,一般多語系會進資料表嗎? 增加英文的就好

### 7. 議題 A 收尾

> 好,用 key,而且 key 是索引,可以增加查詢速度

---

## AI 產出摘要

整個 session 累積的具體產出:

**3 個 backend 級 ADR**:
- ADR 001:Charity-Project-SaleItem 採 1:N + NOT NULL FK + Restrict cascade(終止三次反覆討論)
- ADR 002:Category 採 M:N + 子表繼承,API 對外用 `key` 對內用 UUID(v0.1 → v0.2 收議題 A)
- ADR 004:多語系 suffix columns(Pattern A),3 patterns 評估(suffix / JSONB / translation table)

**3 個 spec**:
- spec 015 v0.7:資料模型完整 5 張表(charities、donation_projects、sale_items、categories、charity_categories)+ 中英 9 個 nullable 雙語欄位 + 12 個 trgm GIN 索引
- spec 016 v0.9:列表 / 搜尋 API 4 個 endpoint(三 list + 一 categories 字典)、`Accept-Language` header、`?category=<key>` 16 literal union
- spec 017 v0.3:詳情 API 3 個 endpoint,nested charity inflated、ETag 包含 locale

**關鍵的中間迴圈**:

- 每次翻案後,先列「對齊 brief 需動哪些」「對齊 schema 需動哪些」,讓使用者確認影響面再動;不是直接覆蓋
- 第 3 次翻案後我主動寫出 ADR 001 並建議:「**現在這個時間點正是寫 ADR 的最佳時機**:你連續 3 次反轉⋯⋯把『為什麼是 1:N、為什麼 NOT NULL、為什麼不 M:N』鎖在版控裡」
- 議題 A(`?category=<key>` vs `?categoryId=<uuid>`)寫了 14 維度評估(URL 可讀性 / 跨環境穩定性 / TypeScript type / REST 慣例 / 業界例子 / 安全考量等),使用者拍板後立即用 ADR 002 v0.2 鎖定

---

## 我的判斷與後續調整

### 判斷一:接受「反覆時主動寫 ADR」的建議

我自己的決策過程確實是「邊想邊改」,但這對未來的我、對審閱者、對未來協作者都會造成困惑。AI 在我第 3 次翻案後主動提議「現在寫 ADR」是準確的:

- ADR 001 §「不採用三 entity 完全獨立」一節明確記下「v0.3 短暫採用過,理由:技術簡單但違反 domain 語意。**Lesson learned**:DB schema 對 domain 語意應從嚴」— 這段不會在程式碼裡看到,但對下一位讀者極有價值

寫完 ADR 後,我又問「資料庫類別是 M:N 嗎」、「議題 A 怎麼選」這類問題,AI 都能引回 ADR(「ADR 002 已定錨」)而不是重新討論,這正是 ADR 的價值。

### 判斷二:14 維度評估(議題 A)的取捨

AI 對 `?category=<key>` vs `?categoryId=<uuid>` 列出的 14 個維度評估,我覺得**對作業而言過深**(評審不會仔細看到所有維度)。但這個深度展現了:

1. 我在做 API 設計時不是憑直覺,而是逐項對照業界規範
2. 留下了清楚的「未來反悔」路徑(動態化分類時改回 UUID)
3. ADR 把這段濃縮成「14 個維度評估摘要 + 安全考量」一節,既不冗長也不省略

決策本身(用 key)很簡單,深度評估是**留給審閱者驗證的證據**。

### 判斷三:多語系決定 + 立刻 close 開放問題

「i18n 預留」原本是 spec 015 v0.6 §12 的 open question(未實作但提到了)。產品確認「加英文」後,AI 沒只在 v0.7 加欄位,還主動回頭把 spec 015 §12 與 ADR 002 §升級觸發 的 i18n 條目改為 `~~分類本身需 i18n~~ → v0.7 已實現`。

這個小動作很重要 — 沒做的話,open question 會變成「殭屍 question」,新讀者看到會困惑「這個是還沒做還是做了沒清掉」。

### 判斷四:DB schema 與 API 分層

議題 A 收尾時,AI 特別強調:

> 改 `?categoryId=<uuid>` → `?category=<key>` 只動 API contract,DB schema 的 `charity_categories.category_id` FK **維持 UUID 內部 identifier**。

這是 ADR 寫作上的重要分層(對外 contract 改變不必動 DB schema)。換言之,這次決策的「半徑」很小,migration 風險可控。

### 展示重點

這段 session 想呈現的工程判斷:

1. **需求反覆是常態,但要有止損機制**:同樣的問題翻 3 次 → 寫 ADR,以後不再吵
2. **DB schema 與 API contract 分層**:對外名字改 ≠ 對內欄位改;ADR 把這個劃清楚
3. **Open question 不是「永遠開著」**:做完一項就回頭 close,避免殭屍 question
4. **大決策小決策都過 ADR 篩**:即使是「`?category=<key>`」這種看似小決定,因為跨 frontend / BFF / backend 三層,還是值得寫進 ADR(避免日後追問「為什麼用 key 不用 uuid」)

---

## 相關檔案

- ADR:
  - [backend/docs/decisions/001-donation-item-relations.md](../../backend/docs/decisions/001-donation-item-relations.md)
  - [backend/docs/decisions/002-charity-category-model.md](../../backend/docs/decisions/002-charity-category-model.md)
  - [backend/docs/decisions/004-i18n-storage-model.md](../../backend/docs/decisions/004-i18n-storage-model.md)
- Spec:
  - [backend/docs/specs/015-charity-data-model.md](../../backend/docs/specs/015-charity-data-model.md) v0.7
  - [backend/docs/specs/016-charity-list-api.md](../../backend/docs/specs/016-charity-list-api.md) v0.9
  - [backend/docs/specs/017-detail-apis.md](../../backend/docs/specs/017-detail-apis.md) v0.3
- 同步影響:
  - [frontend/docs/brief.md](../../frontend/docs/brief.md)(v0.6,brief 與 spec 對齊)
  - frontend/docs/specs/002 / 004 系列(同步加上 `/donation/` 前綴 與 `?category=<key>`)
- 原始 session 對話:`raw/2026-06-14-session-<id>.readable.md`(session 結束後補上)
