# Secure Context Requirements（HTTPS 與瀏覽器 API）

紀錄本專案在 prod 端**必須走 HTTPS** 的原因、影響哪些功能、以及在純 HTTP 下會踩到什麼行為。供部署與除錯時參考。

---

## 1. 背景

部分現代 Web API 在 spec 上被分類為 **"secure context only"** —— 瀏覽器**只在以下三種情境**才會把 `window` / `navigator` / `document` 上的對應 method 暴露給 JS：

| 情境 | 是否 secure |
|---|---|
| `https://*` | ✅ |
| `http://localhost` / `http://127.0.0.1` / `http://*.localhost` | ✅（瀏覽器例外） |
| `file://` | ✅（部分功能） |
| `http://任何其他域名` | ❌（API 不存在 / 拋 SecurityError） |

`window.isSecureContext` 為 `true` 才會暴露這些 API。HTTP prod 站永遠 `false`。

> 為何 localhost 例外：dev 階段強迫每個人架 self-signed cert 太重。但這也讓 dev / prod 在這層行為上**不一致**——本機跑得好不代表 prod 跑得好。

---

## 2. 本專案受影響的 API

| API | 用途 | 不在 secure context 的行為 |
|---|---|---|
| `navigator.share(...)` | [`ShareIconButton`](../../frontend/docs/specs/004a-charity-detail.md) v0.3 開系統 share sheet | `navigator.share` **undefined**——JS 層直接拿不到，無 polyfill 可救 |
| `navigator.clipboard.writeText(url)` | 同上的 fallback、未來其他「複製連結」場景 | `navigator.clipboard` **undefined** |
| `crypto.subtle` | 未來 client-side 加密（目前未用） | undefined |
| Service Worker / Push Notification | （未用） | 註冊失敗 |
| Geolocation `getCurrentPosition` | （未用） | 直接拒絕 |

`<ShareIconButton>` 已實作 share API + clipboard 兩層 fallback；HTTP 環境下**兩層都會 undefined**，落到 error toast。Toast 文案依 `window.isSecureContext` 分流：

| `isSecureContext` | toast | 對應情境 |
|---|---|---|
| `false` | 「HTTP 無法使用分享功能」 | 純 HTTP prod（最常見） |
| `true` | 「無法分享」 | HTTPS 下罕見路徑：老瀏覽器無 share API + iframe 擋 clipboard 等 |

這樣使用者回報「prod 跳無法分享」時，看到精確訊息能直接導向部署層，不會浪費時間找 client bug。

---

## 3. 症狀對照

開 prod 站 DevTools console 跑這三行可快速判定：

```js
window.isSecureContext        // false → 純 HTTP；true → HTTPS 或 localhost
typeof navigator.share        // 'undefined' → share API 不可用
typeof navigator.clipboard    // 'undefined' → clipboard API 不可用
```

| 觀察 | 推測 |
|---|---|
| 三個都 false / undefined | 純 HTTP，需上 HTTPS |
| isSecureContext=true 但 share='undefined' | 桌機 Firefox / 部分舊版瀏覽器（share API 未實作） |
| 都 ok 但 writeText 失敗 | Permission-Policy header 或 iframe sandbox 擋掉 |

---

## 4. 部署要求

**Production 必須走 HTTPS**。可選方案（按本專案實際組態優先排序）：

1. **ECS 前 ALB + ACM 憑證 + Route 53 alias**（本專案目標架構，[ADR 008](../decisions/008-ecs-cicd-pipeline.md)）
2. CloudFront → ECS（同樣由 CF 端 cert termination；origin 內網仍可 HTTP）
3. EC2 + nginx + Let's Encrypt（self-host pattern）
4. Cloudflare proxy 模式（最便宜的 dev 階段方案，CF 端 cert 自帶）

只要瀏覽器端看到的是 `https://`，**origin 後段是否走 HTTP 不影響** secure-context 判定（瀏覽器只看 page URL）。

---

## 5. 沒有 HTTPS 也想救的選項（目前未實作）

| 選項 | 救得到的功能 | 救不到的 | 成本 |
|---|---|---|---|
| `document.execCommand('copy')` legacy fallback | 複製連結到剪貼簿 | 系統 share sheet | 30 行 code + 3 test case |
| 手刻分享 menu（mailto / twitter intent / line share URL...） | 走外連分享 | 體驗不如原生 sheet | 中等 |
| 直接 prompt `window.prompt('複製此網址', url)` | 使用者手動 select+copy | UX 醜 | 5 行 |

`execCommand` spec 雖 deprecated，所有瀏覽器都會繼續支援很多年（web compat）。**不需 secure context**。

> 本作業範圍內**不採行**——HTTPS 是長期正確答案，加 fallback 只是繞道。Demo 階段若需展示，部署到 HTTPS 環境（CF / Vercel preview 都自帶）即可。

---

## 6. Cross-reference

- 元件實作：`frontend/src/components/ui/ShareIconButton.tsx`
- 元件規格：[frontend spec 004a §7 開放問題](../../frontend/docs/specs/004a-charity-detail.md)
- 部署 ADR：[ADR 008 — ECS CI/CD pipeline](../decisions/008-ecs-cicd-pipeline.md)
- 來源：MDN [Secure contexts](https://developer.mozilla.org/en-US/docs/Web/Security/Secure_Contexts) / [Web Share API browser compatibility](https://developer.mozilla.org/en-US/docs/Web/API/Navigator/share#browser_compatibility)
