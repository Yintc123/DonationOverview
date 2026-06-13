# 精選 Prompt:ECS + GHA CI/CD pipeline 從零跑通

日期:2026-06-13
對應 ADR:[008 — ECS CI/CD pipeline](../decisions/008-ecs-cicd-pipeline.md)
對應技術清單:[AWS 服務清單](../tech/aws-services.md)
原始 session:[`raw/2026-06-13-session-b0b99eac.readable.md`](raw/2026-06-13-session-b0b99eac.readable.md)

## 情境

ADR 002 / 005 / 006 / 007 已決定 backend(Fastify + Prisma)、frontend BFF(Next.js + iron-session + Redis)、ORM(Prisma)等技術選型,但**部署層完全還沒摸**:沒建過 ECS、沒用過 GHA 跑 AWS 部署、沒接過 OIDC、沒摸過 ECR。

直接拿 backend / frontend 當白老鼠風險高:應用程式本身的 bug 跟 infra bug 會混在一起,debug 很痛。需要先用一個**最小可丟棄的服務**把整條 CI/CD 走通,讓 backend / frontend 之後可以直接複用模式,而不必各自踩雷。

要求:
1. 無長期 AWS access key 留在 GitHub Secrets
2. ECS task 能讀 Secrets Manager 取得 PG / Redis 密碼
3. task definition 模板放 repo,但 account ID / EC2 私有 IP 不入版控
4. 部署失敗可 idempotent 重跑,不被 image tag 唯一性卡死
5. backend / frontend 加入時可平移最少改動

## 我的 Prompt

> AWS 的 ecs 可以連到 ec2 的服務嗎? 我想在 ec2 docker 啟動 db 和 redis,但是 server 跑在 ecs 上

(中間若干輪 EC2 / Docker / GHA 設定問答省略,見 raw)

> 那先將這個專案建立 github action 我要用 flask server 測試整套流程
>
> 能不能用 github action 觸發 ecs 部署?
>
> 也先把 github action 的 CI 部分也加上
>
> 可不可以 frontend 配 ALB,backend 走 service to service?

收尾 prompt:

> 將目前有使用的 AWS 所有服務記錄到 tech 的資料夾內

## AI 產出摘要

**Pilot 服務:Flask + pytest**

50 行的 `infra/healthcheck/` 提供 3 個 endpoint:
- `GET /health` — 自身 liveness
- `GET /health/postgres` — 連 EC2 上的 PG 跑 `SELECT version()`
- `GET /health/redis` — 對 Redis PING

整個 app + 5 個單元測試(mock 在 `psycopg.connect` / `redis.Redis` boundary)用 TDD 跑紅綠重構,15 分鐘從零完成。

**完整 GHA workflow**

`.github/workflows/deploy-healthcheck.yml` 三個 job:
1. `test`:pytest
2. `build-check`:docker build 不 push
3. `deploy`:OIDC → ECR → ECS Fargate rolling update

`needs: [test, build-check]` 控制 PR 只跑 CI、main 才 deploy。`paths:` 篩選讓不相關改動不浪費 quota。

**Task definition 模板 + sed 注入**

`infra/healthcheck/.aws/task-definition.json` 用三個 placeholder:
- `REPLACE_ACCOUNT_ID`
- `REPLACE_EC2_PRIVATE_IP`
- `REPLACE_ON_DEPLOY`(image URL)

workflow 用 `sed` 從 `secrets.AWS_ACCOUNT_ID` / `vars.EC2_PRIVATE_IP` 注入,確保 repo 公開時不洩漏 account ID 或網路拓樸。image URL 由 `aws-actions/amazon-ecs-render-task-definition` 自動替換。

**Idempotent build step**

ECR tag immutability 與 GHA「Re-run failed jobs」會打架(同 SHA 重 push 失敗)。build step 加 `aws ecr describe-images` 預檢,已存在則 skip build/push 直接進下一步:

```bash
if aws ecr describe-images --repository-name "$ECR_REPOSITORY" \
     --image-ids "imageTag=$IMAGE_TAG" --region "$AWS_REGION" >/dev/null 2>&1; then
  echo "Image already in ECR, skipping"
else
  docker build -t "$IMAGE" . && docker push "$IMAGE"
fi
```

**踩過 12 個雷 + 一一修法**

雷的清單記在 ADR 008 與 [aws-services.md](../tech/aws-services.md):service-linked role 沒自動建、role 命名 `ecsTaskExecutionRole` vs `jko_ecs` 不一致、`iam:PassRole` 沒給、`logs:CreateLogGroup` 不在 default policy、IMMUTABLE tag 衝突、CPU arch x86 vs ARM、wizard 加 random suffix、Service Connect namespace UX、rolling deploy 137 是正常的、SG-to-SG 規則 inbound 方向、PG user 名稱跨層對齊、Fargate task IP 每次重啟會變。

**收尾交付**

1. ADR 008(完整 9 個決策 + 未來改進觸發條件)
2. README 更新(架構圖 + ADR 連結)
3. `docs/tech/aws-services.md` (7 大類資源清單 + 月費估算)
4. CLAUDE.md / README 索引補上 `docs/tech/`

## 我的判斷與後續調整

**判斷一:用最小可丟棄服務當 pilot,不直接拿 backend / frontend 試**

Flask 比 Fastify 啟動更快、依賴更少、最簡單。把它跑通的代價低,但**踩過的每個雷都會對 backend / frontend 直接受益**——role 命名、log group 策略、CPU arch、sed 注入這些「跨應用的 infra 議題」不會跟 application code 的 bug 混在一起,可以乾淨地 debug。

**判斷二:踩雷時讓 AI 先解釋「為什麼這樣設計」,再決定修法**

例如 `logs:CreateLogGroup` 為什麼不在 `AmazonECSTaskExecutionRolePolicy` 預設裡——AWS 認為 log group 是「共享 infra」應預先建好,不是每個 task 自己亂建。理解設計意圖後,選方案 B(role 加 CreateLogGroup, 範圍限定 `/ecs/*`)是承認「我們不想為每個新 service 都記得 pre-create」這個 trade-off,而不是無腦給寬權限。ADR 老實寫:「以稍寬 IAM 換維運自動化,且 Resource 限縮到 `/ecs/*` 字首」。

**判斷三:per-repo IAM role 而非共用**

AI 一開始推薦「一個 role 給三個 repo 共用」,理由是 IAM 免費 + 維護一處。我反問「會不會 push frontend 卻部署 backend」,釐清「workflow 檔案決定觸發 / role 只是通行證」後,**確定共用不會 cross-trigger,但仍選 per-repo**——理由是「audit log 看 role ARN 直接知道誰部署的」、「未來引入協作者好分權」。AI 在我下決定後立刻調整指南。**這種主動測試「AI 推薦的方案有哪些隱形假設」的對話,比直接接受答案更有價值**。

**判斷四:backend 走 Service Connect、不另外掛 ALB**

當 AI 提到「task 每次重啟會換 public IP」時,我反問「frontend 配 ALB,backend 走 service to service 可不可以」。AI 立刻認可這是 production-grade pattern,理由是「frontend 的 BFF 已是 API gateway,backend 沒理由再對外」+「ALB 月費省一半」+「backend attack surface 完全消除」。**這個拓樸決策在 pilot 階段就先定下來,backend repo 開工時不會再花時間設計**——預計獨立寫一份 ADR 009。

**判斷五:平時不寫紀錄、決策節點才主動寫**

整個 session 跨 10 小時、9000+ 行 raw,但精選版只記:
- 5 個重要 prompt(其餘是逐步指導,raw 已留)
- 9 個決策(全寫進 ADR 008,精選版只摘要)
- 5 個我自己的判斷邏輯(AI 不會主動寫這部分)

**raw 是給審閱者「想驗證時去翻」的證據**,精選版才是給人讀的故事。兩個職責不重疊。

## 後續工作

- backend repo 開工時:複用本 workflow 結構,只改 `ECR_REPOSITORY` / `ECS_SERVICE` 等變數
- backend / frontend 都上線後:ADR 009 記錄 BFF + Internal API 拓樸(ALB only on frontend, Service Connect for backend)
- 進入正式環境前:multi-arch build(改 buildx + QEMU)、ALB + ACM 證書、Route 53 Private Hosted Zone 解耦 EC2 IP、EBS Snapshot Lifecycle、ECR Lifecycle Policy
- 後續 service 都用 per-repo IAM role,IAM permission policy 繼續共用同份 inline template,直到引入第二位協作者再切分
