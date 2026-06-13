# 決策：Backend 採用 Fastify + BFF 分層架構

日期：2026-06-13

## 背景

`backend/` 為獨立 NodeJS 服務，主要職責：

- 提供 REST API（捐款流程、會員資料）
- Google OAuth 2.0 登入
- JWT 驗證
- 搭配 Prisma 操作資料庫
- 搭配 Redis 做 cache / token blacklist / rate-limit

前端為 Next.js 16（App Router）並承擔 BFF 角色：瀏覽器與 BFF 之間走 session cookie，BFF 與 backend 之間走 JWT。

需決定 backend 框架：Express 或 Fastify。

## 選項評估

從本專案實際需求的四個角度比較：

| 角度 | Express | Fastify | 結論 |
|---|---|---|---|
| **OAuth 登入** | `passport` + `passport-google-oauth20`，事實標準、教學多；API 偏 callback 風格，TS 體驗一般 | `@fastify/oauth2` 內建 Google / Facebook / GitHub / Apple preset，async/await 原生，TS 友善 | 單一 Google provider 情境：Fastify 更簡潔 |
| **ORM 整合（Prisma）** | 直接 import 使用；request 驗證、型別需自行用 `zod` middleware 串接 | route schema (TypeBox/Zod) → request 型別 → Prisma → response 型別，TS 端到端推導不斷鏈 | Fastify 明顯勝出 |
| **JWT 驗證** | `jsonwebtoken` + 自寫 middleware，或 `express-jwt` | `@fastify/jwt` 官方 plugin，內建 sign/verify、自動注入 `request.user`、與 cookie plugin 整合 | Fastify 略勝，省 boilerplate |
| **Redis 搭配** | `ioredis` 直接使用；session 流程配 `connect-redis` + `express-session` 文件最完整 | `@fastify/redis` 注入乾淨；純 cache / rate-limit 場景一樣順 | 純 stateless 用途下兩者相當 |

## 決策

### 1. Backend 採用 Fastify

關鍵理由：

1. **本專案 backend 為 JWT stateless 服務**，不需要 session middleware，Express 在 session 生態的優勢無從發揮
2. **Fastify schema-driven 開發** 搭配 TypeBox + Prisma，能展現型別安全的工程判斷（面試重點）
3. **常用整合都有官方 plugin**：`@fastify/jwt`、`@fastify/oauth2`、`@fastify/redis`、`@fastify/cors`、`@fastify/helmet`、`@fastify/rate-limit`、`@fastify/swagger`，覆蓋度足夠
4. **效能優勢**：Fastify 在 JSON 序列化與 routing 上比 Express 快約 2 倍，是免費的加分項

### 2. 採用 BFF 分層，session / JWT 邊界明確

```
Browser ──(session cookie)──> Next.js BFF ──(JWT Bearer)──> Fastify API
                                  │                              │
                                  └─ iron-session / next-auth    ├─ @fastify/jwt
                                                                 ├─ @fastify/oauth2
                                                                 ├─ Prisma
                                                                 └─ @fastify/redis
```

- **Browser ↔ BFF**：httpOnly session cookie,由 Next.js（`iron-session` 或 `next-auth`）管理
- **BFF ↔ Backend**：`Authorization: Bearer <JWT>`,backend 完全 stateless
- **OAuth callback** 由 backend 處理 authorize code,簽 JWT 回給 BFF,BFF 再將 JWT 收進 session

此分層的好處:

- Backend 不需處理 CSRF、cookie 設定等瀏覽器層議題
- Backend 可重用於未來的 mobile / 第三方 client(只需發 JWT)
- 前端 session 失效、token 刷新邏輯集中在 BFF,backend 不需感知

## 不採用 Express 的權衡

捨棄項目:

- Passport 龐大的 OAuth provider 生態(本專案只需 Google,影響小)
- `express-session` + `connect-redis` 教學最豐富的 session 流程(本專案 backend 不走 session,不需要)
- Stack Overflow 問答數量(Fastify 文件已相當完整,實務上不構成阻礙)

## 主要套件清單(預定)

- `fastify`
- `@fastify/jwt`、`@fastify/oauth2`、`@fastify/cookie`
- `@fastify/cors`、`@fastify/helmet`、`@fastify/rate-limit`
- `@fastify/redis`、`ioredis`
- `@fastify/swagger`、`@fastify/swagger-ui`
- `@sinclair/typebox`(schema + 型別推導)
- `prisma`、`@prisma/client`
