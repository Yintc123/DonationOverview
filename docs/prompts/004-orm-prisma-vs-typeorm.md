# 精選 Prompt:ORM 選型 Prisma vs TypeORM

日期:2026-06-13
對應 ADR:[007-orm-prisma.md](../decisions/007-orm-prisma.md)

## 情境

ADR 002(backend framework)與 ADR 003(database PostgreSQL)在撰寫時都把「使用 Prisma」當作既定前提帶入,但從未獨立比較過其他主流 Node.js ORM。

這在文件結構上留了一個破口:面試官如果追問「為什麼是 Prisma 不是 TypeORM」,現有 ADR 只能回答片段。因此需要補一份獨立 ADR,把這個決策正式落地、並回頭把相關 ADR 串起來。

## 我的 Prompt

> 為什麼 backend 專案使用 prisma 而不是 typeORM 嗎?

(後續)

> 好,幫我寫一個 ADR

## AI 產出摘要

**第一輪回應**:
- 主動指出「目前沒有專門針對 Prisma vs TypeORM 的 ADR」,Prisma 是 ADR 002/003 的隱含前提
- 從現有 ADR 推導出選 Prisma 的四個理由(型別端到端推導、Migration 工具成熟度、PostgreSQL 一級支援、面試展示價值)
- 主動建議「要不要把這個決策獨立寫成 ADR」,而不是直接動手寫

**第二輪回應**:
- 產出 `docs/decisions/007-orm-prisma.md`,涵蓋背景、八面向比較表、決策、實作要點、未來再評估點
- 額外解釋為何也不選 Drizzle / Kysely(回應潛在追問)
- 完成後主動提兩個延伸動作:更新 ADR 002/003 cross-reference、把這段對話寫成精選 prompt

## 我的判斷與後續調整

**判斷一:接受獨立 ADR 的建議**

Claude 點出「決策散落在 ADR 002/003 字裡行間」這個問題很準。隱含決策對自己讀沒問題,但對審閱者(面試官)就是缺漏。把它顯性化是低成本高回報。

**判斷二:接受 cross-reference 補強**

ADR 之間互相串連可以讓審閱者沿著思路走。已在:
- ADR 002 套件清單後加註「ORM 選型完整評估見 ADR 007」
- ADR 003 背景段加註「完整 vs TypeORM 評估見 ADR 007」

**判斷三:對 Drizzle 段落的態度**

Claude 在 ADR 中主動加了「為何不選 Drizzle / Kysely」一節,並把 Drizzle 標為「未來替換首選」。這個態度誠實——Drizzle 在 2026 確實是 Prisma 的最大競爭者,刻意迴避反而顯得不老實。保留。

**展示重點**

這段對話想呈現的工程判斷:

1. **發現隱含決策並要求補正**:好的決策紀錄不能依賴讀者「自己推」,要顯性化
2. **AI 主動提醒文件互聯**:ADR 之間的 cross-reference 是審閱動線,值得補
3. **誠實面對更新的替代方案**:Drizzle 段落不是貶低自己的選擇,是說明選 Prisma 時清楚知道權衡邊界在哪

## 相關檔案

- [docs/decisions/007-orm-prisma.md](../decisions/007-orm-prisma.md)
- [docs/decisions/002-backend-framework.md](../decisions/002-backend-framework.md)(已更新 cross-reference)
- [docs/decisions/003-database-postgresql.md](../decisions/003-database-postgresql.md)(已更新 cross-reference)
- 原始 session 對話:`raw/2026-06-13-session-<id>.readable.md`(session 結束後補上)
