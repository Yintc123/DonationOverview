# ADR 006：BFF Session 採 Redis Server-Side Store（含 Provider 抽象）

- **狀態**：Accepted
- **日期**：2026-06-13
- **影響範圍**：`frontend/src/lib/session/store/*`、`frontend/src/lib/session/service.ts`、`frontend/src/lib/api/backend.ts`、`frontend/docs/specs/001-bff-infrastructure.md`
- **依賴**：
  - ADR 004（Backend Auth Token：access + refresh、3h/30d、rotation + replay detect）
  - ADR 005 v2（Cookie 封裝採 iron-session、cookie 只放 `{ sessionId }`）
  - Spec 001（BFF 基礎建設）

---

## 1. 背景

`frontend/` 將部署於 **Google Cloud Run**：

- Instance 為**無狀態 container**，閒置數分鐘後自動銷毀
- 同時可能存在多個 instance（auto-scale），請求由 load balancer 分配
- 無 sticky session 保證 — 同一 user 連續兩個請求可能落在不同 instance
- Cold start 1–2 秒；instance 之間**不共享記憶體**

直接後果：

1. **Spec 001 §3.4** 原設計的「in-process refresh Promise 去重」**在多 instance 下失效**
   - User 多分頁同時遇 access 過期 → 不同 instance 都呼叫 backend `/auth/refresh`
   - Backend rotation：只第一個成功；其餘被視為 replay → backend **撤銷該 user 全部 refresh**（ADR 004 設計）→ user 被踢
2. **單 instance 在 refresh 中途死掉**也有相同問題
3. **部署期間 instance 重啟**同上

需要一個**跨 instance 共享**的協調機制。同時，把 session 內容也移到 server-side 帶來副作用收益（立即作廢、無 cookie 大小限制、未來「裝置管理 UI」鋪墊）。

---

## 2. 決策

### 2.1 核心決策

採 **Redis 作為 BFF 端 session 真相來源**，並提供 **`SessionStore` interface 抽象**，使具體 Redis client 與部署 provider 可替換。

### 2.2 範圍

Redis 在 BFF 端負責：

| 用途 | Key 樣式 | 必要性 |
|---|---|---|
| Session 內容存放 | `session:<sessionId>` | ✅ 必 |
| Refresh 分散式鎖 | `refresh-lock:<userId>` | ✅ 必（解決 §3.4） |
| 剛 refresh 完的 token pair 短期 cache | `fresh-tokens:<userId>` | ✅ 必（讓等待中的其他請求取用，避免重打 backend） |
| Idempotency-Key dedup（寫入操作） | `idem:<key>` | ❌ 未來 |
| Per-user rate limit | `rate:<userId>:<bucket>` | ❌ 未來 |

本作業範圍**只實作前 3 個**。Interface 預留擴充。

### 2.3 Provider 抽象

定義 `SessionStore` interface（§5），所有業務模組僅依賴介面。具體實作：

| 實作 | 用途 | 套件 |
|---|---|---|
| `RedisSessionStore` | 開發 + production；走標準 Redis 6+ 協議 | `ioredis` |
| `InMemorySessionStore` | 測試替身；不打網路 | 自寫，~50 行 |

正式部署的 Redis provider（Docker / Google Memorystore / Upstash / 其他）由 `env.REDIS_URL` 決定，**不影響應用程式碼**。本作業先用 **Docker container Redis** 作為開發環境，正式 provider 上線時再決定。

---

## 3. 為何 Redis（與替代方案）

| 方案 | 採用？ | 理由 |
|---|---|---|
| **Redis** | ✅ | 業界標準；TTL、SETNX 原子鎖、SCAN（裝置管理用）、Pub/Sub 都齊；ioredis 成熟；可從 Docker → Memorystore → Upstash 平滑升級 |
| Cloud SQL / PostgreSQL session table | ❌ | 寫入頻率高（每 request touch TTL）對 OLTP DB 是浪費；TTL 需 cron 清；無原子鎖 primitive |
| Firestore / DynamoDB | ❌ | 延遲分佈不利於每 request 同步路徑；自動 TTL 有但 lag 數分鐘；鎖機制不原生 |
| Memcached | ❌ | 無持久化（restart 即 logout 全使用者）；無 SCAN；功能不夠 |
| 雲端 cookie 服務（Vercel KV 等） | ❌ | 本專案部署 Cloud Run，不綁特定平台 KV |
| 不引入 Redis、改回 cookie-only session | ❌ | 多分頁並發 refresh 仍會 replay 誤判（這是 Cloud Run 多 instance 的本質問題） |

---

## 4. Redis Schema

### 4.1 Session

```
Key:    {prefix}:session:{sessionId}
Type:   STRING (JSON-serialized Session)
TTL:    env.SESSION_TTL_SECONDS（預設 7 天；sliding：每次 get 後 EXPIRE 重設）
```

Value shape（與 ADR 005 v2 + spec 001 §2.2 一致）：

```ts
type StoredSession = {
  userId: string                   // 對應 user.id；額外存於頂層便於 SCAN by user
  accessToken: string
  accessTokenExpiresAt: number     // epoch ms
  refreshToken: string
  refreshTokenExpiresAt: number    // epoch ms
  user: { id: string; name: string }
  csrfToken: string                // 43-char base64url
  createdAt: number
  lastSeenAt: number               // 每次 touch 更新
}
```

> 為「裝置管理 UI」鋪墊：可加開 `Key: {prefix}:user-sessions:{userId}` 為 SET，存所有該 user 的 sessionId。當前**不**實作，但 schema 預留。

### 4.2 Refresh 分散式鎖

```
Key:    {prefix}:refresh-lock:{userId}
Type:   STRING（隨機 lock token）
TTL:    10 秒（自動釋放保險）
寫入:   SET ... NX EX 10
釋放:   Lua 腳本：GET 比對 token 後 DEL（避免誤殺別人的鎖）
```

`acquireLock` 成功 = 拿到鎖；失敗 = 別的 instance 在 refresh。

### 4.3 Fresh tokens cache

```
Key:    {prefix}:fresh-tokens:{userId}
Type:   STRING (JSON: { accessToken, accessTokenExpiresAt, refreshToken, refreshTokenExpiresAt })
TTL:    60 秒（足夠等待最慢的並發請求取用，且夠短不留存安全風險）
```

成功 refresh 後立即 `SETEX`；等鎖的其他請求拿到鎖前先嘗試 `GET`，命中即用、不重打 backend。

### 4.4 Key prefix

所有 key 加 `env.REDIS_KEY_PREFIX`（預設 `jko-bff`）前綴，便於：
- 同 Redis instance 多環境共用（dev/staging/prod 用不同 prefix）
- `KEYS jko-bff:*` 快速查問題

---

## 5. SessionStore Interface

```ts
// src/lib/session/store/types.ts
import type { StoredSession } from '@/lib/session/types'

export type TokenPair = {
  accessToken: string
  accessTokenExpiresAt: number
  refreshToken: string
  refreshTokenExpiresAt: number
}

export interface SessionStore {
  // —— Session CRUD ——
  /** 取 session；命中時自動 sliding TTL（內部 EXPIRE）；不存在 / 過期 → null */
  get(sessionId: string): Promise<StoredSession | null>
  /** 建立 / 覆寫 session，並設 TTL */
  set(sessionId: string, session: StoredSession, ttlSeconds: number): Promise<void>
  /** 立即作廢 */
  destroy(sessionId: string): Promise<void>
  /** 顯式 sliding（給 get 路徑未自動 touch 的場景使用） */
  touch(sessionId: string, ttlSeconds: number): Promise<void>

  // —— Refresh 分散式鎖 ——
  /**
   * SET NX EX 取得鎖；回傳 lock token 字串供 release 比對；無法取得 → null
   */
  acquireLock(key: string, ttlSeconds: number): Promise<string | null>
  /**
   * 用 token 比對後釋放（Lua 原子 GET+DEL）；token 不符即 no-op 並回 false
   */
  releaseLock(key: string, lockToken: string): Promise<boolean>

  // —— Fresh tokens short cache ——
  getCachedTokens(userId: string): Promise<TokenPair | null>
  setCachedTokens(userId: string, pair: TokenPair, ttlSeconds: number): Promise<void>

  // —— 運維 ——
  /** Health check：連線是否健康；用於 /api/health */
  ping(): Promise<boolean>
}
```

業務模組（`SessionService`、`backendFetch`）**只依賴 interface**；具體 client 由 DI（簡單版：模組層 singleton 由 `getSessionStore()` 提供）注入。

---

## 6. Refresh 協調流程（spec 001 §3.4 取代版）

```
請求 R 觸發 access pre-emptive refresh（或收到 backend AUTH_TOKEN_EXPIRED）
   │
   ▼
1. store.getCachedTokens(userId)
   ├─ HIT  → 使用 cached pair（其他 instance 剛 refresh 過），更新 session、回到 backend 重打
   └─ MISS → 繼續
   ▼
2. lockToken = store.acquireLock(`refresh-lock:${userId}`, 10s)
   ├─ 取得鎖
   │   ├─ 再次 getCachedTokens（double-check，鎖前後縫隙）
   │   ├─ 打 backend POST /auth/refresh
   │   ├─ 成功：
   │   │   ├─ store.setCachedTokens(userId, newPair, 60s)
   │   │   ├─ store.set(sessionId, updatedSession, TTL)
   │   │   ├─ releaseLock
   │   │   └─ 回到 backend 重打
   │   └─ 失敗（401 / 5xx）：
   │       ├─ 401 UNAUTHORIZED / refresh 真的失效 → store.destroy(sessionId)、回 401 給 client
   │       ├─ 5xx / timeout → 不 destroy，回 503 給 client 重試
   │       └─ releaseLock
   │
   └─ 未取得鎖（其他 instance 在跑）
       ├─ Polling: 每 50ms 嘗試 store.getCachedTokens(userId)
       │   命中 → 用該 pair、更新 session、回到 backend 重打
       │   未命中 → 繼續 polling
       ├─ 最長等待 2 秒（lock 寬鬆值 + safety margin）
       └─ 超時 → 視為 BACKEND_UPSTREAM_ERROR (503)、log 警告
```

### 6.1 Lua 釋放鎖（原子）

```lua
-- KEYS[1]=lock key, ARGV[1]=expected token
if redis.call("GET", KEYS[1]) == ARGV[1] then
  return redis.call("DEL", KEYS[1])
else
  return 0
end
```

`RedisSessionStore.releaseLock` 必須用此腳本，**禁止**簡單 `DEL`（會誤刪別人的鎖）。

### 6.2 為何鎖 TTL = 10 秒

- Backend refresh 路徑 p99 應 < 2 秒（DB / Redis 查詢 + 簽章）
- 10 秒 = 2 倍 safety margin，又夠短到 instance crash 後不長期 stuck
- 萬一 instance 在持鎖中死掉，10 秒後自動釋放

### 6.3 為何 fresh-tokens TTL = 60 秒

- 等待中的並發請求只需數百毫秒內取得
- 60 秒覆蓋極端情境（cold start instance 加入後也能用）
- 過長則被竊取的 access token 有機可乘；60 秒可接受

---

## 7. 失敗 / 退化策略

### 7.1 Redis 不可用

| 情境 | BFF 行為 |
|---|---|
| `REDIS_URL` 未設定（USE_MOCK=0 時）| **啟動拒絕**（env 驗證失敗） |
| Redis 連線 timeout / refused | `SessionService.get()` 失敗 → 拋 `BACKEND_UPSTREAM_ERROR` (502)；handler 不假裝 anonymous |
| Redis 暫時抖動 | ioredis 內建 retry (≤ 3 次, exp backoff)；逾期一樣拋 502 |
| Lock 取不到且 polling 超時 | `BACKEND_UPSTREAM_ERROR` (503) + retry-after: 1 |

> **不採 fail-open 策略**：絕不在 Redis 異常時把使用者「視為已驗證」或「視為匿名」放行。安全優先於可用性。

### 7.2 與 backend Redis 的關係

| Redis | 用途 | 失效影響 |
|---|---|---|
| **BFF Redis（本 ADR）** | session、refresh-lock、fresh-tokens | BFF 不能服務需登入的請求；公開端點仍可（不查 session） |
| **Backend Redis（ADR 004）**| refresh-token 主檔、access blacklist | Backend 認證全面停擺 |

兩個 Redis **獨立**，可同 cluster 不同 DB 或完全分離（建議分離以隔離爆炸半徑）。本作業階段可同 Docker container 不同 DB。

---

## 8. 環境變數（補入 spec 001 §13）

| 變數 | 範圍 | 必填條件 | 預設 | 用途 |
|---|---|---|---|---|
| `REDIS_URL` | server only | `USE_MOCK=0` 必填 | — | e.g. `redis://localhost:6379/0`；rediss:// 表 TLS |
| `REDIS_KEY_PREFIX` | server only | — | `jko-bff` | Key 命名空間 |
| `REDIS_TLS_ENABLED` | server only | — | `'0'` | 顯式覆寫 TLS；通常從 URL scheme 推斷即可 |
| `REDIS_CONNECT_TIMEOUT_MS` | server only | — | `2000` | 連線 timeout |
| `REDIS_COMMAND_TIMEOUT_MS` | server only | — | `1000` | 單一 command timeout（避免拖累請求路徑）|

env 驗證在 `src/lib/config.ts`（spec 001 §13），用 `superRefine` 條件式必填。

---

## 9. 開發環境（Docker Compose）

本作業階段以 `docker-compose.yml`（放 `frontend/`）提供本地 Redis：

```yaml
# frontend/docker-compose.yml（本 ADR 規範；實作時建立）
services:
  redis:
    image: redis:7-alpine
    ports: ['6379:6379']
    healthcheck:
      test: ['CMD', 'redis-cli', 'ping']
      interval: 5s
      timeout: 3s
      retries: 5
    command: redis-server --appendonly yes --save ""
```

對應 `.env.local`：

```
REDIS_URL=redis://localhost:6379/0
REDIS_KEY_PREFIX=jko-bff-dev
```

啟動：`docker compose up -d redis && pnpm dev`

---

## 10. 測試策略

### 10.1 SessionStore Contract Test（套用所有 impl）

撰寫一份 `tests/contracts/sessionStore.contract.ts`，對任何 `SessionStore` impl 跑同一組案例：

- `get / set` round-trip
- `get` 命中後 sliding TTL（TTL 重設）
- `destroy` 後 `get` 回 null
- `touch` 更新 TTL
- `acquireLock` 第一次成功、第二次失敗
- `releaseLock` 用正確 token 成功、用錯 token 失敗
- 鎖 TTL 到期後自動可被其他 caller 取得
- `getCachedTokens` / `setCachedTokens` round-trip
- `ping` 在連線健康時回 true

兩個 impl（`RedisSessionStore`、`InMemorySessionStore`）皆需通過此契約。

### 10.2 整合測試（單一 impl）

- `RedisSessionStore` 對 Docker compose 起的 Redis 跑（CI 用 service container）
- `InMemorySessionStore` 用於單元測試與 Route Handler 測試（無外部依賴）

### 10.3 並發 refresh 測試（critical）

模擬 5 個並發請求同時觸發 refresh：

- 斷言只有 1 個請求打到 backend `/auth/refresh`
- 其他 4 個皆透過 `getCachedTokens` 取得結果
- 全部 5 個請求成功完成
- Backend 未收到 replay 訊號

此測試**必過**，否則 Cloud Run 部署後會踢使用者。

### 10.4 Redis 故障測試

- Redis 連線斷 → handler 回 502，**不**回 200
- Lock 超時 polling → 503 with Retry-After

---

## 11. 升級觸發條件

| 觸發 | 評估 |
|---|---|
| 需要「裝置管理」UI（顯示活躍 session） | 加 `user-sessions:{userId}` SET；無架構變動 |
| QPS 超出單 Redis 負載 | 切 Redis Cluster；ioredis 原生支援；無業務變動 |
| 多區域部署需強一致 session | 評估 active-active replication 或 region-local store |
| Idempotency-Key 寫入去重需求出現 | 加 `idem:` key + middleware；本 ADR interface 已預留 |
| Per-user rate limit 需求 | 同上，加 `rate:` key |

---

## 12. 對下游 spec 的影響

實作前需更新：

- **Spec 001 §2.2**：Cookie content 改為 `{ sessionId }`；session 真相在 Redis（type 改為 `StoredSession`）
- **Spec 001 §2.4**：模組責任表加入 `SessionStore` / `SessionService`
- **Spec 001 §3.4**：refresh 去重段落改為「Redis 分散式鎖 + fresh-tokens cache」
- **Spec 001 §5 模組結構**：
  - 新增 `src/lib/session/cookie.ts`（ADR 005 v2）
  - 新增 `src/lib/session/store/types.ts`、`store/redis.ts`、`store/in-memory.ts`
  - 新增 `src/lib/session/service.ts`（組合 cookie + store，提供業務 API）
- **Spec 001 §6.1**：backendFetch 內部呼叫 `SessionService.get()` / `.refresh()`，不再依賴 in-process Promise
- **Spec 001 §7.1**：錯誤碼補：Redis 故障 → `BACKEND_UPSTREAM_ERROR`
- **Spec 001 §13.2**：補本 ADR §8 所有變數
- **Spec 001 §14.2**：log 遮罩規則加 sessionId（只記前 4 字 + `...`）
- **Spec 001 §15**：加 contract test 章節

---

## 13. 修訂歷史

| 日期 | 版本 | 變更 |
|---|---|---|
| 2026-06-13 | v1 | 初版 |
