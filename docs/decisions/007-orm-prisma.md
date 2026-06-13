# 決策:ORM 採用 Prisma(不採 TypeORM)

日期:2026-06-13

## 背景

ADR 002(backend framework)與 ADR 003(database PostgreSQL)中,Prisma 已被當作既定前提帶入,但未獨立比較與其他主流 Node.js ORM 的取捨。為補上這段決策紀錄、便於日後審視,本 ADR 正式評估 Prisma 與 TypeORM 兩者,並順帶說明為何不採近年興起的 Drizzle / Kysely。

候選方案需滿足的條件:

- TypeScript 一級支援、型別能與 Fastify TypeBox schema 串成端到端推導
- PostgreSQL 完整支援(`numeric`、`uuid`、`enum`、`jsonb`、relation)
- Migration 工具成熟,可進版控
- 與 `@fastify/*` 生態相容

## 選項評估

| 角度 | Prisma | TypeORM | 結論 |
|---|---|---|---|
| **型別推導** | 由 `schema.prisma` 產生精確型別,relation include / select 後型別會自動窄化,end-to-end 不斷鏈 | 依賴 decorator + `reflect-metadata`,relation 預設為 `Promise<T>` 或 `T \| undefined`;`find` 的 `relations` 選項不會反映在回傳型別,常需手動 cast | Prisma 明顯勝出 |
| **Schema 來源** | 單一 `schema.prisma` DSL,model / relation / index / enum 集中管理 | entity class + decorator 散落各檔,需配合 `synchronize` 或 migration 才能一致 | Prisma 較適合 schema-driven 開發 |
| **Migration** | `prisma migrate dev` 比對 schema 與 DB 自動產 SQL;`migrate deploy` 生產用,行為明確 | `typeorm migration:generate` 對 entity 改動的偵測歷史上常漏(尤其 relation / enum 變更),需要人工補 SQL | Prisma 較可靠 |
| **PostgreSQL 型別** | `Decimal`、`Json`、`Bytes`、`enum`、`uuid` 原生對應,自動產生 TS 型別 | 支援度足夠,但 `numeric` 預設回傳 `string`,需自寫 transformer | Prisma 開箱即用 |
| **Fastify 整合** | 直接 `new PrismaClient()`,搭配 TypeBox schema 形成「request 型別 → Prisma 操作 → response 型別」單一推導鏈 | 同樣可用,但因型別偏弱,schema-driven 風格效益打折 | Prisma 配合度高 |
| **生態活躍度** | npm 週下載 ~5M+、活躍社群、Vercel / Supabase / Neon 等平台一級支援 | npm 週下載 ~2M、近 1-2 年 commit 頻率明顯下降、長期維護者離開引發討論 | Prisma 領先 |
| **效能** | 透過 query engine(Rust binary),簡單查詢有額外開銷,複雜 join 表現穩定;v5+ 推出 driver adapter 可繞過 | 純 JS,簡單查詢開銷較低,但複雜查詢容易產生 N+1 | 本專案讀寫量級下兩者皆夠 |
| **學習曲線** | DSL 與生成式 client,概念單純但需學 schema 語法 | OO + Active Record / Data Mapper,熟悉 Java 系 ORM 者上手快 | 主觀,本專案選 Prisma 簡潔性 |

### 為何也不選 Drizzle / Kysely

- **Drizzle**:型別體驗極佳、SQL-like API、無 query engine 開銷,是 Prisma 真正的競爭者。但 migration 工具(`drizzle-kit`)成熟度仍在追趕中,且面試作業希望展現「已驗證的選型判斷」,Prisma 在 2026 仍是業界主流預設值,更貼近真實工作場景。Drizzle 列為**未來替換的首選**。
- **Kysely**:純 query builder,型別安全且輕量,但不含 migration / schema 管理,需自行搭配其他工具。本專案希望單一工具覆蓋 schema + migration + client,不分散選型成本。

## 決策

採用 **Prisma 5.x**(`prisma` + `@prisma/client`),作為 backend 唯一的資料存取層。

## 理由

1. **型別端到端不斷鏈**:呼應 ADR 002「Fastify schema-driven」核心訴求。從 `schema.prisma` 產生的 `@prisma/client` 型別,可直接餵給 Fastify route handler 的 response,搭配 TypeBox 形成完整推導鏈,面試展示價值高
2. **Migration 可靠性**:`prisma migrate` 對 schema 變更偵測穩定,migration 檔可進版控、可在 CI 跑 `migrate deploy`,降低 prod 變更風險
3. **PostgreSQL 型別對齊**:ADR 003 規定金額一律 `Decimal`、ID 用 `uuid`、狀態用 `enum`,這些在 Prisma 都是原生對應,無需額外 transformer
4. **生態與部署彈性**:Supabase / Neon / Vercel Postgres 都將 Prisma 列為推薦 ORM,未來部署選擇不被綁死
5. **TypeORM 維護動能下滑**:核心維護者異動、issue 累積、release cadence 變慢,長期風險高於收益

## 不採用 TypeORM 的權衡

捨棄項目:

- TypeORM 的 Active Record 風格(entity 自帶 `.save()`)對 OO 思維友善,但本專案傾向函式式 service layer,影響小
- TypeORM 與 NestJS 的官方整合(`@nestjs/typeorm`):本專案用 Fastify,不適用
- TypeORM 較成熟的 multi-database 支援(同時連 MySQL + Mongo 等):本專案只用 PostgreSQL,不需要

## 實作要點

### 套件

- `prisma`(dev dependency,CLI / migrate)
- `@prisma/client`(runtime)
- `prisma-erd-generator` 或 `prisma-dbml-generator`(可選,文件用)

### 目錄結構

```
backend/
├── prisma/
│   ├── schema.prisma
│   ├── migrations/
│   └── seed.ts
└── src/
    └── db/
        └── client.ts   # 共用的 PrismaClient instance(singleton)
```

### Client 生命週期

- 全專案共用單一 `PrismaClient` instance(避免連線數爆炸)
- 透過 `@fastify/awilix` 或 plugin 注入到 route context
- 測試環境用 `testcontainers` 起獨立 PostgreSQL,每個測試檔獨立 schema

### 命名對齊 ADR 003

- model 用 `PascalCase`、`@@map("snake_case")` 對應 DB
- 欄位用 `camelCase`、`@map("snake_case")` 對應 DB

### 金額型別

- 一律使用 Prisma `Decimal`(對應 PostgreSQL `numeric(12, 2)`)
- API 邊界轉字串輸出,避免 JSON `number` 精度問題

### Migration 流程

- 開發:`prisma migrate dev --name <description>`
- CI:`prisma migrate deploy`(不會自動產生 migration)
- 重大變更(rename / drop / type change)需在 PR 描述標註,並於 stage 驗證後才 prod

### 待補規格

以下交由 spec 處理,本 ADR 不展開:

- 完整 schema(`User`、`Donation`、`Project` 等)
- soft delete 策略(`deletedAt` 欄位 vs Prisma extension)
- audit log 機制(中介層 vs DB trigger)
- 連線池與 read replica 配置

## 未來再評估

- **Drizzle 成熟後可重新評估**:若 `drizzle-kit` migration / introspection 進入穩定且生態擴大,Prisma 的 query engine 開銷與 cold start 成本將不再划算
- **效能瓶頸出現時**:可考慮對熱點查詢用 `$queryRaw` 或加 driver adapter(v5+),不需整體換 ORM
