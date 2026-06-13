# 決策:專案資安模型 — 分層防禦(defense in depth)

日期:2026-06-14

## 背景

本專案橫跨多個信任邊界:GitHub repo(公開)、AWS account(私有)、EC2(self-host PG/Redis)、ECS Fargate task(無狀態)、使用者瀏覽器(完全不可信任)。每一層都可能被攻擊或洩漏,單點防禦不夠——任何一層被突破,後續層仍需獨立守住。

ADR 004 / 005 / 006 / 008 各別觸碰過認證、session、CI/CD 等局部安全議題,但**整體資安模型**沒有單一文件描述,新加入的人(或下個 session 的 AI)無法快速理解「為什麼這個決策不能改、那個目前 ok」。

本 ADR 把已落實的資安決策集中起來、明確分層、留下驗證手段與未來改進的觸發條件。**這不是一份新做的「決策」,而是把散落在各 ADR 與實作中的隱性原則明文化**。

## 信任邊界與分層

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 0  公開 Internet(完全不可信任)                          │
│  - 瀏覽器、爬蟲、攻擊者掃描                                    │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTPS only(規劃中)
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ Layer 1  ALB(規劃中) + Frontend ECS service                  │
│  - 唯一對外入口、TLS 終結、WAF 可加掛                          │
│  - BFF 做 session、CSRF、auth(ADR 005/006)                   │
└──────────────────────────┬──────────────────────────────────┘
                           │ Service Connect(私網 only)
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ Layer 2  Backend ECS service(無 public IP)                  │
│  - 純 API,無 session 邏輯,信任 BFF 經手的 request            │
│  - 完全在 VPC 私網,不可從 Internet 直連                       │
└──────────────────────────┬──────────────────────────────────┘
                           │ SG-to-SG 規則, port 5432/6379
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ Layer 3  資料層(EC2 self-host PG + Redis)                    │
│  - SG 只允許 ECS task 的 SG inbound                          │
│  - 密碼透過 Secrets Manager 注入                              │
│  - .env 在 EC2 磁碟,gitignored                               │
└─────────────────────────────────────────────────────────────┘

垂直管道(獨立於應用 layer):
┌─────────────────────────────────────────────────────────────┐
│  GitHub Actions(部署管道)                                    │
│   ├─ OIDC,無長期 AWS key                                     │
│   ├─ Per-repo IAM role,trust 鎖到 repo + main branch         │
│   └─ Permission policy 限定 ECR + ECS + 特定 PassRole         │
└─────────────────────────────────────────────────────────────┘
```

## 已實施的決策

### 1. Secret 注入:runtime,而非 build time

**決策**:image 永遠保持「無 secret 的 generic artifact」,所有密碼在 container 啟動時才注入。

**EC2 PG/Redis container**:
```yaml
# infra/docker-compose.yml
environment:
  POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}   # ← runtime 展開,讀 .env
```
- `.env` 本機磁碟、不入 git
- Image 是 Docker Hub 公開的 `postgres:16-alpine` / `redis:7-alpine`,無客製化
- `docker history` / image scan 都看不到密碼

**ECS healthcheck container**:
```dockerfile
# infra/healthcheck/Dockerfile — 完全沒有 secret 相關指令
FROM python:3.12-slim
COPY requirements.txt .
RUN pip install ...
COPY app.py .
CMD ["python", "app.py"]
```
密碼透過 task definition 的 `secrets[].valueFrom` 從 Secrets Manager 注入:
```json
{
  "name": "POSTGRES_PASSWORD",
  "valueFrom": "arn:aws:secretsmanager:...:secret:jko_vm_pg_redis_1:POSTGRES_PASSWORD::"
}
```
- ECS agent 用 `jko_ecs` execution role 取值
- 注入瞬間不留 log(CloudTrail 只記 `GetSecretValue` 被呼叫,不記值)
- 應用程式 `os.environ` 讀到後只在 process 記憶體存活

**驗證方式**:
```bash
docker history <image> --no-trunc | grep -i password   # 應該空
docker inspect <container> --format='{{.Config.Env}}'  # 密碼存在但僅限 runtime
aws ecs describe-task-definition ... --query '...secrets'  # 顯示 valueFrom ARN,非真值
```

**反例(不要做)**:
- `COPY .env .` 把密碼塞進 image
- `ENV POSTGRES_PASSWORD=xxx` 寫死,永久保留於 image 層
- `ARG DB_PASS` + `RUN echo $DB_PASS > config` 同樣會被 `docker history` 挖出

### 2. CI/CD 認證:OIDC + per-repo IAM role

詳見 [ADR 008](008-ecs-cicd-pipeline.md) §2 / §3。重點:

- **無長期 access key** 留在 GitHub Secrets,所有 AWS API 呼叫透過 OIDC 換取 < 1 小時臨時 credentials
- Trust policy 限定 `repo:Yintc123/<repo>:ref:refs/heads/main`,只有特定 repo 的 main branch 能 assume
- Permission policy 限縮:`ecr:*` + `ecs:Describe/Register/Update` + `iam:PassRole` 限定到 `jko_ecs`
- Per-repo role(`-infra-deploy` / `-frontend-deploy` / `-backend-deploy`),frontend repo 編譯不能影響 backend ECS service

### 3. IAM 最小權限

- `jko_ecs`(ECS execution role):
  - `AmazonECSTaskExecutionRolePolicy`(AWS 官方,涵蓋 ECR pull + log write stream)
  - `SecretsManagerReadWrite`(暫採寬鬆版,**未來改進**:換成 inline policy 只給 `GetSecretValue` 對 `jko_vm_pg_redis_1`)
  - `EcsCreateLogGroup`(inline):`logs:CreateLogGroup` 限定 `arn:aws:logs:*:*:log-group:/ecs/*` 字首

- `github-actions-deploy-jkoOverview`(deploy role):
  - `JkoOverviewDeployPolicy`(inline):明列三段 statement,`PassExecutionRole` 限定 `jko_ecs` ARN

- 從未使用過 `AdministratorAccess` 或 `*` 的萬用 policy

### 4. 網路分段:SG-to-SG 規則

**決策**:任何敏感 port 都不對 `0.0.0.0/0` 開放,inbound 來源指定為「特定 SG」,當對方 SG 的 instance 變動時自動適用。

| 邊界 | Inbound 規則 | 不採 0.0.0.0/0 的理由 |
|---|---|---|
| EC2 SG ← ECS task SG | TCP 5432 / 6379 | PG / Redis 對全網開等同把資料庫送上 Shodan |
| EC2 SG ← Mac IP | TCP 22 | SSH 對全網開會被 brute force,改 IP 白名單即可 |
| ECS task SG ← `0.0.0.0/0` | TCP 8080 (暫時) | **規劃改 ALB**:之後僅 ALB SG inbound,task 不再對外 |
| (未來)Backend ECS SG ← Frontend ECS SG | TCP 8080 | Service Connect 走私網,backend 完全不對外 |

### 5. 未來:Frontend ALB + Backend Service Connect

**決策**(規劃中,實作於 ADR 009 後續):
- **Frontend**:掛 ALB,終結 HTTPS,backend 不需要再有 ALB
- **Backend**:`assignPublicIp: DISABLED`、放 private subnet、Service Connect Client-Server mode
- 攻擊者完全無法從 Internet 直接打 backend,所有對 backend 的呼叫都必須經 frontend 的 BFF

詳見 [ADR 008](008-ecs-cicd-pipeline.md) 提到的 BFF + Internal API 拓樸概念,專屬 ADR 待寫(暫定 010)。

### 6. Container image 完整性

- ECR 設 `IMMUTABLE` tag policy:同 SHA 的 image 不可被覆蓋
- ECR `scanOnPush=true`:每次 push 自動掃 CVE
- Image tag = `${{ github.sha }}`:tag 即為 commit,可審計、可回滾

**未來改進**:加 Trivy 在 build-check job 跑 image vulnerability scan、考慮 cosign 簽章。

### 7. Repo 資訊保護

- `.env`、`.mcp.json`、`.ssh/*.pem` 全部 gitignored
- `.gitignore` 第 1-5 行專段:`.env`、`.env.*`(白名單 `.env.example`)、`.mcp.json`
- Task definition 中 account ID / EC2 IP 用 placeholder + GHA `sed` 注入,**repo 公開時不洩漏**
- CLAUDE.md 明文「絕不把任何 token 寫進可能被 commit 的檔案」+ 「發現使用者貼出 token 立即提醒並建議 revoke」

### 8. Session / Auth(已委派至 ADR 005 / 006)

- iron-session 只 seal `sessionId`(不含 token),減少 cookie 體積與洩漏面
- Session 實體存 Redis(BFF 內部),token 永不出 backend
- CSRF 雙重 cookie + header 比對(Spec 001f)
- backend 信任 frontend 的 BFF,自己不做 session,**單一信任源點**

## 風險矩陣(對應已有控制與待處理)

| 風險情境 | 已有控制 | 待加強 |
|---|---|---|
| GitHub repo 公開,account ID 外洩 | placeholder + sed 注入 | (無——已充分) |
| Image 被偷或公開掃描 | 無 secret 嵌入、ECR scanOnPush | Trivy / Sbom |
| ECR tag 被覆蓋成惡意 image | IMMUTABLE policy | 加 cosign 簽章 |
| ECS task 環境變數被 dump | task 環境變數只在 process 記憶體 | (無——AWS 內部保護) |
| Secrets Manager 被未授權 read | `jko_ecs` 用 IAM 限定,`SecretsManagerReadWrite` 範圍仍寬 | **改 inline policy 只給 `GetSecretValue` on `jko_vm_*`** |
| EC2 SSH 被爆破 | inbound 限 Mac IP/32 | 改 SSM Session Manager 完全關 22 |
| PG / Redis 對公網暴露 | SG-to-SG 規則 | (無——已嚴密) |
| ECS task 被 RCE 後可橫向移動 | task role 無 SDK 權限(我們未綁 task role,只綁 execution role) | 若未來綁 task role,需嚴格限縮 |
| Image pull 過程中被竄改 | 走 ECR(同 region 私網) | ECR registry endpoint 走 VPC endpoint |
| Long-lived AWS key 被偷 | **沒有 long-lived key**(OIDC) | (無——根本沒這風險) |
| CloudTrail / log 被刪 | CloudTrail 預設 90 天保留 | 加 S3 sink 跨帳號保存 |
| GitHub repo 被未授權 push | branch protection(待設) + per-repo deploy role | 設 main branch protection + required reviews |

## 不採用的權衡

- **WAF(Web Application Firewall)**:對單一作業範圍過重,規則維護成本高,等真有公網流量再加
- **GuardDuty**:雲端入侵偵測,有月費,**ADR 008 月費估算未含**,production 階段才開
- **VPC endpoint for ECR / Secrets Manager**:可避免出口流量,但設定複雜,目前 ECS task 仍走 VPC 內部走 AWS backbone,流量已不出 region
- **Mutual TLS(mTLS) 在 Service Connect**:Service Connect 預設只開明文,加 mTLS 需自己管證書,在內部 VPC 受 SG 保護下 trade-off 不合算
- **Image signing(cosign)**:目前 IMMUTABLE + scanOnPush 已能阻擋多數場景,signing 加在 CD 簽 + ECS 驗的整套流程屬於 production-grade

## 未來改進(觸發條件)

| 改進項 | 觸發條件 |
|---|---|
| Inline policy 取代 `SecretsManagerReadWrite` | 任何時候,5 分鐘改完 |
| Frontend ALB + Backend Service Connect 拓樸 | backend repo 開工 |
| Branch protection + required reviews | 第二位協作者加入 |
| ECR Trivy vulnerability scan in CI | backend 處理使用者資料前 |
| AWS WAF on ALB | 對外流量出現實際惡意 pattern 時 |
| GuardDuty | 進入正式環境 |
| VPC endpoint for ECR | 出口流量帳單 > $5/月 |
| SSM Session Manager 取代 SSH | 第二位需 SSH 進 EC2 時,順便完全關 22 |
| CloudTrail S3 sink 跨帳號保存 | 正式環境合規要求 |
| `docker scout` / SBOM | image vulnerability 抽樣發現高分項時 |
| ECR registry pull rate-limit | (無——ECR 本身有 quota,不太可能撞到) |

## 連結

- [ADR 004 — auth token strategy](004-auth-token-strategy.md)(token 流向)
- [ADR 005 — BFF session(iron-session)](005-bff-session-iron-session.md)(cookie 只藏 sessionId)
- [ADR 006 — BFF Redis session store](006-bff-redis-session-store.md)(token 永不出 backend)
- [ADR 008 — ECS CI/CD pipeline](008-ecs-cicd-pipeline.md)(OIDC、IAM 最小權限、IMMUTABLE tag、Secrets Manager 注入路徑)
- [docs/tech/aws-services.md](../tech/aws-services.md)(資源清單)
- [`infra/healthcheck/Dockerfile`](../../infra/healthcheck/Dockerfile)(image 無 secret 驗證)
- [`infra/healthcheck/.aws/task-definition.json`](../../infra/healthcheck/.aws/task-definition.json)(secrets[].valueFrom 用法)
