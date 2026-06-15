# 決策:Public Read API 的 Redis cache 走 adapter 層 + cache-aside,list 僅熱門白名單,暫不做 stampede 防護

日期:2026-06-15

## 背景

spec 006(Redis 模組)已定錨 Redis 在本服務同時承擔 cache / auth state / rate-limit / lock 四種角色,並以 key namespace + TTL + eviction 規則分區治理;§9 預設 cache-aside、§11.3 規定 Redis 故障必須降級不可 5xx。然而 **「哪些公開 read API 該 cache、cache 邏輯放在程式碼的哪一層、TTL 怎麼定」** 屬於業務層 cache 策略(spec 006 §1.3 明示 out of scope),本 ADR 為其決策依據。

具體會反覆出現的疑問:

1. 為什麼不直接在 route handler 寫 cache 邏輯就好?
2. 為什麼不把 cache 塞進 domain service(`getDonationProjectById` 內部讀寫 Redis)?
3. 為什麼 list 端點不全 cache,只 cache「熱門首頁」?
4. TTL 為什麼選 30s / 60s / 600s 這幾個值?換成 5min / 1h 不是命中率更高?
5. 為什麼不做 write-through?寫入時順手 SET 一份不是比 DEL 更新鮮?
6. 為什麼不預先實作 stampede 防護(distributed lock / probabilistic refresh)?
7. 失效策略現在還沒做,以後 admin 寫入路由出現時要怎麼接?

問題 1-2 看似最直覺,但會破壞既有分層;問題 3-4 是「對 stale 容忍度」與「key 維度爆炸」的權衡;問題 5-6 是「過度設計」陷阱;問題 7 需要為未來保留接點而不為其過度設計。本 ADR 把這幾條一次定錨,讓 spec 019 的所有規約有據可循。

候選方案需滿足的約束:

- 嚴格遵守 spec 006 §4(key namespace)、§6(TTL)、§9(cache-aside)、§11.3(降級)
- 不破壞 spec 016 / 017 既有 `Cache-Control` + ETag conditional GET 契約
- 不違反 backend CLAUDE.md「純函式 → unit;牽涉 Redis → integration」分層原則
- 不違反 backend CLAUDE.md「不 mock Redis / Prisma」測試政策
- 不為「本作業階段不會出現的場景」過度設計(無 admin 寫入路由、無 prod 等級流量)

## 選項評估

### 1. Cache 層位置:route / domain / adapter

| 方案 | 描述 | 利 | 弊 |
|---|---|---|---|
| **A. Route handler 內** | 7 個 GET handler 各自呼叫 redis,miss 再呼 domain | 改動範圍直觀 | ❌ 7 個 handler 都新增 ~20 行 cache 樣板;❌ i18n locale 解析 + ETag header 已在 route,再疊 cache 後 handler 失去單一職責;❌ 未來 admin 寫入失效邏輯散布在多個 route,難集中 review |
| **B. Domain service 內** | `listCategories` / `getDonationProjectById` 內部讀寫 redis | 一處集中 | ❌ `domain/` 目前依賴單純(`prisma + objectUrl + locale`),所有測試可純 unit;塞 redis 後**全部** domain 測試強制升 integration,測試金字塔倒置;❌ domain 變得不純,後續想抽出做 batch / CLI 工具會被 redis 依賴拖住 |
| **C. 新 adapter 層 `services/cached-*`**(採用) | 薄包裝既有 domain service;route 改呼 `cached-*` | ✅ domain 純度不動,既有 unit test 保留;✅ cache 規則集中,符合 spec 006「分區治理」精神;✅ route handler diff 極小(換一個 function name);✅ 未來換 cache backend 只動 adapter 一層 | 多一個目錄(~5 個檔案)|

→ **採方案 C**。A 的代價在 7 處複製樣板,B 違反既有分層原則同時拖測試金字塔。C 的多目錄成本在本作業是固定一次性,後續每加一個新端點都是純複製。

### 2. Cache 模式:cache-aside vs write-through vs write-back

| 方案 | 描述 | 利 | 弊 |
|---|---|---|---|
| **D. Cache-aside**(採用,亦為 spec 006 §9.1 預設) | 讀:GET miss → loader → SET;寫:更新 SoT → DEL | ✅ 失敗 semantics 單純(cache 失敗只是少省一次 SoT 查詢);✅ SoT 永遠是 truth,不會有「DB 沒寫成但 cache 有」的鬼故事;✅ spec 006 已預設,規約已熟 | miss 第一次有 cold start 延遲;高並發 miss 有 stampede 風險(§3) |
| E. Write-through | 寫入時同步寫 SoT + cache | cache 命中率高 | ❌ 寫入路徑變雙 dependency(SoT + cache 任一失敗都要處理);❌ 並發寫易產生「A 寫 SoT、B 寫 SoT、A 寫 cache、B 寫 cache」交錯,cache 變舊;❌ spec 006 §9.2 明文「**寫入後刪 key,不更新 key**」 |
| F. Write-back / write-behind | 寫入只進 cache,背景同步到 SoT | 寫入延遲最低 | ❌ cache 變成 SoT 一部分,失敗 = 資料遺失;❌ AOF / RDB 沒設好就是 data loss;❌ 完全違反本作業「Redis 為 cache,不為 truth」設定 |

→ **採方案 D**。E 在本專案 spec 已明禁;F 在「不可遺失資料」的捐款場景是反模式。

### 3. List 端點:全 cache vs 僅熱門白名單 vs 不 cache

| 方案 | 描述 | 利 | 弊 |
|---|---|---|---|
| G. List 全 cache | 任何 query 組合都進 cache | 命中即省 DB | ❌ list 完整 query 維度為 `cursor × pageSize × category × charityId × locale`,組合呈指數成長;❌ 翻頁是長尾流量,key 命中率極低 → 記憶體與寫入頻寬白燒;❌ 失效時需 SCAN MATCH(spec 006 §4.3 已禁) |
| **H. List 僅熱門白名單**(採用)| 無 cursor + 預設 pageSize + category ∈ {ALL, 各單一 category} + charityId=ALL 才進 cache | ✅ key 數量上限固定(分類數 × locale × 3 種 resource);✅ 集中流量(首頁、分類頁)命中率高;✅ 失效時白名單可枚舉 DEL,不需 SCAN | miss 的翻頁仍打 DB;但翻頁本就分散,DB 可承受 |
| I. List 不 cache | 全部直接打 DB | 實作最簡 | ❌ 浪費首頁高頻命中機會 — 同 category 同 locale 第一頁是流量最集中處 |

→ **採方案 H**。G 違反 spec 006 key 規範且 ROI 為負;I 浪費明顯命中機會。

### 4. TTL 數值選擇

| Endpoint | 候選值 | 採用 | 理由 |
|---|---|---|---|
| `GET /v1/donation/categories` | 60s / 600s / 3600s | **600s** | 16 列字典近不可變;spec 006 §6.1 cache tier 上限 1h;600s(10min)在「管理員編輯後最壞延遲」與「命中率」之間平衡(編輯後 10min 內生效可接受) |
| 三個 detail | 30s / 60s / 300s | **60s** | spec 016 §11.1 標 detail 為「time-sensitive(lifecycle filter)」;`publishStart/End` 切換時最壞延遲 60s 視覺可接受;比 30s 命中率高、比 300s 對 lifecycle 切換更靈敏 |
| 三個 list(白名單) | 15s / 30s / 60s | **30s** | list 對 lifecycle 切換最敏感(品項可能整列消失);30s 換取更小延遲;比 detail 短的理由是 list 涉及「lifecycle filter 把 row 從結果集移除」這個語意更敏感的變化 |

→ TTL 不是越長越好。越長 = 命中率越高但 stale 越久,本作業選「在 spec 016/017 已宣告的『time-sensitive』約束下,接受最壞延遲 ≤ 10min」這個立場。

### 5. Stampede 防護:預先實作 vs 暫不啟用

| 方案 | 描述 | 利 | 弊 |
|---|---|---|---|
| J. 預先實作 distributed lock | SET NX EX 取鎖,失敗者等再讀 cache | 高並發 miss 不穿透 | ❌ 多一個失敗模式(鎖卡死、TTL 過短鎖被搶);❌ 本作業流量未到觸發門檻 |
| K. 預先實作 probabilistic early refresh | 接近 TTL 末段時部分請求觸發 refresh | 平滑命中曲線 | ❌ 增加實作複雜度;❌ 本作業 TTL 短(30s ~ 10min),穿透成本可承受 |
| **L. 暫不啟用,預留 trigger 條件**(採用) | 觀測 DB QPS 出現 TTL 邊界尖峰或單 key 引發 P99 退化才啟用 | ✅ 對齊 spec 006 §9.3「等實測有 stampede 才導入」;✅ 對齊 CLAUDE.md「don't design for hypothetical future requirements」;✅ 本作業流量規模不需要 | miss 的瞬間多請求會同打 DB |

→ **採方案 L**。J / K 都是真實有用的工具,但啟用時機應由觀測驅動而非預先設計。

### 6. 失效策略:現在做完整 vs 預留接口

| 方案 | 描述 | 利 | 弊 |
|---|---|---|---|
| M. 現在實作完整事件驅動失效 | 訂 admin 寫入事件 / pub-sub,觸發精準 DEL | 失效最即時 | ❌ 目前無 admin 寫入路由,純為假設場景設計;❌ pub-sub 違反 spec 006 §1.3 out-of-scope |
| **N. 現在純 TTL 兜底,預留 `invalidate()` API**(採用) | helper 暴露 DEL 接口供未來 admin 寫入呼叫 | ✅ 最小可用;✅ 接口形狀規範在 spec 019 §8.3;✅ admin 寫入路由出現時直接接上 | 寫入後最壞延遲 = TTL 值 |

→ **採方案 N**。本作業階段無寫入路徑,過早做完整失效就是無用功;但 API 形狀必須先規範,避免未來想接時發現 helper 沒留口。

## 決策

採用 **C + D + H + 上表 TTL + L + N**。具體落地由 [`backend/docs/specs/019-cache-policy.md`](../../backend/docs/specs/019-cache-policy.md) 規範。重點摘要:

1. **架構**:新 `src/services/cached-*` adapter 層包裝 `src/domain/donation-item/*` 與 `src/domain/category/list.ts`;route handler 改呼 `cached-*`,domain 一行不動
2. **通用 helper**:`src/lib/cache/with-cache.ts` 提供 `withCache<T>(opts)`;一律 cache-aside,失敗降級走 loader,不可 5xx
3. **Key schema**:`cache:<resource>:<sub>:v{n}:<segments>`(locale 必入 key,`:v{n}` 用 schema bump 代替 SCAN)
4. **TTL**:categories 600s / detail 60s / list 30s(走 `SET key value EX n` 同步設定)
5. **List 白名單**:無 cursor + 預設 pageSize + category ∈ {ALL, 各單一分類} + charityId=ALL;非白名單 bypass
6. **Stampede**:不實作;觀測到 DB QPS 在 TTL 邊界出現週期性尖峰或單 hot key 引發 P99 退化時,以另一份 ADR 評估啟用方案 J / K
7. **失效**:現階段 TTL 兜底;`invalidate(redis, key, logger)` API 預留;admin 寫入接點規範於 spec 019 §8.3
8. **不變式**:Redis 故障**永遠**不可讓公開端點 5xx、不可改變 response shape、不可改變 ETag / Cache-Control header

### 必要的程式碼改動範圍

| 路徑 | 動作 |
|---|---|
| `src/lib/cache/keys.ts` + test | 新增 |
| `src/lib/cache/json.ts` + test | 新增 |
| `src/lib/cache/with-cache.ts` + integration test | 新增 |
| `src/lib/cache/index.ts` | 新增 |
| `src/services/cached-category.ts` + integration test | 新增 |
| `src/services/cached-charity.ts` + integration test | 新增 |
| `src/services/cached-donation-project.ts` + integration test | 新增 |
| `src/services/cached-sale-item.ts` + integration test | 新增 |
| `src/routes/v1/donation/categories/index.ts` | 改:換呼 `cached-*` |
| `src/routes/v1/donation/charities/index.ts` | 改:同上 |
| `src/routes/v1/donation/donation-projects/index.ts` | 改:同上 |
| `src/routes/v1/donation/sale-items/index.ts` | 改:同上 |
| `src/domain/**` | **不動** |

## 理由

### 1. 為什麼 cache 必須放在 domain 之外

backend CLAUDE.md 已明文「純函式 → unit;牽涉 Redis → integration」。`src/domain/` 目前所有函式都是純的(吃 `prisma + objectUrl + locale`,回傳純資料),可用純 unit test 覆蓋,測試極快。

把 redis 塞進 domain 等同把整個 domain 強制升格為 integration test,後果不只是測試變慢:

- 測試金字塔倒置 — 大量 integration 取代 unit,CI 成本指數增加
- domain 失去「可獨立於基礎設施運行」這個性質 — 日後若需要做 batch script / data migration / CLI 工具直接呼 domain,會被 redis 依賴卡住
- 違反 backend CLAUDE.md「不 mock Redis」政策後,連寫一個 domain test 都要拉 testcontainer,門檻過高

Adapter 層的存在是讓**基礎設施組合**有自己的家:它組合 `redis + domain`,可以坦然走 integration test,而 domain 仍是純的。

### 2. 為什麼 cache-aside 是這個專案唯一合理選擇

捐款是「**不可丟資料**」場景。write-back 把 cache 變成 SoT 之一,任何 Redis 重啟(AOF 沒設好、或 OOM 觸發 evict)= 資料遺失。即便 AOF on,`appendfsync everysec` 仍有 1 秒視窗 — 這在登入 session 可接受,在「使用者按下贊助」的回饋上不可接受。

Write-through 表面上保留 SoT,但寫入路徑變雙 dependency,並發寫入易交錯產生「DB 是 v3、cache 是 v2」的 stale-after-write。spec 006 §9.2 「寫入後刪 key,不更新 key」就是為此設計 — DEL 後讀者重新走 cache-aside,SoT 永遠贏。

Cache-aside 的「first miss 慢一次」代價,在 read-heavy + key 數量可控的設定下幾乎不影響使用體驗。本作業正是此設定。

### 3. 為什麼 list 不全 cache,detail 卻可以

兩者的 key 維度差距是數量級的。

Detail 的 key 維度只有 `(id, locale)` — 給定 N 筆資料、2 個 locale,理論上限 `2N` 個 key。本作業 N 在百位數,key 數可控、命中率高。

List 的 key 維度是 `cursor × pageSize × category × charityId × locale`。`cursor` 是 opaque pagination cursor,長尾翻頁產生的 key 幾乎不重複,每個 cache 只被命中 1-2 次就過期,記憶體與寫入頻寬全燒在無用 entry。

熱門白名單抓住了 list 訪問的**冪律分布**:首頁與主分類佔 80% 流量、key 不超過 20 個。剩下 20% 的長尾翻頁打 DB 也撐得住。

### 4. 為什麼 TTL 是這幾個具體值

TTL 是「**stale 容忍度**」與「**命中率**」的權衡,規則由 spec 016 §11.1 / 017 §2 已宣告的「time-sensitive(lifecycle filter)」立場框定。

- **categories(字典,600s)**:沒有 lifecycle 概念,只有管理員編輯;編輯後 10min 內生效是合理 SLA。短於此(如 60s)命中率變差;長於此(如 1h)違反 spec 006 §6.1 cache tier 上限
- **detail(60s)**:`publishStart/End` 切換時最壞 60s 內畫面仍可見已過期內容。1min 是「使用者重新整理一次」的自然節奏;短於此(30s)收益遞減,長於此(5min)在 lifecycle 切換瞬間可能產生「按下贊助→ 404」的尷尬
- **list(30s)**:list 涉及「整列從結果集消失」的語意,比 detail「單頁狀態變化」更敏感。30s 換取更小視覺延遲;同時與 detail 60s 形成階梯,從上游往下游 stale 容忍度遞增,direction 一致

這些值不是金科玉律 — 落地後跑 metrics(spec 019 §11.1),命中率 / DB QPS 不滿意可調。但**第一版的數字必須有依據**,否則後續調整也無基準。

### 5. 為什麼 stampede 不預先做

spec 006 §9.3 列出三種防護,任一都是合理工具。但每個都增加實作 / debug / 失敗模式複雜度:

- Distributed lock:鎖 TTL 過短會被搶、過長卡 falsely;鎖失敗者要 retry 或 fallback,retry 上限怎麼設?
- Probabilistic early refresh:邊界條件多(怎麼判定「接近 TTL」、refresh 頻率怎麼控)
- Request coalescing:單 instance 內有效,跨 instance 仍打;ECS 多 task 部署下價值受限

這些複雜度的代價,在「**還沒實測有 stampede**」前付出就是空頭支票。本作業流量未到觸發門檻(預估 < 100 QPS),Postgres 在 cache miss 瞬間打進來的 N 次同 query 也能秒回。

啟用標準必須**觀測驅動**:DB QPS 在 TTL 邊界出現週期性尖峰、或 P99 從 50ms 漂到 200ms+,才以另一份 ADR 評估方案 J / K。否則就是 spec 006 §9.3 警告的「過度設計」。

### 6. 為什麼失效現在只預留 API

本作業階段無 admin 寫入路由(spec 016 / 017 都是 public read-only)。實作完整事件驅動失效現在等於為假設場景寫 code,且這個假設場景可能根本不會在 demo 期間出現。

但**API 形狀必須先定**,否則:

- 未來 admin 路由出現時,可能因為 cache helper 沒留 invalidate 口,要回頭改 helper signature(violate open-closed)
- spec 019 §8.3 已規範未來各 admin 寫入要 DEL 哪些 key — 規約先到、實作後到,符合「spec 鎖規格、code 鎖實作」順序

`invalidate(redis, key, logger): Promise<void>` 是最小完備 API:接受 key、容錯不 throw、記降級 log。未來 admin 寫入路由實作時,呼叫一行即可。

### 7. 為什麼不變式比命中率優先

cache 失敗永遠不可讓公開端點 5xx — 這條規則的價值不在「正常情況」(正常情況 Redis 不會掛),而在「Redis 升級、Redis OOM、Redis 網路抖動」這幾個 demo 期間隨時可能發生的場景。

如果不變式失守,cache 從「優化」變成「**新的 SPOF**」 — 引入 cache 反而降低系統可用性。這是「過早優化」中最糟的一種。

具體三條:

- **不可改變 5xx 行為**:GET / SET 失敗一律 try-catch → log warn → 降級走 loader
- **不可改變 response shape**:cache 命中與 miss 走同樣的 deserialize / 同樣的 ETag header / 同樣的 envelope
- **不可改變 header**:`Cache-Control` / `Vary` / `Content-Language` / `ETag` 一律在 route 層處理,**不**因 cache hit/miss 分歧

spec 019 §12.2「必須有的測試」第一條就是「Redis down 時 detail endpoint 仍 200」 — 這是不變式的可執行證明。

## 後續

| 項目 | 觸發條件 | 動作 |
|---|---|---|
| 啟用 stampede 防護 | 觀測到 DB QPS 在 TTL 邊界出現週期性尖峰,或單 hot key 引發 P99 退化 | 另立 ADR 評估方案 J / K;優先考慮 request coalescing(in-process,複雜度最低) |
| 擴大 list 白名單 | metrics 顯示特定非白名單組合命中率超過 30% | spec 019 §3.1 表格新增該組合;TTL 沿用 30s |
| 接上 admin 寫入失效 | 第一個 admin 寫入路由出現 | 走 spec 019 §8.3 規約;每個 write handler 在成功 commit 後呼 `invalidate(...)` |
| 字典編輯後的失效 | categories 加入 admin 編輯介面 | 同上,DEL `cache:cat:list:v1:zh-TW` + `:en` |
| Response shape breaking change | `paginatedEnvelope` / detail schema 結構性變更 | key schema 段 `:v1` → `:v2`,**不**清舊 key(自然 TTL 過期) |
| 跨服務 cache 共享 | 出現第二個 backend 服務需讀同樣資料 | 評估「兩個服務各自 cache(simple)」vs「shared cache 加 version key(避免雙寫)」;初期偏好前者 |
| Cache 觀測 | spec 觀測模組落地 | 接上 spec 019 §11.1 的四個 metric;DB QPS、cache hit ratio、降級頻率上 dashboard |

## 變更紀錄

| 版本 | 日期 | 變更 |
|---|---|---|
| 0.1 | 2026-06-15 | 初版;定錨 adapter 層 + cache-aside + 熱門白名單 + TTL 表 + stampede 暫不啟用 + 失效 API 預留 |
