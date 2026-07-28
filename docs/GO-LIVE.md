# Go-Live Runbook — Wonder DQ Console

Step-by-step to take the console live. Scoped to the **three constraints for this launch**:

1. **Hosted on GCP** — single container (FastAPI API + built React app) on **Cloud Run**, app data in
   **Cloud SQL for Postgres**, source data read-only from **BigQuery**.
2. **Linked to the client's real Jira** — not the sandbox `dietrichcoding.atlassian.net`.
3. **No SSO / no permissions** — the service is **publicly invokable** (`allow_unauthenticated = true`).
   Entra SSO / IAP is **explicitly deferred** (see [§10](#10-explicitly-deferred-post-go-live-hardening)).

> How the app runs today: one image built from `app/Dockerfile` (Vite build → served by FastAPI). The
> container's start command is `alembic upgrade head && uvicorn wonder.main:app` — so the Postgres
> schema is created/migrated automatically on first boot **— provided a migration exists for every
> model change (see [§12](#12-database-migrations--new-tables-since-the-initial-migration)).** Behavior
> is controlled entirely by env vars (`app/backend/wonder/config.py`); the two switches that make it
> "live" are `DATA_SOURCE=bigquery` and `TICKET_SINK=jira`.

Infra lives in `infra/terraform/` (Cloud Run + Cloud SQL + Secret Manager + Artifact Registry + a
least-privilege runtime SA). It's a **validated scaffold, not yet applied**. The two blocker gaps from
the first review — the ERP BigQuery grant and the daily-run automation — **have now been added to the
Terraform** (see [§8](#8-terraform-completeness-now-closed)); remaining items are config/verification.

---

## 0. Decisions & access to gather first

- [ ] **GCP project id** to deploy into (Wonder's project, billing enabled). → sets Terraform `project_id`.
- [ ] **Region** (default `us-central1`). → `region`.
- [ ] **BigQuery source projects** — confirm both:
  - [ ] Ledger/PO dataset project: `wonder-dw-prod-brd` (dataset `inventory`). → `bq_project`.
  - [ ] **ERP standard-cost project**: `wonder-raw-prod` (dataset `erp_prod_batch`) — used by the COST
        rules. **This is a separate project and needs its own read grant** (see §8).
- [ ] **Client Jira**: base URL (`https://<client>.atlassian.net`), the **project key** to file into,
      the **issue type**, a **service-account Jira user** + **API token**, and the exact **"Done"
      transition name** in that project's workflow (auto-close depends on it).
- [ ] **Cloud SQL app-user password** (you generate; goes into Secret Manager, never committed).
- [ ] **Go-live cutover date** — the day you flip on daily runs and backfill the baseline (see §7).
- [ ] Who owns the GCP project / Terraform state going forward (see §9 — migrate off personal accounts).

---

## 1. GCP project foundation

- [ ] **1.1** Confirm billing is enabled on the target project.
- [ ] **1.2** Authenticate locally for Terraform: `gcloud auth application-default login`.
- [ ] **1.3** APIs are enabled automatically by Terraform (`google_project_service`): Cloud Run, SQL
      Admin, Secret Manager, Artifact Registry, BigQuery, IAM. **Add Cloud Scheduler** (`cloudscheduler.googleapis.com`)
      to that list — needed for the daily run in §7 (currently missing; see §8).
- [ ] **1.4** Decide Terraform **state backend**: use the GCS backend (encrypted, access-controlled),
      **not** local state — Terraform state will contain the DB password and Jira token. Wire the
      backend block in `infra/terraform/versions.tf` before `init`.

## 2. Client Jira setup (replace the sandbox)

- [ ] **2.1** In the client's Jira Cloud, create/confirm the **project** the tickets land in and note
      its **key** (scaffold default is `WIQ` — change if the client uses a different key).
- [ ] **2.2** Create a **service account user** in the client's Jira (e.g. `inventory-dq@client`) and
      generate an **API token** at <https://id.atlassian.com/manage/api-tokens>. Tickets will be
      created/commented as this user.
- [ ] **2.3** Confirm the **issue type** exists (default `Task`) and the project's **workflow has a
      transition named exactly `Done`** (or set `JIRA_DONE_TRANSITION` to the real name — auto-close
      calls this transition).
- [ ] **2.4** *(Optional but recommended)* Create a **custom field** to hold the dedup fingerprint and
      set `JIRA_FINGERPRINT_FIELD=customfield_xxxxx`. Without it, the fingerprint rides on a **label**
      (works, but a field is cleaner). Confirm the field is on the project's create screen.
- [ ] **2.5** Map each **owner group** (SC Product/IMS, Field Ops, HDR Field Ops, Procurement,
      Accounting/Cost Accountant) to a real Jira **assignee/component** in the client instance, so
      routing lands on the right people.
- [ ] **2.6** These values become Terraform vars: `jira_base_url`, `jira_email`, `jira_project_key`,
      `jira_issue_type`, and the secret `jira_api_token`.

## 3. BigQuery read-only access

The runtime service account (created by Terraform) needs **read-only** BigQuery on **both** source
projects. It uses `bigquery.jobUser` (to run queries, granted on the deploy project) + `bigquery.dataViewer`
(to read data, granted on each source project).

- [ ] **3.1** Ledger/PO project (`bq_project`, e.g. `wonder-dw-prod-brd`) — `dataViewer` grant is in the
      Terraform (`run_bq_data_viewer`). ✅
- [ ] **3.2** **ERP project (`wonder-raw-prod`)** — now granted in Terraform via the
      `run_erp_bq_data_viewer` resource (`erp_bq_project` var, default `wonder-raw-prod`; the container
      also gets `ERP_PROJECT` so app + grant stay in sync). Just confirm `erp_bq_project` is correct for
      the client. ✅
- [ ] **3.3** No key file is needed on Cloud Run — the runtime SA is used automatically. (Locally,
      `GOOGLE_APPLICATION_CREDENTIALS` or ADC is used; in prod leave it unset.)
- [ ] **3.4** Confirm the real table **column names** match `wonder/schema_map.py`. (Already validated
      against `wonder-dw-prod-brd.inventory` in the live local runs — re-confirm if the client points at
      different tables.)

## 4. Build & push the container image

- [ ] **4.1** The image is built from `app/Dockerfile` with build context `./app`. Push to the Artifact
      Registry repo that Terraform creates (`<region>-docker.pkg.dev/<project>/wonder-dq`).
- [ ] **4.2** Chicken-and-egg note: the repo is created by `terraform apply`, but the Cloud Run service
      needs an image. Two clean options:
  - **Option A (recommended):** first apply only the registry —
    `terraform apply -target=google_artifact_registry_repository.app` — then build/push, then full apply.
  - **Option B:** push to a temporary repo / use a placeholder image, then update `image` and re-apply.
- [ ] **4.3** Build & push:
      ```bash
      gcloud builds submit ./app \
        --tag <region>-docker.pkg.dev/<project>/wonder-dq/app:<tag>
      ```
- [ ] **4.4** Set `image` in `terraform.tfvars` to that exact tag.

## 5. Configure Terraform variables (public, no SSO)

Copy `infra/terraform/terraform.tfvars.example` → `terraform.tfvars` and fill in. **Secrets go via env,
not the file.**

- [ ] **5.1** Non-secret vars in `terraform.tfvars`:
      ```hcl
      project_id            = "<wonder-gcp-project>"
      region                = "us-central1"
      image                 = "<region>-docker.pkg.dev/<project>/wonder-dq/app:<tag>"

      allow_unauthenticated = true          # <-- NO SSO: public invoker for this launch

      bq_project            = "wonder-dw-prod-brd"
      bq_dataset            = "inventory"
      bq_ledger_table       = "consolidated_inventory_ledger"
      bq_po_table           = "int_ledger_purchase_orders"

      jira_base_url         = "https://<client>.atlassian.net"   # <-- client Jira, not sandbox
      jira_email            = "inventory-dq@<client>"
      jira_project_key      = "WIQ"          # <-- client's key
      jira_issue_type       = "Task"
      ```
- [ ] **5.2** Secrets via environment (never commit):
      ```bash
      export TF_VAR_db_password='<generated-strong-password>'
      export TF_VAR_jira_api_token='<client-jira-api-token>'
      ```
- [ ] **5.3** Sanity-check: `allow_unauthenticated = true` is intentional for this launch (no SSO). It
      grants `roles/run.invoker` to `allUsers` — anyone with the URL can reach it, **including the
      `POST /api/run` endpoint, which creates real Jira tickets.** Accept this risk or gate the URL by
      obscurity/VPC until SSO lands (see §10).

## 6. Provision the infrastructure

- [ ] **6.1** `cd infra/terraform`
- [ ] **6.2** `terraform init` (with the GCS backend from §1.4)
- [ ] **6.3** `terraform validate`
- [ ] **6.4** `terraform plan` — review: Cloud Run service, Cloud SQL Postgres 16 instance + db + user,
      2 secrets (+versions), Artifact Registry repo, runtime SA + IAM, public invoker binding.
- [ ] **6.5** `terraform apply`
- [ ] **6.6** `terraform output service_url` → the public console URL. First boot runs
      `alembic upgrade head` automatically, provisioning the Postgres schema.

## 7. Daily automation (Cloud Scheduler → `POST /api/run`)

The validation runs once a day for the prior data day. Locally this is a stand-in APScheduler
(`SCHEDULER_ENABLED`); **in prod that in-app scheduler is unreliable because Cloud Run scales to zero**
(`min_instance_count = 0`), so a scaled-down instance won't fire the timer. Use **Cloud Scheduler**
hitting the HTTP endpoint instead. Keep `SCHEDULER_ENABLED=false` on Cloud Run so the job isn't
double-triggered.

- [ ] **7.1** Confirm `POST /api/run` is the trigger (it exists: `wonder/api/routes.py` →
      `run_daily`). It scans the prior day, opens/auto-closes tickets, returns a summary.
- [ ] **7.2** The Cloud Scheduler job is now in Terraform (`google_cloud_scheduler_job.daily_run`):
      `POST <service_url>/api/run`, schedule `scheduler_schedule` (default `15 0 * * *`), time zone
      `scheduler_time_zone` (default `America/Los_Angeles`). It's created by `terraform apply` — no
      manual `gcloud` step needed. Adjust the two vars if the client wants a different time.
- [ ] **7.3** Because there's no auth this launch, the scheduler calls the endpoint **unauthenticated**
      (the `oidc_token` block auto-activates only when `allow_unauthenticated = false`). When SSO lands,
      flip that var and the scheduler switches to an OIDC-authenticated call automatically.
- [ ] **7.4** The console polls `GET /api/runinfo` and shows a refresh banner when the run date advances
      — no extra wiring needed.
- [ ] **7.5** The daily run also **purges closed tickets** older than the retention window (Admin →
      *Data retention*, default **30 days**; `0` = keep forever, stored in the new `app_setting` table).
      This is local app-DB cleanup only — **Jira is untouched** (it stays the system of record). Confirm
      the retention window with the client at cutover. *(Requires the migration in [§12](#12-database-migrations--new-tables-since-the-initial-migration).)*

## 8. Terraform completeness (now closed)

The two blocker gaps from the first review are **now written into `infra/terraform/` and
`terraform validate` passes**:

- [x] **8.1 ERP BigQuery grant (was a blocker for COST rules).** Added
      `google_project_iam_member.run_erp_bq_data_viewer` — grants `bigquery.dataViewer` to the runtime
      SA on `var.erp_bq_project` (default `wonder-raw-prod`). Guarded by a `count` so it's skipped if the
      ERP project equals `bq_project`. The container also now receives `ERP_PROJECT` so app config and
      the grant can't drift.
- [x] **8.2 Daily run automation (was a blocker for "runs daily").** Added
      `google_cloud_scheduler_job.daily_run` (`POST <service_url>/api/run`) plus
      `cloudscheduler.googleapis.com` in the enabled `apis`. New vars: `scheduler_schedule`,
      `scheduler_time_zone`.
- [ ] **8.3 Scheduler vs. scale-to-zero.** Leave `SCHEDULER_ENABLED=false` (default) on Cloud Run;
      driving the run from Cloud Scheduler avoids needing `min_instance_count >= 1`. (No code change —
      just don't set the flag.)
- [ ] **8.4 Verify auto-close config end-to-end** against the client's Jira workflow: `JIRA_DONE_TRANSITION`
      must match a real transition name, and `JIRA_FINGERPRINT_FIELD` (if used) must be a valid field on
      the project. *(Runtime verification, not a Terraform change.)*

## 9. Migrate off personal / sandbox accounts (before or at go-live)

Everything is currently on the consultant's personal accounts. Move it to client-owned:

- [ ] **9.1 Repo + CI:** move `wonder_inventory` (GitHub `MDietrichWork`) and its GitHub Actions,
      branch protections, and secrets into the **client's GitHub org**.
- [ ] **9.2 Jira:** stop using `dietrichcoding.atlassian.net`; point at the client's Jira (done in §2).
- [ ] **9.3 GCP:** deploy into the client's project (done in §1); Terraform state in the client's GCS.
- [ ] **9.4 Tokens:** **re-issue every token** (Jira API token, any PATs, SA keys) under client-owned
      identities — no carried-over personal credentials.

## 10. Explicitly deferred (post-go-live hardening)

Called out so the team knows the trade-offs accepted for a fast, no-permissions launch:

- **Auth / SSO:** `allow_unauthenticated = true` means **anyone with the URL can use the app and trigger
  `POST /api/run` (real Jira tickets)**. Defer Microsoft Entra ID (OIDC/MSAL) + IAP and role-based
  access to a follow-up; when it lands, set `allow_unauthenticated = false`, front with IAP/SSO, and
  switch the scheduler to an authenticated OIDC call.
- **Cloud SQL hardening:** the scaffold is sandbox-shaped — **public IP, single zone,
  `deletion_protection = false`**. For prod: **private IP**, `availability_type = "REGIONAL"` (HA),
  backups + PITR, `deletion_protection = true`.
- **Exact breach-age backfill:** the prototype clamps age to a ~2-week window. For exact breach age at
  go-live, decide backfill depth **X** and pull full per-PO receipt history (bound BigQuery cost).
- **Baseline cutover reseed:** at cutover, pick the start date and **backfill all open exceptions as the
  baseline** so day-one isn't a flood; defer scope/threshold tuning (e.g. `CONSUMABLE_ZERO_COST` scope,
  waste thresholds) to then.
- **Observability:** Cloud Logging/Monitoring alerts on failed runs / anomalous error counts.

## 11. Smoke test (after deploy)

- [ ] **11.1** Open `service_url` — the React console loads.
- [ ] **11.2** `GET <service_url>/api/runinfo` returns a `runDate`.
- [ ] **11.3** Trigger one `POST <service_url>/api/run` and confirm the summary
      (`scanned/seen/new/autoClosed`) looks sane.
- [ ] **11.4** Confirm a **real ticket appears in the client's Jira** with the right project/type/assignee,
      and that a resolved item **auto-closes** on the next run.
- [ ] **11.5** Confirm the daily Cloud Scheduler job fires and advances the run date (refresh banner).

## 12. Database migrations — new tables since the initial migration

The Postgres schema is owned by **Alembic** (`alembic upgrade head` runs on container boot — see the
intro and §6.6). **Local dev uses `Base.metadata.create_all` (`app/backend/wonder/db.py`), so new
tables appear automatically on SQLite — but *not* on Postgres.** Postgres only gets what the migration
files in `app/backend/alembic/versions/` create, and there is currently just one
(`d43ff7a17b74_initial_schema`).

The data model has gained a table since that migration:

- **`app_setting`** — key/value store backing the **closed-ticket retention** feature (Admin →
  *Data retention*, and the daily purge in §7.5). Without a migration, `alembic upgrade head` will not
  create it and the app will error the first time it reads or writes the retention window on Postgres.

**Do this before building the image for cutover ([§4](#4-build--push-the-container-image)):**

- [ ] **12.1** Autogenerate a migration (models are wired into Alembic via `target_metadata = Base.metadata`
      in `alembic/env.py`):
      ```bash
      cd app/backend
      # point Alembic at any reachable DB (even the local SQLite) — autogenerate diffs the models, not data
      alembic revision --autogenerate -m "add app_setting (closed-ticket retention)"
      ```
- [ ] **12.2** Review the generated file in `alembic/versions/` — confirm it **only creates `app_setting`**
      (and nothing unexpected), then commit it. It runs automatically as part of `alembic upgrade head`
      on the next deploy, so there's no manual DB step in prod.
- [ ] **12.3** **Every future model change needs the same treatment.** The "schema is created
      automatically on first boot" guarantee (intro, §A.4) only holds if a migration exists for each
      change to `wonder/models.py`. Local SQLite hides a missing migration; Postgres will not.

> **Rule of thumb:** touched `wonder/models.py`? Generate and commit an Alembic migration before it
> reaches Postgres.

---

## Appendix A — Plain-English primer (for stakeholder conversations)

Non-technical background for anyone who needs to understand or explain *what this deploys and how* —
no prior knowledge assumed. The runbook above is the "how to do it"; this is the "what it is and why."

### A.1 What Terraform is

**Terraform is a tool that lets you describe your cloud setup in a text file, and then builds it for you
automatically.** Instead of clicking around in the Google Cloud web console for an hour to create a
database, a server, some passwords, and permissions, you write down *what you want* in a file, and
Terraform makes reality match that file.

> **Analogy:** it's the difference between building a house by telling workers what to do, room by room,
> verbally, every time — versus handing them a **blueprint**. The blueprint is repeatable, reviewable,
> and if the house burns down you can rebuild it exactly. Terraform is the blueprint for cloud
> infrastructure. The industry term for this is **"Infrastructure as Code"** — your servers, databases,
> and permissions are written as code and version-controlled just like the app itself.

### A.2 How Terraform works — the basic loop

Three commands and one concept:

1. **You write** what you want in `.tf` files — "I want a Postgres database, a container running my app,
   and these permissions." You describe the *end state*, not the step-by-step; Terraform works out the order.
2. **`terraform plan`** shows a **preview**: "I will create these 12 things, change this 1, delete nothing."
   Nothing happens yet — this is the safety step you read before committing.
3. **`terraform apply`** actually builds it, calling Google Cloud's APIs in the right order (e.g. the
   database is created before the app that connects to it).

The one concept to know is **state**: Terraform keeps a record of what it has built, so later you can edit
the file (say, bump the database size), run `plan` (it shows *only* that one change), and `apply` — it makes
the minimal change rather than rebuilding everything. Two words clients like: it's **declarative** (you
declare the desired result) and **idempotent** (running it again when things already match does nothing).

### A.3 How this application uses Terraform

The Terraform lives in **`infra/terraform/`** and is the complete blueprint for running the app on Google
Cloud. One `terraform apply` against the client's Google account stands up the entire environment:

| The blueprint creates… | In plain English |
|---|---|
| **Cloud Run** | The place the app container actually runs (the web server) |
| **Cloud SQL (Postgres)** | The app's own database (see A.4) |
| **Artifact Registry** | Private storage for the app's packaged image |
| **Secret Manager** | A secure vault for the database password and Jira API token — never in plain files |
| **A runtime service account + permissions** | The app's own identity, given *exactly* the access it needs — read-only to BigQuery, nothing more |
| **BigQuery read grants** | Permission to read Wonder's inventory data (the two source projects) |
| **Cloud Scheduler** | The alarm clock that triggers the daily validation run |

**Why this is good for the client:** it's repeatable (the whole environment rebuilds in minutes, the same
way every time), reviewable (infrastructure changes are approved like code before touching production),
auditable (you can see exactly what exists and who changed it), and not locked in one person's head (it's
written down — anyone on the team can read it). If something is deleted, re-running `apply` brings it back.

> **One honest caveat:** `apply` is powerful — it can also *change or delete* real things — which is exactly
> why the `plan` preview step exists and why the state file is stored securely (it contains those secrets;
> see §1.4).

### A.4 What the database is for — and why there are two

The app touches **two different databases that do opposite jobs.** The one Terraform creates is the second.

- **BigQuery — the source data (read-only, already exists, Wonder owns it).** Wonder's data warehouse: the
  inventory ledger, purchase orders, ERP standard costs. The app **only reads** it and **never writes** to
  it. Terraform doesn't create this; it just grants read-only access.
- **Cloud SQL (Postgres) — the app's own database (this is what Terraform creates).** The application's
  private workspace. It starts empty and the app fills it. Wonder's raw data never lives here — only the
  app's own working records.

> **Analogy:** BigQuery is the **filing cabinet of company records** (you only read from it). The Postgres
> database is the **auditor's own notebook** — where the app writes "I found this problem, on this date, I
> opened this Jira ticket, here's who it's assigned to, here's whether it's been fixed." The notebook is
> useless without the filing cabinet, but they're separate things.

**Why the app needs its own database at all:** it has to *remember things between daily runs*. Without it,
every morning the app would re-scan the data, find the same problems, and open duplicate Jira tickets — every
day. The database is what makes it smart instead: it remembers which problems it has already seen (no
duplicate tickets), when each first appeared (breach age / SLA), and which Jira ticket goes with which
problem (so it can **auto-close** the right one when the problem is fixed). It also stores the settings you
can edit in the app (like dollar thresholds) so your changes persist.

What's actually stored in it (the real tables, in plain English):

| Table | What it remembers |
|---|---|
| **`error`** | The heart of it: every data problem found — the rule that caught it, the item, severity, when first seen, status (Open/Resolved), assignee, and **which Jira ticket** it created. Prevents duplicates; enables auto-close. |
| **`validation_run`** | A log of each daily run — the date, rows scanned, how many problems were new, how many auto-closed. (Drives the run date + refresh banner.) |
| **`ticket_event`** | The history/audit trail of each ticket — status changes, notes, when and by whom. |
| **`rule`** | The catalog of validation rules (e.g. `PO-01`), their severity and routing. |
| **`routing_map`** | Who each type of problem is assigned to in Jira (team / person / component). |
| **`sla_target`** | The deadline per severity level (Urgent = 0 days, High = 1 day, etc.). |
| **`facility_threshold`**, **`waste_action_combo`** | The dollar thresholds and rule settings **editable in the Admin screen** — stored here so edits persist and the next run honors them. |
| **`app_setting`** | Small key/value app settings edited in the Admin screen — currently the **closed-ticket retention window** (how many days resolved/auto-closed tickets are kept before the daily run purges them; `0` = keep forever). |
| **`audit_log`** | A record of who changed what settings, with before/after values. |

The database starts **empty** and is **built automatically** on first startup — the container runs
`alembic upgrade head` on boot, which creates all these tables. So Terraform creates the *empty database
server*, and the app creates its *own tables* inside it on first run. Nobody sets up tables by hand.

> **The one-liner for the client:** *"The app reads the company's inventory data from BigQuery, and keeps
> its own separate record — in a small Postgres database — of every issue it's found and every Jira ticket
> it's opened, so it never duplicates work and can automatically close tickets once problems are fixed."*
