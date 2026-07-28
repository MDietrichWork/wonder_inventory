# Go-Live Runbook — Wonder DQ Console (AWS)

**Parallel to [`GO-LIVE.md`](GO-LIVE.md) (GCP).** Same app, same three launch constraints — hosted on AWS
instead of GCP. Read this alongside the GCP runbook: the app, the Jira setup (§2), the cutover/backfill,
and the deferred-hardening list are **identical**. The only material difference is **where the container
runs** and **how it reaches BigQuery across clouds** (§3). Section numbers line up with the GCP doc.

> **Read this first — the honest trade-off.** The source of truth is **BigQuery**, which is Google Cloud,
> and it is staying there. Hosting the app on AWS therefore introduces one seam the GCP deployment does
> **not** have: the app must authenticate *across clouds* to read BigQuery. We solve this with **Workload
> Identity Federation (WIF)** — an AWS IAM role that Google trusts, so **no long-lived Google key file is
> ever stored in AWS** (see §3). This is the correct pattern, but it is more setup than the GCP path,
> where the runtime identity gets native BigQuery grants. Choose AWS because the client *operates* on AWS,
> not because it is less work — it isn't. Everything else (Postgres, container, scheduler, Jira) is a
> one-to-one swap of equivalent managed services.

Scoped to the **three constraints for this launch**:

1. **Hosted on AWS** — single container (FastAPI API + built React app) on **App Runner**, app data in
   **RDS for PostgreSQL**, source data read-only from **BigQuery** (cross-cloud via WIF).
2. **Linked to the client's real Jira** — not the sandbox `dietrichcoding.atlassian.net`.
3. **No SSO / no permissions** — the service is **publicly reachable** (App Runner default public
   endpoint). SSO (Entra / Cognito / an ALB OIDC front) is **explicitly deferred** (see [§10](#10-explicitly-deferred-post-go-live-hardening)).

> How the app runs today: one image built from `app/Dockerfile` (Vite build → served by FastAPI). The
> container's start command is `alembic upgrade head && uvicorn wonder.main:app` — the Postgres schema
> is created/migrated automatically on first boot. Behavior is controlled entirely by env vars
> (`app/backend/wonder/config.py`); the two switches that make it "live" are `DATA_SOURCE=bigquery`
> and `TICKET_SINK=jira`. **None of this changes on AWS** — it's the same image and the same env vars.

> **Terraform status (differs from GCP).** The GCP runbook ships a *validated* Terraform scaffold in
> `infra/terraform/`. The AWS equivalent is **not yet written** — this document is the design + task list
> for it. Porting is straightforward (all AWS-managed services with mature Terraform providers); §8 lists
> exactly what the `infra/terraform-aws/` module needs to contain.

---

## Service mapping at a glance (GCP → AWS)

| Concern | GCP (shipped) | AWS (this doc) |
|---|---|---|
| Container runtime | Cloud Run | **App Runner** (managed, HTTPS URL, scale-to-near-zero) — ECS Fargate + ALB is the alternative |
| App database | Cloud SQL for Postgres 16 | **RDS for PostgreSQL 16** (or Aurora Serverless v2) |
| Container registry | Artifact Registry | **Amazon ECR** |
| Secrets | Secret Manager | **AWS Secrets Manager** |
| Runtime identity | Runtime service account | **IAM role** (App Runner instance role) |
| Daily run trigger | Cloud Scheduler → `POST /api/run` | **EventBridge Scheduler** → `POST /api/run` (via API destination) |
| **BigQuery read** | **Native SA IAM grant** | **Workload Identity Federation** (AWS role ↔ GCP), **no key file** |
| IaC | Terraform (google provider) | Terraform (**aws** provider + a little **google** provider for the WIF pool + BQ grants) |

Everything except the BigQuery row is a like-for-like swap. The BigQuery row is the reason AWS is more
work, and it is the section to read most carefully (§3).

---

## 0. Decisions & access to gather first

- [ ] **AWS account id + region** to deploy into (Wonder's account, billing enabled). → sets Terraform
      `aws_account_id`, `region` (default `us-east-1` or match the client's standard region).
- [ ] **BigQuery source projects** (unchanged from GCP — the data lives in GCP either way):
  - [ ] Ledger/PO dataset project: `wonder-dw-prod-brd` (dataset `inventory`). → `bq_project`.
  - [ ] **ERP standard-cost project**: `wonder-raw-prod` (dataset `erp_prod_batch`) — used by the COST
        rules. **Separate project, needs its own federated read grant** (see §3).
  - [ ] **You still need owner/IAM access to these GCP projects** to create the Workload Identity Pool and
        grant BigQuery to the federated AWS identity. AWS hosting does not remove the GCP-side setup — it
        moves it from "create a service account" to "create a trust for an AWS role."
- [ ] **Client Jira** (identical to GCP §2): base URL, project key, issue type, a service-account Jira
      user + API token, and the exact **"Done"** transition name.
- [ ] **RDS app-user password** (you generate; goes into Secrets Manager, never committed).
- [ ] **Go-live cutover date** — the day you flip on daily runs and backfill the baseline (same as GCP §7).
- [ ] Who owns the AWS account / Terraform state / the GCP projects going forward (see §9 — migrate off
      personal accounts on **both** sides).

---

## 1. AWS account foundation

- [ ] **1.1** Confirm billing is enabled on the target AWS account and you have an admin/deployer IAM
      identity (or an assumable deploy role).
- [ ] **1.2** Authenticate locally for Terraform: `aws sso login` (or configure a named profile /
      `AWS_PROFILE`). Terraform's AWS provider reads the standard credential chain.
- [ ] **1.3** Decide **networking posture**. Two options, matching how "public/sandbox-shaped" the GCP
      scaffold is:
  - **Simple (matches GCP scaffold):** RDS with `publicly_accessible = true`, locked to the App Runner
      egress by security group; App Runner reaches BigQuery over its default public egress. Fastest to stand up.
  - **Hardened (recommended for real prod):** RDS in **private subnets**, App Runner attached via a **VPC
      connector**, and a **NAT gateway** so the container can still reach BigQuery + Jira on the internet.
      This is the AWS analog of the GCP "private IP" hardening in §10.
  > Note the asymmetry: on Cloud Run, private DB + internet egress is nearly free to configure. On App
  > Runner, putting the container in a VPC to reach a private RDS means you **also** need a NAT gateway
  > for its BigQuery/Jira egress (a small always-on cost). Budget for it if you choose the hardened path.
- [ ] **1.4** Decide Terraform **state backend**: use an **S3 backend + DynamoDB lock table** (encrypted,
      access-controlled) — **not** local state. State will contain the DB password and Jira token.

## 2. Client Jira setup (replace the sandbox)

**Identical to the GCP runbook §2 — Jira is external SaaS and cloud-agnostic.** In brief:

- [ ] **2.1** Confirm the client Jira **project** and note its **key** (scaffold default `WIQ`).
- [ ] **2.2** Create a **service-account user** + **API token** (<https://id.atlassian.com/manage/api-tokens>).
- [ ] **2.3** Confirm the **issue type** (default `Task`) and a **transition named exactly `Done`** (or set
      `JIRA_DONE_TRANSITION`).
- [ ] **2.4** *(Optional)* Custom field for the dedup fingerprint → `JIRA_FINGERPRINT_FIELD=customfield_xxxxx`
      (else it rides on a label).
- [ ] **2.5** Map each **owner group** to a real Jira assignee/component.
- [ ] **2.6** These become Terraform vars: `jira_base_url`, `jira_email`, `jira_project_key`,
      `jira_issue_type`, and the secret `jira_api_token`.

## 3. BigQuery read-only access — cross-cloud via Workload Identity Federation

**This is the one section that has no GCP-runbook equivalent, and it's the crux of hosting on AWS.** The
app must read BigQuery, which is in GCP. Instead of storing a Google service-account **key file** in AWS
(a long-lived secret — exactly what §9.4 tells us to avoid), we make Google **trust the App Runner IAM
role directly** via Workload Identity Federation. No Google key ever leaves GCP.

**How it works:** the app's Google client library (already using ADC / `GOOGLE_APPLICATION_CREDENTIALS`,
per the GCP runbook §3.3) is pointed at an **external-account credential config file**. That file contains
**no secret** — it only describes how to (a) fetch the App Runner role's AWS credentials from the instance
metadata, and (b) exchange them with Google STS for a short-lived Google token. The exchange is authorized
because we told Google to trust that AWS role.

- [ ] **3.1 (GCP side) Create a Workload Identity Pool + AWS provider.** In the GCP project you'll bill
      queries to (typically `bq_project`), create a pool and an **AWS provider** in it that references the
      client's **AWS account id**. *(Terraform: `google_iam_workload_identity_pool` +
      `google_iam_workload_identity_pool_provider` with an `aws { account_id = ... }` block.)*
- [ ] **3.2 (GCP side) Grant BigQuery to the federated AWS role — on both source projects.** Grant the
      principal that represents the App Runner role:
  - `roles/bigquery.jobUser` on the **billing project** (to run queries), and
  - `roles/bigquery.dataViewer` on **`wonder-dw-prod-brd`** (ledger/PO) **and** on **`wonder-raw-prod`**
    (ERP cost) — the same two grants as the GCP runbook §3.1/§3.2, just to a federated principal:
    `principalSet://iam.googleapis.com/projects/<num>/locations/global/workloadIdentityPools/<pool>/attribute.aws_role/arn:aws:sts::<acct>:assumed-role/<AppRunnerInstanceRole>`.
- [ ] **3.3 (AWS side) Create the App Runner instance IAM role** the container runs as. This is the role
      the config in 3.1 trusts. It needs no special AWS permissions for BigQuery — being *assumable by the
      task* is what matters — plus Secrets Manager read (§5) and RDS connectivity.
- [ ] **3.4 (App config) Provide the external-account config file + point ADC at it.** Bake the small JSON
      config into the image (or mount it) and set `GOOGLE_APPLICATION_CREDENTIALS=/path/to/wif.json`. Set
      the config's `quota_project_id` / billing to the BigQuery billing project. **No app code change** —
      the existing BigQuery client picks it up through ADC. Keep `GCP_PROJECT` / `ERP_PROJECT` env vars set
      as today so app config and grants stay in sync.
- [ ] **3.5** Confirm real table **column names** still match `wonder/schema_map.py` (unchanged from GCP —
      same tables).
- [ ] **3.6 Verify the token exchange end-to-end** from a running task before go-live: a
      `bigquery.jobs.query` from the container should succeed with **no key file present**. This is the
      single most important AWS-specific smoke test.

> If WIF setup slips the timeline, the fallback is a Google SA **key file** in AWS Secrets Manager — it
> works and needs no GCP pool, but it's a long-lived credential to rotate and guard. **Prefer WIF;** treat
> the key file as a temporary bridge only, and put rotation on the follow-up list.

## 4. Build & push the container image (ECR)

- [ ] **4.1** Same image as GCP — built from `app/Dockerfile`, context `./app`. Push to the **ECR** repo
      Terraform creates (`<acct>.dkr.ecr.<region>.amazonaws.com/wonder-dq`).
- [ ] **4.2** Same chicken-and-egg as GCP: App Runner needs an image, but the repo is created by apply.
      Clean options:
  - **Option A (recommended):** `terraform apply -target=aws_ecr_repository.app` first, then build/push,
    then full apply.
  - **Option B:** placeholder image, then update `image` and re-apply.
- [ ] **4.3** Build & push:
      ```bash
      aws ecr get-login-password --region <region> \
        | docker login --username AWS --password-stdin <acct>.dkr.ecr.<region>.amazonaws.com
      docker build -t <acct>.dkr.ecr.<region>.amazonaws.com/wonder-dq/app:<tag> ./app
      docker push <acct>.dkr.ecr.<region>.amazonaws.com/wonder-dq/app:<tag>
      ```
      *(App Runner can also build from source, but pushing a prebuilt image keeps it identical to GCP.)*
- [ ] **4.4** Set `image` in `terraform.tfvars` to that exact tag.

## 5. Configure Terraform variables (public, no SSO)

Copy `infra/terraform-aws/terraform.tfvars.example` → `terraform.tfvars`. **Secrets go via env, not the file.**

- [ ] **5.1** Non-secret vars:
      ```hcl
      aws_account_id        = "<wonder-aws-account>"
      region                = "us-east-1"
      image                 = "<acct>.dkr.ecr.<region>.amazonaws.com/wonder-dq/app:<tag>"

      allow_unauthenticated = true          # NO SSO: App Runner public endpoint for this launch

      bq_project            = "wonder-dw-prod-brd"
      erp_bq_project        = "wonder-raw-prod"
      bq_dataset            = "inventory"
      bq_ledger_table       = "consolidated_inventory_ledger"
      bq_po_table           = "int_ledger_purchase_orders"

      wif_pool_project      = "wonder-dw-prod-brd"   # GCP project holding the WIF pool + query billing

      jira_base_url         = "https://<client>.atlassian.net"
      jira_email            = "inventory-dq@<client>"
      jira_project_key      = "WIQ"
      jira_issue_type       = "Task"
      ```
- [ ] **5.2** Secrets via environment (never commit):
      ```bash
      export TF_VAR_db_password='<generated-strong-password>'
      export TF_VAR_jira_api_token='<client-jira-api-token>'
      ```
- [ ] **5.3** Sanity-check: `allow_unauthenticated = true` means the App Runner URL is **public**, including
      `POST /api/run` (which creates real Jira tickets). Accept this for the launch or gate it (WAF IP
      allow-list / VPC + private App Runner ingress) until SSO lands (§10).

## 6. Provision the infrastructure

- [ ] **6.1** `cd infra/terraform-aws`
- [ ] **6.2** `terraform init` (with the S3 backend from §1.4)
- [ ] **6.3** `terraform validate`
- [ ] **6.4** `terraform plan` — review: ECR repo, RDS Postgres 16 instance + db + user, 2 Secrets Manager
      secrets, App Runner service + instance role, WIF pool/provider + BigQuery grants (google provider),
      EventBridge Scheduler + API destination, security groups.
- [ ] **6.5** `terraform apply`
- [ ] **6.6** `terraform output service_url` → the public console URL. First boot runs `alembic upgrade head`
      automatically, provisioning the Postgres schema. *(App Runner runs the same container start command
      as Cloud Run.)*

## 7. Daily automation (EventBridge Scheduler → `POST /api/run`)

Same design as GCP §7: run once a day for the prior data day via an external scheduler, **not** the in-app
APScheduler (keep `SCHEDULER_ENABLED=false` so it isn't double-triggered — App Runner may idle the
instance, so an in-process timer is unreliable, exactly as on Cloud Run).

- [ ] **7.1** Trigger is `POST /api/run` (`wonder/api/routes.py` → `run_daily`) — unchanged.
- [ ] **7.2** Use **EventBridge Scheduler** with an **API destination** target to `POST <service_url>/api/run`
      on cron (`scheduler_schedule`, default `cron(15 0 * * ? *)`; `scheduler_time_zone`, default
      `America/Los_Angeles`). *(Terraform: `aws_scheduler_schedule` + `aws_cloudwatch_event_connection` +
      `aws_cloudwatch_event_api_destination`.)*
  - **Simplest alternative:** a tiny **Lambda** on an EventBridge cron that does one HTTP POST — fewer
    moving parts than API destinations if the team prefers it.
- [ ] **7.3** No auth this launch, so the scheduled call is **unauthenticated**. When SSO lands, put the
      auth token in the API-destination connection (or have the Lambda mint one).
- [ ] **7.4** The console polls `GET /api/runinfo` and shows a refresh banner when the run date advances —
      no extra wiring (unchanged).

## 8. Terraform completeness (what `infra/terraform-aws/` must contain)

Unlike the GCP module, this is **not yet written**. The module needs:

- [ ] **8.1 ECR repo** (`aws_ecr_repository`).
- [ ] **8.2 RDS Postgres** instance + parameter group + subnet group + security group; DB + app user.
- [ ] **8.3 Secrets Manager** secrets for `APP_DB_URL` and `JIRA_API_TOKEN` (+ versions).
- [ ] **8.4 App Runner** service (image from ECR), **instance IAM role**, env vars (mirroring the GCP
      container's env block: `DATA_SOURCE`, `TICKET_SINK`, `GCP_PROJECT`, `ERP_PROJECT`, `BQ_*`, `JIRA_*`,
      `GOOGLE_APPLICATION_CREDENTIALS`), secrets wired from Secrets Manager, port 8000; optional VPC
      connector for the hardened path.
- [ ] **8.5 Workload Identity Federation (the cross-cloud blocker for COST + all rules).** Uses the
      **google** provider inside the AWS module: `google_iam_workload_identity_pool`,
      `..._provider` (AWS account), and `google_project_iam_member` granting `bigquery.jobUser` +
      `dataViewer` (on both `bq_project` and `erp_bq_project`) to the federated App Runner-role principal.
      This is the AWS analog of the GCP module's `run_bq_data_viewer` / `run_erp_bq_data_viewer`.
- [ ] **8.6 EventBridge Scheduler** job + API destination (or Lambda) for the daily run.
- [ ] **8.7 Networking** — security groups (and, for the hardened path, VPC/subnets/NAT + VPC connector).
- [ ] **8.8 Verify auto-close config** against the client's Jira workflow (`JIRA_DONE_TRANSITION`,
      `JIRA_FINGERPRINT_FIELD`) — runtime verification, identical to GCP §8.4.

## 9. Migrate off personal / sandbox accounts (before or at go-live)

Same intent as GCP §9, on both clouds:

- [ ] **9.1 Repo + CI:** move `wonder_inventory` and its GitHub Actions/secrets into the **client's GitHub org**.
- [ ] **9.2 Jira:** point at the client's Jira (done in §2), not `dietrichcoding.atlassian.net`.
- [ ] **9.3 AWS:** deploy into the **client's AWS account**; Terraform state in the client's S3 bucket.
- [ ] **9.4 GCP:** the WIF pool + BigQuery grants live in the **client's GCP projects** — created under
      client-owned identities.
- [ ] **9.5 Tokens:** **re-issue every credential** (Jira API token, any PATs). With WIF there is **no
      Google key file to carry over** — one of the security upsides of doing it properly.

## 10. Explicitly deferred (post-go-live hardening)

Same trade-offs as GCP §10, AWS-flavored:

- **Auth / SSO:** the App Runner URL is public — anyone with it can trigger `POST /api/run` (real Jira
  tickets). Defer SSO (Entra/Cognito, or an ALB + OIDC front, or App Runner private ingress behind an
  authenticated ALB) to a follow-up; then set `allow_unauthenticated = false` and authenticate the
  scheduler call.
- **RDS hardening:** the simple posture is sandbox-shaped — **public RDS, single-AZ, `deletion_protection
  = false`, no final snapshot**. For prod: **private subnets + VPC connector + NAT**, **Multi-AZ**,
  automated backups + PITR, `deletion_protection = true`, `skip_final_snapshot = false`.
- **BigQuery credential:** ship on **WIF** (no key file). If a key file was used as a launch bridge (§3
  fallback), replace it with WIF and add rotation.
- **Exact breach-age backfill:** unchanged from GCP — prototype clamps age to ~2 weeks; decide backfill
  depth **X** and pull full per-PO history (bound BigQuery cost).
- **Baseline cutover reseed:** unchanged — at cutover pick the start date and backfill all open exceptions
  as the baseline; defer scope/threshold tuning to then.
- **Observability:** CloudWatch alarms on failed runs / anomalous error counts (analog of Cloud Logging).

## 11. Smoke test (after deploy)

- [ ] **11.1** Open `service_url` — the React console loads.
- [ ] **11.2** `GET <service_url>/api/runinfo` returns a `runDate`.
- [ ] **11.3** **BigQuery reachability (AWS-specific):** confirm a validation actually reads BigQuery — i.e.
      the WIF token exchange works from the running task with **no key file present** (§3.6).
- [ ] **11.4** Trigger one `POST <service_url>/api/run` and confirm the summary
      (`scanned/seen/new/autoClosed`) looks sane.
- [ ] **11.5** Confirm a **real ticket appears in the client's Jira** with the right project/type/assignee,
      and that a resolved item **auto-closes** on the next run.
- [ ] **11.6** Confirm the daily EventBridge Scheduler job fires and advances the run date (refresh banner).
