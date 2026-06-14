# 決策:DB schema migration 透過一次性 ECS task 在 rolling deploy 之前執行

日期:2026-06-14

## 背景

ADR 008 把 backend 的 GHA → ECR → ECS Fargate rolling deploy 跑通,ADR 009 把 PG / Redis 的安全邊界(SG only-from-ECS、最小存取面)落實。在此之上,backend 透過 Prisma Migrate 管理 schema 演進,但「**deploy 流程要在什麼時候、什麼地方、用什麼身分跑 `prisma migrate deploy`**」仍未定錨。

具體會反覆出現的疑問:

1. 為什麼不直接在 `Dockerfile` 多開一個 stage 跑 migration?
2. 為什麼不在 GHA runner 直接 `npm run prisma:migrate:deploy`?
3. 為什麼不讓 container 啟動時自己跑(`CMD ["sh", "-c", "npx prisma migrate deploy && node dist/server.js"]`)?
4. migration 失敗時,backend 服務的狀態應該是什麼?
5. 之後其他「需要碰 VPC 私網資源」的維運工作(backup / restore、cache warm-up、一次性資料修正),要走同樣模式嗎?

問題 1-3 的直覺都看似合理,但實際上分別違反了 build/deploy 分離、安全邊界、單一 image 跨環境部署這幾個既有設計原則。本 ADR 定錨 migration 流程,並在過程中把這幾個原則明文化,讓問題 5 的延伸場景能直接套用同一份決策。

候選方案需滿足的約束:

- migration 在 application 容器啟動前完成,失敗則 deploy 中止、舊版仍在線
- 不開放 EC2 PG SG 給 VPC 以外的對象(維持 ADR 009 §4 的最小存取面)
- image artifact 跨環境可重用(prod / staging 共用同一個 image,只透過 deploy 時的環境參數區分)
- 多 task 同時啟動時不會競態跑 migration
- GHA runner 不需要新 IAM 權限以外的網路改動

## 選項評估

### 1. 何時跑 migration:build-time vs deploy-time

| 方案 | 描述 | 利 | 弊 |
|---|---|---|---|
| **A. Build-time:Dockerfile 多開 stage 跑 migrate** | `RUN npx prisma migrate deploy` 寫進 Dockerfile | 概念上「最早完成」 | ❌ GHA runner 在 GitHub 公有雲,build context 無路徑連 VPC 私網 PG;❌ Image build 必須 deterministic、無副作用,migration 是 stateful mutation,違反此契約;❌ 一個 image 部到多環境(dev/staging/prod),migration 不能 bake 進 artifact;❌ Build 失敗可能留下部分套用的 schema,沒有清楚的回復點 |
| **B. Deploy-time on GHA runner** | `aws-actions/...` 之後直接 `npm run prisma:migrate:deploy` | 實作最簡單 | ❌ GHA runner IP 不在 EC2 SG 允許清單(ADR 009 §4),封包打到 5432 被擋;❌ 開 SG 給 GitHub IP 範圍等於對 internet 部分開放(GitHub 的 IP 池幾千個 + 會輪換);❌ 即使用 SSM Session Manager 隧道也大幅增加維運面 |
| **C. Deploy-time on ECS one-shot task**(採用) | GHA 呼叫 `ecs:RunTask`,跑跟 backend 同 image、override command 為 `prisma migrate deploy` | ✅ 在 VPC 內帶對的 SG,自然能連 PG;✅ image artifact 無副作用,跨環境共用;✅ migration 失敗 → GHA fail → 不觸發 UpdateService → 舊版繼續服務;✅ 只跑一次,沒有 multi-task 競態;✅ 共用既有的 task definition / log group / secrets / IAM | task 啟動 30-60 秒(Fargate ENI provisioning),CD 整體時間 +1-2 分鐘 |
| D. Container startup:CMD 串接 migrate + server | `CMD ["sh","-c","npx prisma migrate deploy && node dist/server.js"]` | 不需要改 GHA workflow | ❌ Rolling deploy 期間 N+1 個 container 同時啟動,全部搶 migration;❌ Prisma advisory lock 雖然能擋並發,但敗者卡 startup;❌ Migration 失敗 → container 起不來 → ECS 認為 unhealthy → 不斷重啟,log 灌爆;❌ 將 schema migration 跟 application liveness 耦合,失敗模式難 debug |

→ **採方案 C**。方案 A 違反建構原則,方案 B 違反 ADR 009 攻擊面原則,方案 D 在 rolling deploy 拓樸下有實際失敗模式。

### 2. Migration 用的容器 image:共用 backend image vs 獨立 migrator image

| 方案 | 描述 | 利 | 弊 |
|---|---|---|---|
| **C-1. 共用 backend image**(採用) | 把 `prisma` 從 `devDependencies` 移到 `dependencies`,runtime image 內含 CLI;RunTask 用 `containerOverrides` 換 command | 一個 image 多用途;不必額外 ECR repo / Dockerfile;`prisma db execute` 緊急修復也可直接用 | runtime image +~30 MB(Prisma CLI 體積) |
| C-2. 獨立 `Dockerfile.migrator` | 另寫一份只裝 prisma CLI + schema + migrations 的小 image | runtime image 維持瘦身 | ❌ 多一份 image / ECR repo / task def 維護;❌ 兩個 image 的 prisma version drift 風險;❌ deploy.yml 變雙 image build/push,複雜 |
| C-3. Runtime 階段補裝 prisma | Dockerfile runtime stage 加 `RUN npm install --no-save prisma` | image 體積比 C-1 略小(只 CLI) | ❌ 增加 image layer + build 時間;❌ install 受 npm registry availability 影響,build 變脆 |

→ **採 C-1**。30 MB 的代價換取單一 image artifact 跟最低維運開銷,符合 12-factor「build/release/run 三階段對應單一 artifact」原則。

### 3. Task definition revision 註冊策略

| 方案 | 描述 | 結果 |
|---|---|---|
| 用 `aws-actions/amazon-ecs-deploy-task-definition@v2` 註冊 | 此 action 內部會 RegisterTaskDefinition + UpdateService | 兩次註冊(migrate 一次、deploy 一次)= 兩個 revision,差別只在 `containerOverrides` 不算進 revision diff,所以兩個 revision 內容相同,純浪費 |
| **手動 `aws ecs register-task-definition` 一次,RunTask + UpdateService 都用同一個 ARN**(採用) | 註冊 revision N,RunTask 跑 N(override command)、UpdateService 也指 N | 一次註冊、ARN 在 step output 流轉、`_prisma_migrations` 跟 task def revision 1:1 對應 |

→ **採用一次註冊**,實作上以 step output(`steps.register.outputs.arn`)在多個 step 間共享 ARN。

### 4. Migration 失敗時的 deploy 行為

| 方案 | 描述 | 結果 |
|---|---|---|
| Migration 失敗仍繼續 UpdateService | 容忍 partial-state 部署 | ❌ application 跑在跟自身 schema 不對應的 DB 上,500 error / 資料毀損風險 |
| **Migration 失敗則 abort,舊版繼續服務**(採用) | GHA step `exit 1`,後續 UpdateService 跳過 | ✅ application 永遠跑在符合 schema 的 DB;✅ ECS service 維持 last-known-good 狀態,有時間人工介入;✅ migration 修正後重跑 workflow_dispatch,從 register 後重新走流程 |

## 決策

採用 **C + C-1 + 一次註冊 + Migration 失敗則 abort**,具體實作:

1. `backend/package.json` 將 `prisma` 從 `devDependencies` 改為 `dependencies`,runtime image 帶 CLI
2. `backend/.github/workflows/deploy.yml` 在現有 build / push / render 步驟之後、UpdateService 之前插入:
   - `Register task definition` — 註冊一個 revision,輸出 ARN
   - `Run Prisma migrate (one-shot ECS task)` — `aws ecs run-task` 用 ARN + `containerOverrides`(command 改為 `npx prisma migrate deploy`)+ `awsvpcConfiguration`(backend task 的 subnet + SG)+ `assignPublicIp=DISABLED`
   - `aws ecs wait tasks-stopped` 等任務退出,`describe-tasks` 取得 exit code 與 stoppedReason,非 0 則 `exit 1`
3. `Update ECS service (rolling deploy)` 改用 `aws ecs update-service` 直接指 step 2 的同一個 ARN(取代原本的 `amazon-ecs-deploy-task-definition` action,避免二次註冊)

### 必要的 IAM 權限(backend deploy role)

backend repo 的 OIDC role(命名 `github-actions-deploy-jkoBackend`,對齊 overview 的 `github-actions-deploy-jkoOverview` pattern)需有以下 inline policy(`JkoBackendDeployPolicy`):

```json
{
  "Effect": "Allow",
  "Action": ["ecs:RunTask", "ecs:DescribeTasks"],
  "Resource": "*"
}
```

`iam:PassRole` 對 `jko_ecs` 已有(ADR 008),無需新增——RunTask 用同一個 execution role。

### 必要的 GitHub repo variables

| Variable | 用途 |
|---|---|
| `ECS_SUBNETS` | backend service 所在 subnet IDs,逗號分隔。RunTask 必須指定 subnet 才能 schedule Fargate task |
| `BACKEND_TASK_SG` | backend ECS task 的 SG ID。RunTask 帶這個 SG 才能通過 EC2 PG 的 inbound 規則 |

## 理由

### 1. Build-time 跟 deploy-time 是兩個契約不同的階段

Build-time 的契約是「**deterministic、無副作用、無外部依賴**」——同樣的 source + Dockerfile 必須產出同樣的 image(checksum 相同)。一旦 build 過程對 DB 做 mutation,這個契約立即破裂,而且帶來幾個連鎖後果:

- ECR `IMMUTABLE` tag 假設「同 SHA = 同 image」,build-time side effect 破壞此假設
- 重 build 同一個 SHA 在不同時間點會產出不同 image(因為 DB 狀態變了)
- Build 失敗時 DB 可能已部分 mutation,沒有清楚的回復語意

Deploy-time 才是 stateful 操作的歸宿——它本來就針對特定環境、必然有副作用、有明確的成功/失敗信號。

### 2. ADR 009 §4 的最小存取面要求 migration 從 VPC 內發起

ADR 009 把 PG / Redis 的 SG 設定成「only-from-ECS-task-SG」是 defense-in-depth 的核心,擋下的攻擊向量包括:GitHub 帳號被入侵後直連 prod DB、public scan、同 VPC 跨 SG 橫向移動。

如果為了 migration 開放 GHA runner 連線,等於把這個攻擊面強行打開——GHA runner 的 IP 範圍涵蓋 GitHub 整個基礎設施,實質上是對 public internet 部分開放。

把 migration 移到 ECS task 跑,意味著「**任何需要碰 prod DB 的工作,執行者都要在 VPC 內帶對的 SG**」這個原則沒有例外,SG 規則就是唯一的入口控制。

### 3. 共用 application image 符合 12-factor build/release/run 分離

12-factor 第五點(Build, release, run)要求:

- **Build** 階段產生不可變的 artifact(image)
- **Release** 階段把 artifact + 環境設定組合成 release
- **Run** 階段執行 release

Migration 屬於 release 階段的一部分(它跟特定環境的 DB 綁定),不該洩漏到 build。共用 backend image 讓單一 artifact 跨環境部署 — 同一個 image 在 staging 環境的 release 跑 migration 連到 staging DB、prod release 跑 migration 連到 prod DB。

### 4. ECS task 已備齊 migration 所需的所有條件

application container 為了在 Fargate 啟動,已經設置了:

- 對的 VPC / subnet(網路可達 PG)
- 對的 SG(SG 規則允許)
- Secrets Manager 讀取權限(`DB_PASSWORD` 在 `jko_vm_pg_redis_1:POSTGRES_PASSWORD`)
- IAM execution role(`jko_ecs`)
- log group + awslogs driver(`/ecs/jko-backend`)
- 環境變數(DB_HOST、DB_USER、DB_NAME、...)

**所有 migration 需要的執行環境,application 階段已備齊**。共用同一份 task definition + image 等於把這份設置的價值用兩次,額外成本接近 0。

### 5. 一次性 RunTask 是「VPC-only 維運工作」的可重複 pattern

migration 不會是唯一一個需要碰 VPC 私網資源的維運工作。後續會出現:

- **Database backup / restore**:`pg_dump` / `pg_restore`
- **Cache warm-up**:啟動前預熱 Redis
- **Search index rebuild**:從 PG 撈資料重建索引
- **一次性資料修正腳本**:bug fix 後的歷史資料校正
- **Metrics 撈取**:從 PG / Redis 撈統計

這些**全部**面臨跟 migration 一樣的網路 / SG 約束,因此**全部**走同樣 pattern:

```
GHA workflow
  → ecs:RunTask 帶 containerOverrides
  → ecs:DescribeTasks 檢查結果
  → 成功才繼續、失敗即 abort
```

把 migration 的實作建立成模板,未來上述任一場景出現時都能複用同一個 workflow 結構,只改 `command` overrides。

### 6. 失敗即中止比「容忍部分失敗」更安全

application 程式碼跟 DB schema 是緊耦合的——code path 假設特定欄位 / table 存在。如果 migration 失敗仍繼續 UpdateService,新 application 會跑在「自身假設」與「DB 實際 schema」不一致的環境上,輕則 500 error、重則資料毀損。

讓 GHA 在 migration 失敗時 `exit 1`、跳過 UpdateService,意味著 ECS service 維持 last-known-good 狀態。應用層繼續以舊版服務、舊 DB schema(本來就匹配),問題沒擴散。debug 時間由「線上事故」變成「下一次 deploy 之前」,可控性高很多。

## 後續

| 項目 | 觸發條件 | 動作 |
|---|---|---|
| 為其他維運操作建立模板 | 第一次出現 VPC-only 維運需求(backup / index rebuild 等) | 拷貝 deploy.yml 的 register + RunTask + wait 三步驟,改 `command` overrides 即可 |
| Migration dry-run | Schema 變動觸及 prod 既有資料(rename / type change) | 加 `prisma migrate diff --exit-code` 在 CI 階段預先警告 |
| Migration 性能監控 | Single migration 超過 30 秒 | RunTask 加 `cloudwatchLogsLogGroup` 注 metric,超時 alert |
| Zero-downtime schema change | 流量規模到 prod 級 | 採 expand-contract pattern(加欄不刪欄、雙寫、cutover、移除舊欄分兩個 release ship) |
| Migration rollback 策略 | 第一次發生需要回滾 migration | 評估「寫一個反向 migration」vs「`prisma migrate resolve --rolled-back` 跳過後手動 SQL」 — 目前無 down migration,先以 forward-only 為原則 |
| 跨 repo 共用 workflow | frontend 也加類似步驟 | 抽 reusable workflow(`workflow_call`),deploy.yml 改為呼叫 |

## 變更紀錄

| 版本 | 日期 | 變更 |
|---|---|---|
| 0.1 | 2026-06-14 | 初版;定錨 one-shot ECS task migration pattern + VPC-only 維運模板 |
