# 精選 Prompt:Public Read API 的 Redis Cache 策略(ADR → spec → code → bonus bug fix)

日期:2026-06-15
對應 ADR:
- [011-cache-strategy.md](../decisions/011-cache-strategy.md) — adapter 層 + cache-aside + 熱門白名單 + TTL 表 + stampede 暫不啟用 + 失效 API 預留

對應 spec(均位於 `backend/docs/specs/`):
- [019-cache-policy.md](../../backend/docs/specs/019-cache-policy.md) v0.2

對應 backend 實作:`src/lib/cache/*`、`src/services/cached-*`、四個 route handler 換接,以及一個過程中發現的 `buildKey` 雙前綴 bug 順手修掉。

---

## 情境

session 命題是「**後端 GET API 哪些適合放在 Redis 做 cache?**」— 表面是諮詢,實際展開成一條**完整工程鏈**:

```
顧問問答(7 個 GET 端點 × 是/否/條件)
  ↓ 「將適合的都加 cache,最佳實踐?」
最佳實踐諮詢(adapter 層 vs route vs domain;cache-aside vs write-through)
  ↓ 「最佳實踐該選哪個?」(用戶連問 3 次)
逼出收斂決策(C + cache-aside + 熱門白名單)
  ↓ 「以最佳實踐建立規格書」
spec 019(規格)
  ↓ 「最佳實踐該選哪個?」(再次追問,讓我決定下一步)
ADR 011(決策依據,擋在 code 之前)
  ↓ 「以最佳實踐開始」
TDD 落地(8 步:keys → json → withCache → 4 個 service → route 切換)
  ↓ 過程中 integration test 暴露 buildKey 雙前綴 bug
順手 fix(redis):drop double-prefix in buildKey
  ↓ 「commit 後 push」
3 commits across 2 repos
```

整段對話展示了 **「使用者連續追問『最佳實踐是哪個?』時,如何用 ADR + spec 制度把決策定錨,再用 TDD 鎖實作,並接住中途發現的相鄰 bug 一起處理」**。

---

## 我的代表性 Prompts

### 1. 起手式:顧問問答(範圍探索)

> 後端 GET API 哪些適合放在 REDIS 做 cache?

(預期 AI 列出端點清單 + 判斷標準 + 建議)

### 2. 實作意圖:從諮詢轉為動工

> 將適合的 API 都用 redis cache 並且 redis 沒資料在讀 pgdb,從 pgdb 拿到資料後再寫入資料庫,該如何最佳實踐?

(要求最佳實踐,但 AI 給的是「3 個架構選項 + 推薦」的形式,還沒收斂)

### 3. 收斂施壓 #1

> 最佳實踐該選哪個?

(逼 AI 從 3 選 1,給出單一明確答案 + 為什麼不選 A、為什麼不選 B)

### 4. 認可 + 進規格書

> 那以 C 並且以最佳實踐建立規格書

(用 C 開 spec 019)

### 5. 收斂施壓 #2(在多個下一步選項間)

> 哪個是最佳實踐?

(我列了 ADR / prompts / code 三個下一步,AI 選 ADR 並解釋為什麼必須先 ADR 才 code)

### 6. 認可 + 開始

> 以最佳實踐開始

(寫 ADR 011)

### 7. 進入 TDD 落地

> 繼續

(按 spec 019 §13.1 8 步逐項 red → green;每步收任務、跑回歸)

### 8. 接住相鄰 bug

> 修正 1 和執行 2

(整段結尾我列了 3 件 follow-up;用戶選擇處理 1 + 2,放掉 3)

### 9. Ship

> 好 commit 後 push

(3 commits,2 repos)

---

## AI 產出摘要

整個 session 累積的具體產出:

**1 個專案級 ADR**(`docs/decisions/011-cache-strategy.md`):
- 6 個 trade-off 各列選項表 + 採用理由(架構位置 / cache 模式 / list 範圍 / TTL 數值 / stampede 立場 / 失效策略)
- 7 條「理由」章節,每條對應一個會被反覆質疑的點
- 後續觀測驅動啟用條件 + 7 項 follow-up

**1 個 backend 級 spec**(`backend/docs/specs/019-cache-policy.md`):
- 14 章,從架構決策到 TDD 測試規約全包
- key schema(`cache:<resource>:<sub>:v{n}:<segments>` 含 schema bump 規則)
- TTL 表(categories 600s / detail 60s / list 30s)
- 熱門白名單規則(§4.2)+ 為什麼不全 cache(§3.3)
- 不變式三條(降級不可 5xx / 不可改 shape / 不可改 header)+ 對應測試

**Backend 實作**(完整 cache 層):
- `src/lib/cache/{keys,json,with-cache,index}.ts` + 對應 unit + integration test
- `src/services/cached-*.ts` × 4(category + 3 個 charity/project/sale 各含 detail + list 熱門白名單)
- 4 個 GET route handler 換接(detail × 3 + list × 3 + categories)
- 4 個新 integration test 檔案 + 2 個 donation-api 既有測試契約更新

**Bonus bug fix**:
- 發現 `src/lib/redis/key-prefix.ts` 的 `buildKey` 把 `APP_PREFIX` 寫進回傳值,跟 ioredis 的 `keyPrefix` 重複,造成所有 auth / rate-limit key 在 Redis 實際是 `jkod:jkod:...`
- 一個 `fix(redis):` commit 收拾:更新 impl、註解、unit test、rate-limit hand-built key、auth-google integration test 對 raw key 的斷言

**最終驗證**:typecheck 清、unit 487/487、integration 177/177。

---

## 我的判斷與後續調整

### 判斷一:「最佳實踐該選哪個?」連問三次的價值

我發現自己連續問了三次「最佳實踐該選哪個?」、「哪個是最佳實踐?」、「以最佳實踐...」。事後反思,這個重複追問**不是廢話**,而是有效的 forcing function:

- 第一次:逼 AI 從「3 個 option + 推薦」收斂到「單一最佳答案」
- 第二次:在多個合理的下一步(ADR / prompts / code)間,逼 AI 給出時序判斷(為何 ADR 必須在 code 之前)
- 第三次:把「以最佳實踐」當成執行指令,進入 TDD

如果不這樣追問,AI 容易停在「列選項 + 給推薦」的安全位置,讓使用者自己拍板。但 ADR / spec / TDD 的整套流程需要 AI 自己對「下一步是什麼」有立場。**追問把「諮詢顧問」推到「執行夥伴」的位置。**

### 判斷二:ADR 鎖決策 → spec 鎖規格 → 測試鎖實作 → prompts 鎖過程

session 中我反覆把這條鏈說清楚並執行。具體價值:

- spec 019 寫完後本來想直接開測試,但「最佳實踐該選哪個?」的追問逼出 ADR 011。**沒有 ADR 就動 code,等於把決策依據埋進 commit log,半年後沒人記得當初為什麼選 60s TTL**
- ADR 011 §6「為什麼失效現在只預留 API」這段尤其重要 — 本作業根本沒 admin 寫入路由,但 helper signature 預留 `invalidate()` 是為未來的接口,**不是為現在寫實作**
- TDD 鐵則被嚴格遵守:8 個任務每步都先寫紅測試 → 跑紅 → 寫最小 impl → 綠 → 推進

### 判斷三:「先實作再補測試」的暗誘惑被擋下來

backend CLAUDE.md 明文「沒有失敗的測試就不寫產品碼」。session 中 AI 一路守住這條:每個檔案先寫 test,跑紅確認(`Error: Failed to load url ./keys.js`),才寫 impl。

最容易破例的時刻是 `cached-charity.ts` 加 list 函式 — 我已經有 detail 的測試 pattern,複製貼上很容易順便寫 impl。但 AI 仍然先寫測試再寫 impl,沒省略「跑紅」這步。

### 判斷四:Integration test 暴露的 buildKey bug 處理時機

寫 `cached-category.test.ts` 時,我要驗證 cache key 落在 `jkod:cache:cat:list:v1:zh-TW`(單前綴)。實驗發現實際是 `jkod:jkod:cache:cat:list:v1:zh-TW`(雙前綴)。

選項:
1. **跟著錯下去**:我的 cache 也產生 `jkod:jkod:cache:...`,跟 auth/rate-limit 一致
2. **跳出來自己對**:我的 cache 用單前綴,跟 auth/rate-limit 不一致
3. **整個專案修掉**:獨立 PR 修 buildKey

session 中我選 **2** 落地 cache,並把 **3** 列為 follow-up。後續用戶選擇「修 1 和執行 2」,所以 buildKey 修復跟 cache 落地是**兩個 commit**而非合併,git history 乾淨。

這個分次處理的優點:
- cache 落地 commit 自己完整可審
- buildKey fix commit 完整解釋 migration semantics(refresh tokens lost = Redis flush 等價)
- 如果合併會讓 commit message 涵蓋兩個決策,日後 revert 難拆開

### 判斷五:既有測試契約更新而非繞過

cache 落地後,兩個 donation-api 測試失敗:
- `Project detail ETag changes when parent updates` — parent 改 name → child 應 ETag 變,但 cache 還在
- `cascading visibility reverse: parent 續約 → child 應重現` — 同樣 cache 卡住

選擇:
1. **降 TTL 到 0**:破壞 cache 設計
2. **改測試斷言**:測「ETag 公式」改測「30s 後 ETag 變」— 但這就要 sleep,fragile
3. **加 invalidate 模擬寫入路徑**:測試中 `redis.del(...)` 對應 key,符合 spec 019 §8.3 admin 寫入路徑會做的事

session 中選 3。優點:
- 保留原測試的**意圖**(ETag 公式 / cascading visibility 公式)
- 同時**明文化新的 cache 契約**(寫入後需 invalidate)
- 未來 admin 路由出現時,把測試的 `redis.del()` 搬到 handler 即可,測試斷言不變

### 展示重點

這段 session 想呈現的工程判斷:

1. **顧問問答 → 規格 → 決策 → 實作的順序鎖**:即使是「加個 cache」的小事,也走 ADR → spec → TDD 完整流程,因為決策鏈價值在「下一個讀者能看到 why」
2. **重複追問是有效的 forcing function**:不是 AI 笨,是諮詢顧問位置太舒服,要逼它離開
3. **TDD 不是儀式,是擋掉「順手實作」的機制**:每步先跑紅是為了確認「我為什麼這麼做」,而不是「我會這麼做」
4. **發現相鄰 bug 不繞道**:cache 工作中發現 buildKey 雙前綴,寫個獨立 commit 收掉,順便對齊 spec 006 §4 文件
5. **既有測試契約變動要明文化**:加 cache 後測試要改,改的方式要反映新契約,而不是改成「能過」

---

## 相關檔案

- ADR:
  - [`docs/decisions/011-cache-strategy.md`](../decisions/011-cache-strategy.md)
- Spec:
  - [`backend/docs/specs/019-cache-policy.md`](../../backend/docs/specs/019-cache-policy.md) v0.2
- 實作(backend):
  - `src/lib/cache/{keys,json,with-cache,index}.ts`
  - `src/services/cached-{category,charity,donation-project,sale-item}.ts`
  - `src/routes/v1/donation/{categories,charities,donation-projects,sale-items}/index.ts`(改)
  - `tests/integration/{with-cache,cached-category,cached-detail,cached-list}.test.ts`
- Bonus fix:
  - `src/lib/redis/key-prefix.ts` + test(buildKey 雙前綴)
  - `src/lib/rate-limit/keys.ts` + test
  - `tests/integration/auth-google.test.ts`(raw key 斷言)
- Git history:
  - backend `fix(redis): drop double-prefix in buildKey` `6d6c2bd`
  - backend `feat(cache): add Redis cache-aside layer` `8e1ad6c`
  - root `docs(adr): add ADR 011` `0c6da0c`
- 原始 session 對話:[`raw/2026-06-15-session-6b1c9b4a.readable.md`](raw/2026-06-15-session-6b1c9b4a.readable.md)
