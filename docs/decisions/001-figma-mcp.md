# 決策：使用 Figma MCP 讀取設計稿

日期：2026-06-13

## 背景

專案為 `2026 全端面試作業 - web`，設計稿放在 Figma：
<https://www.figma.com/design/0kx2Ne2rvndhfVr3uVUwad/2026-%E5%85%A8%E7%AB%AF%E9%9D%A2%E8%A9%A6%E4%BD%9C%E6%A5%AD---web>

需要讓 Claude Code 能讀取 Figma 設計內容（frame、文字、樣式、圖片資產），以輔助前端實作。

## 選項評估

| 方案 | 機制 | 限制 | 結論 |
|---|---|---|---|
| WebFetch 直接抓 URL | 抓 Figma 頁面 HTML | Figma 為 JS 渲染，只能拿到頂層 "Figma" 字串，拿不到設計內容 | ❌ 無效 |
| 官方 Figma Dev Mode MCP | Figma 桌面 App 內建，讀取當下選取的 frame | 需 Dev 或 Full seat，使用者只有 Viewer + comment 權限 | ❌ 不符權限條件 |
| 社群版 `figma-developer-mcp` | 走 Figma REST API + Personal Access Token | Viewer 權限即可讀檔 | ✅ 採用 |

## 決策

採用社群版 `figma-developer-mcp`，搭配 Figma Personal Access Token。

## 實作步驟

### 1. 產生 Personal Access Token

到 <https://www.figma.com/settings> → Security → Personal access tokens → Generate new token

權限只需勾選 `File content: Read-only`。

### 2. 安裝 MCP（專案範圍）

```bash
claude mcp add figma --scope project \
  --env FIGMA_API_KEY=你的token \
  -- npx -y figma-developer-mcp --stdio
```

使用 `--scope project` 將設定寫在專案的 `.claude/settings.json`，不污染其他專案。

### 3. 重啟 Claude Code

設定後重新啟動，即可在對話中讀取 file key `0kx2Ne2rvndhfVr3uVUwad` 的設計內容。

## 清理步驟（專案結束後）

### 1. 移除 MCP 設定

```bash
claude mcp remove figma --scope project
```

### 2. 撤銷 Token

至 <https://www.figma.com/settings> → Security → Personal access tokens → Revoke。

### 3. （可選）清除 npx 快取

```bash
npm cache clean --force
```

僅為徹底清除快取，無敏感資料。
