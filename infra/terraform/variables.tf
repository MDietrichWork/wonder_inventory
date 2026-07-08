variable "project_id" {
  description = "GCP project to deploy into. SANDBOX today; retarget to Wonder's project at go-live."
  type        = string
}

variable "region" {
  description = "Region for Cloud Run + Cloud SQL + Artifact Registry."
  type        = string
  default     = "us-central1"
}

variable "service_name" {
  description = "Base name for the Cloud Run service and related resources."
  type        = string
  default     = "wonder-dq"
}

variable "image" {
  description = "Container image to deploy (e.g. REGION-docker.pkg.dev/PROJECT/wonder-dq/app:TAG). Built from app/Dockerfile and pushed to the Artifact Registry repo below."
  type        = string
}

variable "allow_unauthenticated" {
  description = "Expose the console publicly (run.invoker for allUsers). Fine for a quick sandbox demo; at go-live keep this false and put it behind IAP / Entra SSO."
  type        = bool
  default     = false
}

# --- Cloud SQL (Postgres) ---
variable "db_tier" {
  description = "Cloud SQL machine tier. db-f1-micro is fine for sandbox; bump (+ HA + backups) for prod."
  type        = string
  default     = "db-f1-micro"
}

variable "db_name" {
  type    = string
  default = "wonderdq"
}

variable "db_user" {
  type    = string
  default = "wonder"
}

variable "db_password" {
  description = "Cloud SQL app-user password. Provide via TF_VAR_db_password (env) — never commit it."
  type        = string
  sensitive   = true
}

# --- BigQuery (read-only source) ---
variable "bq_project" {
  description = "Project that holds the inventory dataset (may differ from project_id)."
  type        = string
}

variable "erp_bq_project" {
  description = "Project that holds the ERP standard-cost dataset (read by the COST rules; separate from bq_project). The runtime SA is granted bigquery.dataViewer here too."
  type        = string
  default     = "wonder-raw-prod"
}

variable "bq_dataset" {
  type    = string
  default = "inventory"
}

variable "bq_ledger_table" {
  type    = string
  default = "consolidated_inventory_ledger"
}

variable "bq_po_table" {
  type    = string
  default = "int_ledger_purchase_orders"
}

# --- Jira ---
variable "jira_base_url" {
  type = string
}

variable "jira_email" {
  type = string
}

variable "jira_project_key" {
  type    = string
  default = "WIQ"
}

variable "jira_issue_type" {
  type    = string
  default = "Task"
}

variable "jira_api_token" {
  description = "Jira API token. Provide via TF_VAR_jira_api_token (env) — never commit it."
  type        = string
  sensitive   = true
}

# --- Daily validation run (Cloud Scheduler -> POST /api/run) ---
variable "scheduler_schedule" {
  description = "Cron for the daily validation run. Default 00:15 (see scheduler_time_zone) — just after the prior data day closes."
  type        = string
  default     = "15 0 * * *"
}

variable "scheduler_time_zone" {
  description = "Time zone for scheduler_schedule (IANA name)."
  type        = string
  default     = "America/Los_Angeles"
}
