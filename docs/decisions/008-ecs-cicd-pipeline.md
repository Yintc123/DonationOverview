# 決策:GHA → ECR → ECS Fargate CI/CD pipeline

日期:2026-06-13

## 背景

本專案最終會有三個獨立 GitHub repo 都要部署到 AWS:`infra`(本 repo,含 healthcheck 工具)、`backend`(Fastify + Prisma)、`frontend`(Next.js BFF)。在 backend / frontend 開始實作前,先以最小的 Flask healthcheck 服務(`infra/healthcheck/`)作為 pilot,把整條 CI/CD 走通,確認:

- IAM / OIDC 認證鏈
- Secrets 注入路徑
- Cluster / Service / Task definition 規格
- 應用層真的能跨 VPC 連到 EC2 上的 PG 與 Redis

待 pilot 跑通後,backend / frontend 可直接複用同一份模式,不必各自摸索。

候選方案需滿足的條件:

- 無長期 AWS access key 留在 GitHub Secrets
- ECS task 能讀 Secrets Manager 取得 PG / Redis 密碼
- task definition 模板放 repo,但敏感識別(account ID、私有 IP)不入版控
- 部署失敗可 idempotent 重跑,不卡 image tag 唯一性
- frontend / backend 加入時可平移最少改動

## 選項評估

### 1. ECS launch type:Fargate vs EC2

| 角度 | Fargate | EC2 | 結論 |
|---|---|---|---|
| 管理面 | AWS 託管,不必維護底層 OS / 容器 daemon | 需自管 EC2 instance、ECS agent | Fargate 簡單 |
| 計費 | 按 task vCPU / 記憶體秒計 | 按 EC2 instance 小時計,task 數量無關 | task 數穩定且不滿載 → Fargate 划算 |
| 啟動延遲 | 30-60 秒(會多 ENI provisioning) | 已有 instance 時 < 10 秒 | 本作業無 spike 流量,差異無感 |
| 適合場景 | 短跑、無狀態、流量可變 | 長跑、需要本地 cache、需 daemon set | healthcheck / backend / frontend 都偏 Fargate |

→ **採 Fargate**。EC2 (PG/Redis 主機)用 EC2 instance 是因為要 self-host 資料服務、需要 EBS 持久化,跟應用層的選擇正交。

### 2. AWS 認證:OIDC vs 長期 access key

| 角度 | OIDC(GitHub → IAM Role) | Access Key 存 GitHub Secrets | 結論 |
|---|---|---|---|
| 長期 secret 存放 | ❌ 無 | ✅ 有(=風險) | OIDC 安全 |
| Token 時效 | 每次 workflow 自動換、< 1 小時 | 永久,需手動輪換 | OIDC 安全 |
| Audit | CloudTrail 可看到「哪個 repo / branch / workflow」assume role | 只看得到 access key id | OIDC 可追蹤性高 |
| 設定成本 | 一次性 setup OIDC provider + trust policy | 加兩個 secret 就好 | OIDC 多花 30 分鐘 |
| 自動輪換 | 不需要 | 應每 90 天輪換,常被忽略 | OIDC 維運省事 |

→ **採 OIDC**。trust policy 用 `repo:<owner>/<repo>:ref:refs/heads/main` 限定特定 repo 的 main branch 才能 assume,進一步收斂攻擊面。

### 3. IAM role 結構:單一 deploy role vs per-repo deploy role

| 角度 | 單一 role(三個 repo 共用) | Per-repo role(三個 role) | 結論 |
|---|---|---|---|
| 維護成本 | 改 trust 一處 | 改 trust 三處 | 單一較省事 |
| 隔離性 | frontend repo 理論上可調 backend ECR | frontend role 完全看不到 backend ECR | Per-repo 較安全 |
| Audit 來源 | CloudTrail 看 role session name 才能分辨 | role ARN 直接區分 | Per-repo 清楚 |
| 多人協作擴充性 | 不適合(賦予一人即賦予所有 repo) | 可分人發 | Per-repo 較有彈性 |

→ **採 per-repo role**(`github-actions-jko-infra-deploy`、`...-backend-deploy`、`...-frontend-deploy`)。IAM 是免費的,沒有成本誘因共用。Permission policy 暫時共用同一份 inline 內容(三段:PushECR、DeployECS、PassRole),後續若要 resource-level least privilege 再個別收緊。

### 4. ECS Cluster:單一 vs per-service

| 角度 | 單一 cluster | Per-service cluster | 結論 |
|---|---|---|---|
| 成本 | Fargate cluster 本體免費 | 同上 | 無差 |
| Networking | 共 VPC,Service Connect 內部 DNS 簡單 | 跨 cluster 需 ALB / Cloud Map | 單一較簡單 |
| 觀測 | 一個 dashboard 看全部 | 分散 | 單一較好維運 |
| 隔離 | 同 cluster 內邏輯隔離 | 強隔離 | 個人作業不需要 |

→ **採單一 cluster** `jko-cluster`,healthcheck / backend / frontend service 都進去。未來進入 production / 合規環境再拆分。

### 5. Image tag 策略:`:latest` vs `:${{ github.sha }}` + IMMUTABLE

| 角度 | `:latest`(mutable) | `:${{ github.sha }}`(IMMUTABLE) | 結論 |
|---|---|---|---|
| 可回溯 | ❌ 沒人知道現在是哪個 commit | ✅ tag 即為 commit | SHA tag 勝 |
| 回滾速度 | 要重 build | 改 task def image 指到舊 tag 即可 | SHA tag 勝 |
| 防止意外覆蓋 | tag 可被覆蓋 | ECR IMMUTABLE 拒絕同名覆蓋 | IMMUTABLE 勝 |
| Re-run failed job 影響 | 重 build 蓋掉 latest | 同 tag push 會 fail,需 idempotent 處理 | IMMUTABLE 需配 idempotent build step |

→ **採 SHA tag + ECR IMMUTABLE 模式**。為解決「Re-run failed jobs 重 push 同 SHA」問題,build step 加 `aws ecr describe-images` 預檢,已存在則跳過 build/push,直接進下一步。

### 6. Secret 注入:Secrets Manager(整合 JSON)vs 拆分 vs SSM Parameter Store

PG 密碼與 Redis 密碼兩個機密。三種存法:

| 方案 | 月費 | task def 引用語法 | 共用 IAM 政策 |
|---|---|---|---|
| **A. 單一 secret + JSON 多 key**(採用) | $0.40 × 1 | `:secret:name:KEY::` | 一條 Resource 涵蓋 |
| B. 兩個獨立 secret | $0.40 × 2 | `:secret:name` | 兩條 Resource |
| C. SSM Parameter Store | 標準參數免費 | `arn:...:parameter/...` | 不同 service 命名空間 |

→ **採方案 A**:`jko_vm_pg_redis_1` 一個 secret,內部兩個 key(`POSTGRES_PASSWORD` / `REDIS_PASSWORD`)。同一 service 範疇的兩把密碼合理一起輪換、IAM 邊界一致,成本省一半。

不選 SSM 是因為:Secrets Manager 提供自動輪換 hook(未來想接 RDS 管理密碼)、跨 region 複製、版本管理;SSM Parameter Store 設計上偏向「設定」而非「密碼」,雖然 SecureString 也能存,但缺輪換機制。

### 7. ECS log group:預先建立 vs IAM 授權 ECS 自建

ECS task 啟動時,若 task def 指定的 CloudWatch log group 不存在,行為由 `awslogs-create-group` option 控制:

| 方案 | task def | execution role 權限 | 多 service 維運 |
|---|---|---|---|
| **A. 預先建好 log group** | 不設 `awslogs-create-group` | `AmazonECSTaskExecutionRolePolicy` 即足(只給 CreateLogStream / PutLogEvents) | 每加一個 service 都要記得手動 / IaC 建 group |
| **B. 給 role 加 CreateLogGroup** (採用) | `awslogs-create-group: "true"` | 額外 inline policy 允許 `logs:CreateLogGroup` on `arn:...log-group:/ecs/*` | 新 service 自動 provision,零維運 |

→ **採方案 B**。本作業未來 backend / frontend 都會加新 service,讓 ECS 自動 provision 對應 log group 比每次手動省事;以 inline policy 把 Resource 限定到 `/ecs/*` 字首,範圍可控。

### 8. CPU architecture:Fargate ARM64(Graviton)vs X86_64

EC2 (PG/Redis) 已選 ARM64 享 Graviton 約 20% 價格優勢,直覺上 ECS 也想用 ARM64。但 GitHub-hosted runner `ubuntu-latest` 是 x86_64,`docker build` 預設輸出 x86_64 image;Fargate ARM64 拿 x86 binary 會立刻 `exec format error` exit 255。

| 方案 | 優點 | 缺點 |
|---|---|---|
| **A. task def 改回 X86_64**(本階段採用) | 立即可用、image 無需 multi-arch | 失去 Graviton 20% 折扣 |
| B. GHA 加 buildx + QEMU 出 ARM64 image | 與 ARM EC2 一致、省 20% | build 時間從 ~1 分鐘變 ~3 分鐘(emulation) |

→ **暫採方案 A**。Pilot 階段優先驗證 pipeline,arch 統一以 GHA 預設 x86 為基準。記入「未來改進」:當 backend / frontend 上線、build time 累積影響 CI 體感、或 Fargate 帳單可觀時,改 multi-arch build。CPU 架構對 task 與 EC2 之間的 TCP 連線沒有影響,跨架構通訊不是問題。

### 9. 敏感識別處理:placeholder + GHA substitute

task definition 必須引用 AWS account ID(出現在 IAM role ARN、Secrets Manager ARN);此外 task 啟動需要 EC2 私有 IP 才能連到 self-host 的 PG/Redis。兩個值不算機密但仍敏感:

- Account ID:可被用於 cross-account 偵察與 confused deputy 攻擊
- EC2 私有 IP:VPC 外不可達,但會洩漏網路拓樸

→ **task-definition.json 留 `REPLACE_ACCOUNT_ID` / `REPLACE_EC2_PRIVATE_IP` placeholder**,workflow 在 deploy 前用 `sed` 從 GitHub Secret(`AWS_ACCOUNT_ID`)與 Variable(`EC2_PRIVATE_IP`)注入真實值,確保 repo 公開時不洩漏。`REPLACE_ON_DEPLOY` placeholder 則由 `aws-actions/amazon-ecs-render-task-definition` 自動替換為當次 build 出的 image URL。

## 決策

採以下組合作為**本專案標準 CI/CD pipeline**,後續 backend / frontend repo 複用同模式:

1. ECS launch type:**Fargate**
2. AWS 認證:**GitHub OIDC + per-repo IAM role**
3. ECS cluster:**單一 `jko-cluster`** 收容三個 service
4. Image tag:`${{ github.sha }}` + ECR IMMUTABLE + GHA build 預檢 idempotent
5. Secrets:**Secrets Manager 單一 JSON secret**,多 key 引用
6. CloudWatch log group:**ECS 自動建**,role 賦予 `/ecs/*` 範圍的 CreateLogGroup
7. CPU arch:**X86_64**(短期),未來改 multi-arch
8. Task def 機密欄位:**repo 留 placeholder + GHA 用 sed 注入**

整條 pipeline 概覽:

```
GitHub push (main)
    │
    ▼
┌──────────────────────────────────┐
│ CI: test + docker build-check    │  (PR 也跑)
└──────────────┬───────────────────┘
               │ needs:passed
               ▼
┌──────────────────────────────────┐
│ Deploy job                       │
│  1. Configure AWS via OIDC       │
│  2. Login ECR                    │
│  3. Build image (idempotent)     │
│  4. Substitute placeholders      │
│     (sed: account ID, EC2 IP)    │
│  5. Render task def with image   │
│  6. Register new revision        │
│  7. Update service               │
│  8. wait-for-service-stability   │
└──────────────┬───────────────────┘
               │
               ▼
        ECS Fargate task
               │
               │ private VPC routing
               ▼
        EC2 self-host Docker
        ├── PostgreSQL
        └── Redis
```

## 理由

1. **Pilot 驗證設計可行性**:用 50 行的 Flask 跑通整套,代價遠低於拿 backend 當白老鼠;一旦 backend / frontend 加入時所有踩過的雷(arch、log group、PassRole、tag immutable)都已解決
2. **預設選現代化、AWS 官方推薦的安全模式**:OIDC、IMMUTABLE tag、Fargate、Secrets Manager 都是 2024+ AWS 文件第一順位推薦
3. **每個非預設選擇都有明確權衡記錄**:per-repo role 取代共用、單 cluster 取代多 cluster、X86_64 暫代 ARM64,各自留下未來改善的觸發條件
4. **repo 對外公開無顧慮**:Account ID / EC2 IP / 密碼都不入版控,workflow 改寫流程可被面試官 / 同事審視

## 不採用的權衡

捨棄項目:

- **GitOps 模式(Argo CD / Flux)**:更聲明式、可審計,但需另起一個 controller cluster,對單人小專案重型過頭
- **CodePipeline + CodeBuild + CodeDeploy**:AWS 原生但 vendor lock-in 重,GHA 通用性更高、本地 / fork 也能跑
- **Blue/Green via CodeDeploy**:rolling update 已可滿足 0 downtime,CodeDeploy 多一層學習曲線、需另外建 ALB 與 listener rule,留待真正有 prod 流量時再加
- **環境分離(staging / prod)**:GitHub Free 個人 private repo 不支援 environment-level secret,加上目前單一目標,延後到正式上線階段再導入

## 未來改進(觸發條件)

| 改進項 | 何時做 |
|---|---|
| Multi-arch build(ARM64) | backend / frontend 上線後,Fargate 帳單佔比 > 30% |
| Per-repo permission policy 收緊 | 加入第二位協作者時 |
| Staging environment + GitHub Environment secret | 需要 PR preview 部署時 |
| Route 53 Private Hosted Zone 解耦 EC2 IP | EC2 重啟換 IP 影響超過一次 |
| Blue/Green via CodeDeploy | 第一次因 deploy 造成可感知 downtime |
| Container image vulnerability scan(Trivy / ECR scanning) | backend 處理使用者資料前 |

## 連結

- [ADR 002 — backend framework](002-backend-framework.md)(Fastify 部署模式)
- [ADR 006 — BFF Redis session](006-bff-redis-session-store.md)(Redis 連線配置)
- [`infra/healthcheck/`](../../infra/healthcheck/) — Pilot Flask 服務
- [`.github/workflows/deploy-healthcheck.yml`](../../.github/workflows/deploy-healthcheck.yml) — workflow 實作
