# 決策:Auth Token 採用 Access + Refresh 雙 Token 架構

日期:2026-06-13

## 背景

`backend/` 為 JWT stateless API(ADR 002),需決定 token 壽命策略與撤銷機制。三個核心需求:

1. **可撤銷**:使用者登出 / 換密碼 / 帳號異常時需失效既有 token
2. **不犧牲 stateless**:每個請求的 access 驗證不可走 DB / Redis(否則退化為 session)
3. **UX 合理**:不能讓使用者頻繁重新登入

## 選項評估

| 選項 | 機制 | 撤銷 | UX | 結論 |
|---|---|---|---|---|
| **單一長期 JWT** | 一張長 token(e.g. 7d) | ❌ 簽出後無法撤銷(除非每次驗證查 DB) | 好(久久才重登) | ❌ 安全性不足 |
| **單一短期 JWT** | 短壽命 token(e.g. 15m),過期重登 | ⚠️ 等過期才失效 | 差(頻繁重登) | ❌ UX 不可接受 |
| **Access + Refresh 雙 token** | 短 access(stateless 驗證)+ 長 refresh(可撤銷) | ✅ 撤銷 refresh 即阻斷續期 | 好(背景續期) | ✅ 採用 |
| **Session(server-side)** | session id 存 Redis,cookie 帶 id | ✅ DEL 即失效 | 好 | ❌ 與 ADR 002 stateless API 邊界衝突;BFF 那層已用 session,backend 重複 |

## 決策

採用 **Access Token + Refresh Token 雙 Token 架構**。

### 參數

| 項目 | 值 | 備註 |
|---|---|---|
| Access token 壽命 | **3 小時** | UX 優先;搭配 Redis blacklist 可緊急撤銷 |
| Refresh token 壽命 | **30 天** | 一個月不需重登,平衡安全與便利 |
| Refresh token 儲存 | **Redis only** | prod 需啟用 AOF 持久化 |
| Refresh rotation | **每次 refresh 都換新** | 偵測 replay → revoke 該 user 全部 refresh |
| Access 緊急撤銷 | **Redis blacklist**,TTL = access token 剩餘壽命 | 平常不查;僅異常事件寫入(換密碼、強制登出) |

## 理由

### 為什麼 access 3 小時

業界常見預設 15 分鐘 ~ 1 小時。本專案選 3 小時,理由:

- 捐款 app 屬中低敏感(非銀行 / 醫療),較長 access 可降低前端 refresh 邏輯壓力與閃爍體驗
- 一旦 token 外洩,曝險最長 3 小時——可接受,且有 Redis blacklist 緊急撤銷管道
- 高風險操作(變更綁定 email、更新付款方式)在 app 層額外要求重新驗證,不依賴 token 壽命作為唯一防線

### 為什麼 refresh 30 天

- 與業界主流(GitHub、Google) 同量級
- 7 天太短,使用者頻繁重登;90 天太長,失竊風險高
- 30 天搭配 rotation 與 Redis 撤銷,可逐裝置處理異常

### 為什麼 refresh 存 Redis(而非 DB)

| 角度 | Redis only | DB(+ Redis cache) |
|---|---|---|
| 個別撤銷 | ✅ `DEL key` | ✅ |
| 全使用者撤銷 | ✅ 用 user→tokens 的 SET | ✅ `WHERE user_id` |
| 「裝置管理」UI | 可做但需多存 metadata | 直觀 |
| 審計紀錄保留 | 不適合(隨 TTL 蒸發) | 天生適合 |
| Redis flush / 重啟 | **需 AOF**,否則全使用者重登 | 不受影響 |
| 實作成本 | 低 | 中(table + Prisma model + migration) |

本專案無「裝置管理 UI」、無合規審計需求,Redis only 已足夠。prod Redis 啟用 AOF 即可滿足持久化。

### 為什麼 rotation + replay detection

每次 refresh 都換新的 refresh token,舊的立即失效。若同一個舊 refresh token 再次被使用(replay),代表:

- 使用者裝置已用過該 token 換新 → 舊 token 不該再出現
- 出現 = 中間人 / 竊取者拿到 token 在用

偵測到 replay → 撤銷該 user 所有 refresh token,強迫所有裝置重登。OAuth 2.0 RFC 6819 建議做法。

## 實作要點

### Redis Key 設計(暫定)

```
refresh:{tokenId}        Hash { userId, hashedToken, createdAt, expiresAt }
                         TTL = refresh 壽命
user:refresh:{userId}    SET of tokenId
                         撤銷整個 user 時 SMEMBERS 後逐一 DEL
blacklist:access:{jti}   STRING "1"
                         TTL = access 剩餘壽命
```

- refresh token 本身**只給 client**,server 端只存 hash(SHA-256)
- access token 用 `jti` claim 唯一標識,blacklist 比對 jti

### Token Payload(暫定)

Access:
```jsonc
{
  "sub": "<userId>",
  "jti": "<uuid>",            // for blacklist
  "iat": ...,
  "exp": ...,                 // iat + 3h
  "type": "access"
}
```

Refresh:
```jsonc
{
  "sub": "<userId>",
  "jti": "<tokenId>",         // matches Redis key
  "iat": ...,
  "exp": ...,                 // iat + 30d
  "type": "refresh"
}
```

### 端點(暫定,留待後續 auth flow spec)

- `POST /auth/refresh` — body 帶 refresh,回新 access + 新 refresh,舊 refresh 失效
- `POST /auth/logout` — 撤銷當前 refresh + 寫 access blacklist
- `POST /auth/logout-all` — 撤銷該 user 所有 refresh,寫所有 active access 的 blacklist(若可知)

完整 auth flow(OAuth → token 發放 / 續期 / 撤銷)交由後續 spec 處理,本 ADR 僅鎖定策略。

## 權衡

捨棄項目與接受成本:

- **3 小時 access 外洩曝險** — 比 15m 高,接受;緊急時 Redis blacklist 可立即斷
- **Redis 故障 = refresh 失效** — 全使用者重登,影響可接受;由 AOF + managed Redis 降低機率
- **無歷史審計** — 無法事後查「某 token 是何時建立、從哪登入」,本專案無此需求
- **複雜度高於單 token** — 多寫 refresh / rotation / blacklist 邏輯,以換取可撤銷性

## 升級觸發

以下情況出現時,需重新評估,考慮升級為 **DB-backed refresh token**:

- 需要「查看 / 撤銷個別登入裝置」UI
- 合規 / 法規要求 token 發放紀錄保留 ≥ N 天
- 多區域 / 多 Redis cluster 之間需要強一致同步
- 異常登入分析(IP / UA pattern detection)成為產品需求

## 下游影響

本決策確定後,需更新:

- **Spec 001(環境設定)§3.4**:JWT 區塊拆成 access / refresh 兩組變數
- **Spec 002(`.env.example` 模板)§3.3**:目標草案改寫
- **Spec 003(未來):Auth flow 規格**:OAuth callback → token 發放 / 續期 / 撤銷 / 端點定義

實作順序:更新 spec 001 → 更新 spec 002 → 寫 spec 003 → 動程式碼。
