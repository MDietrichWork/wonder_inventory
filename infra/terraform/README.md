# Wonder DQ — infrastructure (Terraform)

Provisions the console on GCP: **Cloud Run** (the container from `app/Dockerfile`), **Cloud SQL
for Postgres** (the app DB), **Secret Manager** (DB URL + Jira token), **Artifact Registry** (image
repo), a least-privilege **runtime service account**, and **read-only BigQuery** access.

> Status: **scaffold**, validated against the Google provider but **not yet applied** — it needs a
> GCP project + credentials. Today everything is on personal/sandbox accounts; at go-live retarget
> `project_id` (and `bq_project` if different) to **Wonder's** project and re-issue all tokens.

## Prerequisites
- `terraform >= 1.5`, `gcloud` authenticated (`gcloud auth application-default login`).
- A GCP project with billing enabled.

## Deploy
```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars     # fill in non-secret values

# Secrets via env (never commit them):
export TF_VAR_db_password='...'
export TF_VAR_jira_api_token='...'

# Build + push the image to Artifact Registry (repo is created by `terraform apply`):
#   gcloud builds submit ../../app --tag REGION-docker.pkg.dev/PROJECT/wonder-dq/app:TAG
# then set `image` in terraform.tfvars to that tag.

terraform init
terraform validate
terraform plan
terraform apply
```
`terraform output service_url` prints the console URL. The container runs `alembic upgrade head`
on start, so the Postgres schema is provisioned automatically.

## Notes / go-live hardening
- **State holds secrets** (DB password flows into the `app-db-url` secret + the SQL user). Use the
  GCS backend in `versions.tf` (encrypted, access-controlled) — not local state.
- `allow_unauthenticated = true` is for a quick sandbox demo only. In prod set it `false` and front
  the service with **IAP / Entra SSO**.
- Cloud SQL is sandbox-shaped (public IP, single zone). Prod: **private IP**, `REGIONAL` HA, PITR,
  `deletion_protection = true`.
- BigQuery stays **read-only** (`bigquery.jobUser` + `bigquery.dataViewer` on the source project).
- See the project's open items: migrate repo/CI/Jira/GCP off personal sandbox accounts to Wonder's org.
