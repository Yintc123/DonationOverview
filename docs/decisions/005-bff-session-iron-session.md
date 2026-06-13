# ADR 005：BFF Cookie 封裝採用 iron-session（不採 NextAuth / 自寫）

- **狀態**：Accepted（2026-06-13 修訂 — 範圍縮為「cookie 封裝」，session 真相搬到 Redis；見 §9 修訂歷史與 ADR 006）
- **日期**：2026-06-13
- **影響範圍**：`frontend/src/lib/session/*`、`frontend/docs/specs/001-bff-infrastructure.md`
- **依賴**：
  - ADR 002（Backend = Fastify、BFF 分層）
  - ADR 004（Auth Token：access + refresh 雙 JWT、3h/30d、rotation + replay detect）
  - **ADR 006（Redis-backed BFF session 與 provider 抽象）— 本 ADR 之延伸**
  - Spec 001（BFF 基礎建設）§2 認證邊界、§3 Token 生命週期、§4 CSRF

---

## 1. 背景

BFF spec 001 §16 將「Session 加解密實作」列為待定 ADR。

> **修訂註（2026-06-13）**：原版本將 access/refresh token 直接放入 cookie。因專案部署於 Cloud Run（多 instance + 自動銷毀），改採 **server-side session in Redis** 模式（詳見 ADR 006）。本 ADR 範圍縮窄為**「cookie 封裝層」的選型**：cookie 內僅放 `{ sessionId }`，session 真實內容存 Redis。

需要在 Browser ↔ BFF 邊界提供一個**簽章 / 加密 cookie 容器**，存放：

- `sessionId`（opaque 隨機字串，長度 ≥ 32 bytes，由 BFF 在 session 建立時產生）

真正的 session 內容（accessToken / refreshToken / user / csrfToken）由 Redis 保管，cookie 只是「指向 session 的 token」。

關鍵限制（**已由其他 ADR 決定**）：

1. **OAuth 由 backend 處理**（ADR 002 §2、ADR 004 §「實作要點」）
2. **JWT 由 backend 簽**（ADR 004）
3. **Refresh / Logout 端點在 backend**
4. **CSRF 由 spec 001 §4 自訂**（synchronizer token 綁 session + Origin allowlist + timing-safe compare）
5. **Session 真相在 Redis**（ADR 006）

BFF 在 auth 鏈中的責任：「從 cookie 解出 sessionId、查 Redis 拿真實 session、用其中的 accessToken 打 backend、必要時觸發 refresh 並寫回 Redis」。Cookie 層**只**負責 sessionId 的完整性與不可竄改。

---

## 2. 選項評估

### 2.1 候選

| 方案 | 性質 |
|---|---|
| **A. iron-session（v8+）** | 純 encrypted cookie session 函式庫，無任何 auth 假設 |
| **B. NextAuth / Auth.js v5** | 完整身份框架：providers、callbacks、JWT 簽章、DB 適配、CSRF |
| **C. 自寫** | 用 `iron-webcrypto` / `jose` 寫薄包裝 |

### 2.2 八個關鍵維度比對

| 維度 | A. iron-session | B. NextAuth v5 | C. 自寫 |
|---|---|---|---|
| 與「backend 已 own identity」的相容性 | ✅ 純 cookie 容器，不假設誰發 token | ⚠️ 設計假設自己是 identity layer；要用 backend 發的 JWT 需走 Credentials Provider + callbacks 拗 | ✅ 完全控制 |
| 自訂 session shape（accessToken / refreshToken / csrfToken / user）| ✅ 泛型直接指定 | ⚠️ 內建 shape 為主，自訂欄位走 `callbacks.jwt` / `callbacks.session` 兜，型別不直觀 | ✅ |
| Sliding TTL（spec 001 §2.3）| ✅ `cookieOptions.maxAge` + 每次 `save` 重簽 | ⚠️ 有但綁在自己的 callback 流程內 | ✅ |
| 與我們的 CSRF 設計（spec 001 §4）相容 | ✅ 完全不干涉 | ❌ 內建 CSRF（state token + double-submit），與我們的 synchronizer 設計重疊／衝突，必須 disable 或繞 | ✅ |
| Bundle / 啟動成本 | ~10 KB，無 runtime overhead | 大；prerender / middleware 都被注入 | 最小 |
| Route Handler + Server Component + Server Action 都好用 | ✅ v8 對 App Router 一級支援（`getIronSession(cookieStore, opts)`） | ✅（這是它的主場）| 看實作 |
| 測試友善（可 mock cookie store、可手動 seal/unseal） | ✅ `sealData` / `unsealData` 是 public API | ⚠️ 需要 mock 整套 NextAuth context | ✅ |
| 維護成本與生態 | 低；由 vvo 維護，issue 回應穩 | 高（功能多 = 升版常踩坑）；Auth.js v5 仍持續 breaking | 高（自己擔） |

### 2.3 NextAuth 為什麼「看起來像答案、其實不是」

NextAuth 是**身份框架**，前提是「我這個 Next.js app 就是 identity 真相來源」（或代理它）。在我們的架構：

- 真相來源是 backend（OAuth 換 token、簽 JWT、refresh rotation、blacklist、replay detect 都在那）
- BFF 只是「把 backend 給的 token 放 cookie」

把 NextAuth 套上來會被迫做這幾件不划算的事：

1. **Credentials Provider 兜 OAuth**：寫一個 fake provider，在 `authorize()` 裡反向呼叫 backend，把 backend 發的 token 塞進 NextAuth 的 JWT。多一層繞圈
2. **同時擁有兩個 JWT 概念**：backend 的 JWT（給後端用）+ NextAuth 自己簽的 JWT（給它自己 session 用）。心智模型混亂
3. **Disable NextAuth 內建 CSRF**：我們已自訂（synchronizer token in session）；同時開兩套 CSRF 互相干涉
4. **NextAuth 的 callbacks/jwt 自動 refresh 模式**與 ADR 004 的 in-flight refresh debounce（spec 001 §3.4）整合困難
5. **Bundle 與升版負擔**：每次 Auth.js 大版本都需測試 BFF 邏輯是否還對

簡言之：**NextAuth 解決的問題我們已經在 backend 解掉了**。

### 2.4 自寫為什麼也不選

`iron-session` 內部就是 `iron-webcrypto`（AES-256-GCM 簽章加密）的薄包裝 + cookie 串接 + App Router helper。自寫等同於**重寫 iron-session**，沒有額外好處，徒增維護成本（cookie 邊界、Web Crypto fallback、SameSite/Secure 判斷、TTL 邏輯都要顧）。

---

## 3. 決策

採用 **iron-session（v8 以上）作為 cookie 封裝層**。

範圍**僅限於**：把 `{ sessionId }` 加密 + 簽章 + 寫入 / 讀取 cookie + sliding maxAge。
**不**將業務 session（accessToken / refreshToken / user / csrfToken）放入 cookie——那些由 ADR 006 規定的 Redis SessionStore 保管。

理由濃縮：

1. **角色匹配**：cookie 層需要「加密 / 簽章 + cookie attribute 管理 + sliding TTL」，iron-session 是這件事的最小可行解
2. **不與既有架構打架**：CSRF、refresh 流程、token 簽發、session 存儲都已各有歸屬，iron-session 不會插手
3. **小負載最佳化**：cookie 內容極小（`{ sessionId }`），iron-session 的 AES-GCM 加密成本可忽略
4. **App Router 一級支援**：在 Server Component、Route Handler、Server Action 都用 `getIronSession(await cookies(), options)`
5. **測試友善**：`sealData` / `unsealData` 可手動操作，配合 `tests/helpers/session.ts`（spec 001 §15.7）
6. **彈性保留**：若未來想在 cookie 多塞輕量欄位（e.g. csrfToken 也放 cookie 避免 Redis 查詢）容易擴張，無需換 lib

---

## 4. 實作要點

### 4.1 套件

```bash
pnpm add iron-session
```

> iron-session 為 ESM-only（v8+），需 Node 18+ Web Crypto 支援。Next.js 16 + Node 20+ 已滿足。

### 4.2 設定

```ts
// src/lib/session/config.ts
import 'server-only'
import type { SessionOptions } from 'iron-session'
import { env } from '@/lib/config'

export const sessionOptions: SessionOptions = {
  password: env.SESSION_SECRET!,           // spec 001 §13 已驗證 ≥ 32 字元、條件式必填
  cookieName: env.SESSION_COOKIE_NAME,
  cookieOptions: {
    httpOnly: true,
    secure: env.NODE_ENV === 'production',
    sameSite: 'lax',
    path: '/',
    maxAge: env.SESSION_TTL_SECONDS,
  },
}
```

### 4.3 Cookie 層公開 API（封裝 iron-session，只處理 sessionId）

```ts
// src/lib/session/cookie.ts
import 'server-only'
import { cookies } from 'next/headers'
import { getIronSession, type IronSession } from 'iron-session'
import { sessionOptions } from './config'
import crypto from 'node:crypto'

type CookiePayload = { sessionId: string }
type Box = IronSession<CookiePayload>

async function open(): Promise<Box> {
  return getIronSession<CookiePayload>(await cookies(), sessionOptions)
}

/** 從 cookie 取出 sessionId（無 cookie / 解密失敗時回 null） */
export async function readSessionId(): Promise<string | null> {
  const box = await open()
  return typeof box.sessionId === 'string' && box.sessionId.length > 0
    ? box.sessionId
    : null
}

/** 寫入 / 更新 cookie 的 sessionId；觸發 sliding maxAge */
export async function writeSessionId(sessionId: string): Promise<void> {
  const box = await open()
  box.sessionId = sessionId
  await box.save()
}

/** 清 cookie（與 ADR 006 SessionStore.destroy 配對呼叫） */
export async function clearSessionCookie(): Promise<void> {
  const box = await open()
  box.destroy()
}

/** 產 sessionId：opaque、32 random bytes → base64url（43 字元） */
export function newSessionId(): string {
  return crypto.randomBytes(32).toString('base64url')
}
```

> Session 的業務 API（取 access token、refresh、CSRF token 等）由 spec 001 §5 / ADR 006 規範的 `SessionService` 提供，內部呼叫 cookie 層 + SessionStore（Redis）。Route Handler **不直接呼叫** `readSessionId`，而是用 `SessionService.get()` 拿到組合後的 `Session` 物件。

### 4.4 與 spec 001 / ADR 006 各節對映

| 規範 § | iron-session 對應 |
|---|---|
| spec 001 §2.2 Cookie 內容 | cookie 只放 `{ sessionId }`，由 iron-session 加密簽章 |
| spec 001 §2.3 Sliding TTL | `cookieOptions.maxAge` + 每次 `writeSessionId()` 觸發重簽（cookie 端 sliding） |
| spec 001 §3 access + refresh 流程 | iron-session 不介入；流程操作 Redis（ADR 006），cookie 內容不變 |
| spec 001 §3.4 並發 refresh | 由 Redis 分散式鎖（ADR 006）處理，與 cookie 層無關 |
| spec 001 §4 CSRF（synchronizer token）| csrfToken 存於 Redis session（ADR 006），cookie 不放 |
| spec 001 §11.1 入站 session 驗證 | cookie 解出 sessionId → Redis 查詢 → Zod parse 驗證 shape |
| spec 001 §13 SESSION_SECRET | `sessionOptions.password` 強制依賴；必填條件不變 |
| spec 001 §15 cookie 層測試 | `sealData` / `unsealData` 可手動構造 cookie；測 helper 包成 `withSessionCookie(sessionId)` |
| ADR 006 §5 SessionService | 內部用 cookie 層 + SessionStore，提供業務語意 API |

### 4.5 測試輔助

`tests/helpers/session-cookie.ts`：

```ts
import { sealData } from 'iron-session'
import { sessionOptions } from '@/lib/session/config'

export async function withSessionCookie(req: Request, sessionId: string): Promise<Request> {
  const sealed = await sealData({ sessionId }, { password: sessionOptions.password, ttl: 0 })
  const headers = new Headers(req.headers)
  headers.set('cookie', `${sessionOptions.cookieName}=${sealed}`)
  return new Request(req.url, { method: req.method, headers, body: req.body })
}
```

整合測試（cookie + Redis）由 `tests/helpers/session.ts` 提供 `withSession(req, sessionData)`：寫入 InMemorySessionStore + 對應 cookie。詳見 ADR 006 §6.4。

---

## 5. 權衡（接受的成本）

| 失去 | 接受？ | 說明 |
|---|---|---|
| NextAuth 的 OAuth provider 生態（Google / Facebook / Apple 一鍵接）| ✅ | OAuth 由 backend `@fastify/oauth2` 負責，BFF 不需要 |
| NextAuth 的內建 CSRF | ✅ | 已自訂（spec 001 §4），更符合本架構 |
| NextAuth 的 middleware 整合（`auth()` helper）| ✅ | 用 `createRoute({ requireAuth: true })` 取代 |
| NextAuth 的 session callback 自動 refresh | ✅ | `backendFetch` 自寫 refresh 流程更貼合 ADR 004 的 rotation + replay |
| 自寫的「完全控制」 | ⚠️ | iron-session 已是極薄層；只放棄極少彈性，但省維護成本 |

---

## 6. 觸發重新評估的條件

以下任一發生時，**重新審視本 ADR**：

1. **BFF 需要直接做 OAuth**（脫離 backend 路徑），例如新增「Apple 登入」且 backend 端不想實作
2. **多 client（mobile / 第三方）共用同一個 BFF 並各自有 auth 需求**——這時可能值得引入 NextAuth 作為 identity 抽象層
3. **cookie 內容必須 > 4KB**（極不可能，因 sessionId 模式下 cookie 內容極小）
4. **想用 HTTP-only signed cookie 而非加密**（與 connect-redis / express-session 慣例一致；屬風格選擇，無安全增益）
5. **Auth.js 推出明確「pure cookie + external store」整合模式**並文件完整

---

## 7. 對下游 spec / ADR 的影響

本 ADR 修訂後，相關更新：

- **Spec 001 §2.2**：Cookie 內容從「full session」改為 `{ sessionId }`（其餘存 Redis）
- **Spec 001 §2.4**：`getSession()` 不收 `req`，內部用 Next.js `cookies()` 解 cookie + 呼叫 SessionStore
- **Spec 001 §3.4**：In-flight refresh 從 in-process Promise 改為 Redis 分散式鎖（ADR 006）
- **Spec 001 §5 模組結構**：`src/lib/session/` 加 `cookie.ts`、`store/`（介面 + impl）、`service.ts`
- **Spec 001 §6.2**：`backendFetch` 仍收 `req`，內部呼叫 `SessionService.get()`（cookie + Redis）
- **Spec 001 §13.2**：env 變數加 `REDIS_URL`、`REDIS_KEY_PREFIX`、可選 `REDIS_TLS_ENABLED`（詳見 ADR 006）
- **Spec 001 §15**：session 測試補：cookie round-trip、store 介面契約、InMemorySessionStore 替身

實作順序：**本 ADR → ADR 006 → 更新 spec 001 → TDD 實作 `src/lib/session/*`**。

---

## 8. 參考

- iron-session GitHub：<https://github.com/vvo/iron-session>
- iron-webcrypto（底層）：<https://github.com/brc-dd/iron-webcrypto>
- NextAuth → Auth.js 遷移：<https://authjs.dev/>
- Express + connect-redis 的 sessionId 模式：<https://github.com/tj/connect-redis>
- 本架構的 server-side session 決策：ADR 006

---

## 9. 修訂歷史

| 日期 | 變更 | 原因 |
|---|---|---|
| 2026-06-13 v1 | 初版：iron-session 持有 full session（access/refresh/user/csrfToken） | 預設 cookie-only 模式 |
| **2026-06-13 v2** | **範圍縮為「cookie 封裝層」**：cookie 只放 `{ sessionId }`，真實 session 移至 Redis；新增 ADR 006 處理 server-side session | **部署平台確定為 Cloud Run（多 instance + 自動銷毀）；server-side session 帶來立即作廢、無 cookie 大小限制、與 spec 001 §3.4 並發 refresh 解法天然整合等優勢** |
