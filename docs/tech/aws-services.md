# AWS 服務清單

紀錄本專案目前使用中的所有 AWS 服務、對應資源名稱、用途與相關連結。

**Region**: `ap-southeast-2`（雪梨）
**Account ID**: 見 GitHub Secret `AWS_ACCOUNT_ID`（不入版控）

---

## 運算 / 容器

### EC2

| 項目 | 值 |
|---|---|
| 實例類型 | t4g 系列（Graviton ARM64） |
| 作業系統 | Ubuntu Server |
| 用途 | self-host Docker daemon,跑 PG + Redis |
| 相關設定 | `infra/docker-compose.yml` |
| Inbound SG | 22(SSH from Mac IP)、5432 / 6379(from ECS task SG) |
| 連線方式 | SSH 用 `~/.ssh/JKO_vm.pem`,user `ubuntu` |

### ECS（Elastic Container Service）

| 項目 | 值 |
|---|---|
| Cluster | `jko-cluster`（CFN stack 前綴 `warmhearted-crocodile-18gqvo-`） |
| Launch type | Fargate |
| CPU 架構 | X86_64（暫定,見 [ADR 008](../decisions/008-ecs-cicd-pipeline.md)） |
| Service | `jko-healthcheck-service-hq27okrx`（pilot) |
| Task definition family | `jko-healthcheck` |
| 未來會加 | `jko-backend`、`jko-frontend` |

### ECR（Elastic Container Registry）

| 項目 | 值 |
|---|---|
| Repository | `jko_healthcheck` |
| Image tag 策略 | `${GITHUB_SHA}` + `IMMUTABLE` |
| 漏洞掃描 | scanOnPush=true |
| Lifecycle | 待設(建議保留最近 10 個) |

---

## 網路

### VPC / Subnet

| 項目 | 用途 |
|---|---|
| 預設 VPC | 同時收容 EC2 與 ECS task |
| Public subnet | ECS task 取得 public IP 用 |
| Private subnet | 未來 backend service 進入用(規劃中) |

### Security Group

| SG | Inbound 規則 | 套用對象 |
|---|---|---|
| EC2 SG | 22 from Mac IP、5432 from ECS SG、6379 from ECS SG | EC2 instance |
| ECS task SG | 8080 from `0.0.0.0/0`（測試暫開,正式上線改 ALB SG） | ECS task ENI |
| ALB SG（規劃中） | 80 / 443 from `0.0.0.0/0` | ALB |

---

## 身分與權限

### IAM Identity Provider

| 項目 | 值 |
|---|---|
| Provider URL | `token.actions.githubusercontent.com` |
| Audience | `sts.amazonaws.com` |
| 用途 | GitHub Actions OIDC 認證,免長期 access key |

### IAM Roles

| Role | 用途 | Trust principal | 附加 policy |
|---|---|---|---|
| `jko_ecs` | ECS task execution role | `ecs-tasks.amazonaws.com` | `AmazonECSTaskExecutionRolePolicy`、`SecretsManagerReadWrite`、`EcsCreateLogGroup`（inline） |
| `github-actions-deploy-jkoOverview` | GitHub Actions 部署本 repo | OIDC（限 `Yintc123/DonationOverview:main`） | `JkoOverviewDeployPolicy`（inline,涵蓋 PushECR / DeployECS / PassRole） |
| `AWSServiceRoleForECS` | ECS 服務本身的 service-linked role | `ecs.amazonaws.com` | AWS 自動維護 |
| `github-actions-jko-frontend-deploy`（待建） | 部署 frontend repo | 同上,限 frontend repo | 同 `JkoOverviewDeployPolicy` |
| `github-actions-jko-backend-deploy`（待建） | 部署 backend repo | 同上,限 backend repo | 同 `JkoOverviewDeployPolicy` |

### IAM Policies（與權限說明）

- **`JkoOverviewDeployPolicy`**（inline on deploy role）：
  - `ecr:*`（推 image）
  - `ecs:DescribeServices`、`RegisterTaskDefinition`、`UpdateService` 等
  - `iam:PassRole` 限定 `arn:aws:iam::<account>:role/jko_ecs`

- **`EcsCreateLogGroup`**（inline on `jko_ecs`）：
  - `logs:CreateLogGroup` 限定 `arn:aws:logs:*:*:log-group:/ecs/*`

詳細決策見 [ADR 008](../decisions/008-ecs-cicd-pipeline.md)。

---

## 機密 / 設定

### Secrets Manager

| Secret 名稱 | 內容 | 引用方 |
|---|---|---|
| `jko_vm_pg_redis_1` | JSON: `{"POSTGRES_PASSWORD": "...", "REDIS_PASSWORD": "..."}` | ECS task definition 的 `secrets[].valueFrom` |

引用語法：`arn:aws:secretsmanager:ap-southeast-2:<account>:secret:jko_vm_pg_redis_1:POSTGRES_PASSWORD::`（最後雙冒號代表 latest version）。

---

## 監控 / 日誌

### CloudWatch Logs

| Log group | 內容 |
|---|---|
| `/ecs/jko-healthcheck` | Flask container stdout/stderr |
| `/ecs/jko-backend`（規劃中） | backend container 輸出 |
| `/ecs/jko-frontend`（規劃中） | frontend container 輸出 |

由 ECS 在 task 首次啟動時自動建立（`awslogs-create-group: true`,搭配 `jko_ecs` 的 `EcsCreateLogGroup` 權限）。

Retention policy 尚未設定（**待辦**：每個 group 設 7 天 retention,避免堆積）。

### CloudShell

無固定資源,但**長期使用中**：
- 跑 IAM service-linked role 建立
- 本機未裝 AWS CLI 時的代替方案

---

## CI/CD 相關（非 AWS 但相關）

- **GitHub Actions** workflow：`.github/workflows/deploy-healthcheck.yml`
- **GitHub repo secrets / variables**：
  - Secret `AWS_DEPLOY_ROLE_ARN`（OIDC assume target）
  - Secret `AWS_ACCOUNT_ID`（sed 注入用）
  - Variable `EC2_PRIVATE_IP`（sed 注入用）

---

## 規劃中（尚未建立）

| 服務 / 資源 | 用途 | 觸發條件 |
|---|---|---|
| Application Load Balancer | frontend service 對外入口 | frontend repo 上線 |
| ACM 證書 | ALB HTTPS | 取得自訂域名後 |
| Route 53 hosted zone | 自訂域名 + Private Hosted Zone(取代 EC2 IP) | frontend 上線 / EC2 IP 變動超過 1 次 |
| AWS Cloud Map namespace | Service Connect `jko.local` | backend / frontend 都上線 |
| EBS Snapshot lifecycle policy | EC2 上 PG / Redis volume 自動備份 | 進入正式環境前 |
| ECR Lifecycle policy | 自動清舊 image,避免月費漲 | 任何時候,做了無痛 |

---

## 月費預估（粗估）

| 服務 | 月費（USD） | 備註 |
|---|---|---|
| EC2 t4g.small | ~$12 | 24×7 running |
| EC2 EBS root（30 GB） | ~$3 | gp3 |
| ECS Fargate（3 task × 256 CPU / 512 RAM） | ~$15 | 24×7,3 個 service |
| ECR storage（~5 GB） | ~$0.50 | 含 lifecycle policy |
| Secrets Manager（1 secret） | $0.40 | 整合 JSON |
| CloudWatch Logs(< 1 GB) | < $1 | 7 天 retention |
| ALB(待建) | ~$18 | 含 LCU |
| **小計**(現狀) | **~$32** | 不含 ALB |
| **小計**(全上) | **~$50** | 含 ALB |

> 數字僅供面試作業期間參考,各 service scaling 後會變動。Free tier 不適用(account 已超過 12 個月 / 額度)。

---

## 相關文件

- [ADR 008 — ECS CI/CD pipeline](../decisions/008-ecs-cicd-pipeline.md)
- [`infra/docker-compose.yml`](../../infra/docker-compose.yml)
- [`infra/healthcheck/`](../../infra/healthcheck/) — pilot 服務
- [`.github/workflows/deploy-healthcheck.yml`](../../.github/workflows/deploy-healthcheck.yml)
- 根目錄 [README](../../README.md) — 整體架構圖
