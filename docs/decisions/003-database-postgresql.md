# 決策:資料庫採用 PostgreSQL

日期:2026-06-13

## 背景

`backend/` 服務需要持久化以下資料:

- 使用者帳號(Google OAuth 登入後建立)
- 捐款紀錄(交易語意,需強一致性)
- 受款專案 / 受款對象(關聯性高)
- 後續可能擴充:訂閱型定期捐款、稅務收據、活動紀錄

需選定關聯式 / 非關聯式資料庫與具體產品。Prisma ORM 已於 ADR 002 確定使用,本決策僅涵蓋資料庫引擎本身。

## 選項評估

| 選項 | 優勢 | 劣勢 | 結論 |
|---|---|---|---|
| **PostgreSQL** | ACID、豐富型別(JSONB、UUID、enum、numeric)、`pg_trgm` 全文搜尋、Prisma 一級支援、業界主流 | 自架運維比 SQLite 重 | ✅ 採用 |
| MySQL | 同為成熟關聯式 DB,部署選擇多 | JSON 支援與型別豐富度遜於 PostgreSQL;Prisma 支援良好但社群活躍度較低 | ❌ 無明顯優勢 |
| SQLite | 零部署、開發快 | 不適合多寫入並發、缺乏 numeric / enum / JSONB,prod 與 dev 行為差異大,違反 backend `CLAUDE.md` 「不用 in-memory mock」原則 | ❌ 僅可能用於極輕量場景 |
| MongoDB | schema-less、開發初期靈活 | 捐款資料屬強關聯(user → donation → project),join 需求高;事務語意較弱;與 Prisma 整合不如關聯式 DB 自然 | ❌ 與資料模型不匹配 |

## 決策

採用 **PostgreSQL 16**(對齊 `.github/workflows/ci.yml` 已採用的版本)。

## 理由

1. **交易語意**:捐款流程涉及金額扣抵 / 紀錄寫入 / 通知,需要 ACID 與 row-level lock。PostgreSQL 在這方面是業界標準
2. **型別豐富**:
   - `numeric(12, 2)` 處理金額,避免浮點誤差
   - `uuid` 原生,Prisma `@default(uuid())` 直接用
   - `enum` 表達狀態機(donation status、user role)
   - `jsonb` 存彈性資料(metadata、event payload),仍可索引
3. **Prisma 一級支援**:relation、type、migration 在 PostgreSQL 上最完整;`Prisma Studio` 開發體驗順
4. **測試策略一致性**:呼應 backend `CLAUDE.md`,測試用 `testcontainers` 起 PostgreSQL 16,與 prod 同型,避免 mock 假象
5. **生態與運維**:Supabase / Neon / Railway / RDS 等託管選項多,未來部署彈性大

## 實作要點

### 版本

- **PostgreSQL 16**(LTS、與 CI service container 一致)

### 連線

- 由 `DATABASE_URL` 環境變數提供,格式詳見 spec `backend/docs/specs/001-environment-config.md`
- dev / stage / prod 三環境獨立 instance,絕不共用

### Schema 管理

- 使用 **Prisma Migrate**(`prisma migrate dev` / `prisma migrate deploy`)
- migration 檔案進入版控,審查時與 PR 一同 review
- 重大 migration(rename、drop column、type change)需在 stage 驗證後才上 prod

### 命名

- table 名稱:Prisma 預設 `PascalCase` model → DB 端可用 `@@map("snake_case")` 統一為 snake_case
- 欄位:Prisma `camelCase` → DB `@map("snake_case")`(避免 quoting 不便)

### 金額處理

- **一律使用 `Decimal`**(Prisma `Decimal` / PostgreSQL `numeric`),禁用 `Float`
- 精度建議 `numeric(12, 2)`(支援到 99 億,可調)

### 待補規格

以下交由後續 spec 處理,本 ADR 不展開:

- 資料模型(`User`、`Donation`、`Project` 等的 schema)
- 索引策略
- soft delete / audit log 政策

## 權衡

捨棄項目:

- SQLite 的零部署便利(dev 仍可直接用 `docker-compose` 起 local Postgres,影響可接受)
- MongoDB 的 schema 彈性(我們的資料模型偏關聯,JSONB 已足夠處理 metadata 彈性需求)

未來若需要:

- 全文搜尋:可加 `pg_trgm` 或 OpenSearch
- 時序資料(活動 metrics):可加 TimescaleDB 擴充或另起時序資料庫
- 大量讀:可加 read replica,Prisma 5+ 支援
