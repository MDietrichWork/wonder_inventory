# Wonder DQ console — Cloud Run + Cloud SQL (Postgres) + Secret Manager + Artifact Registry.
# Scaffold: validated against the Google provider; retarget `project_id`/`bq_project` to Wonder's
# project and `terraform apply` once that access exists. The app image is built from app/Dockerfile.

locals {
  # The app reads a single APP_DB_URL. On Cloud Run + Cloud SQL the connection is a unix socket
  # at /cloudsql/<connection_name>; psycopg takes it via the `host` query param.
  app_db_url = "postgresql+psycopg://${var.db_user}:${var.db_password}@/${var.db_name}?host=/cloudsql/${google_sql_database_instance.pg.connection_name}"

  apis = [
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
    "bigquery.googleapis.com",
    "iam.googleapis.com",
    "cloudscheduler.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each           = toset(local.apis)
  service            = each.value
  disable_on_destroy = false
}

# --- Artifact Registry (Docker images) ---
resource "google_artifact_registry_repository" "app" {
  location      = var.region
  repository_id = var.service_name
  format        = "DOCKER"
  description   = "Wonder DQ console images"
  depends_on    = [google_project_service.apis]
}

# --- Runtime service account (least privilege) ---
resource "google_service_account" "run" {
  account_id   = "${var.service_name}-run"
  display_name = "Wonder DQ Cloud Run runtime"
}

# Cloud SQL client + read secrets + read-only BigQuery (run queries + read data).
resource "google_project_iam_member" "run_roles" {
  for_each = toset([
    "roles/cloudsql.client",
    "roles/secretmanager.secretAccessor",
    "roles/bigquery.jobUser",
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.run.email}"
}

# BigQuery data read is granted on the source project (may differ from the deploy project).
resource "google_project_iam_member" "run_bq_data_viewer" {
  project = var.bq_project
  role    = "roles/bigquery.dataViewer"
  member  = "serviceAccount:${google_service_account.run.email}"
}

# ERP standard-cost data lives in a SECOND project (var.erp_bq_project). The COST rules read it,
# so the runtime SA needs dataViewer there as well. Skipped only if it's the same project as bq_project.
resource "google_project_iam_member" "run_erp_bq_data_viewer" {
  count   = var.erp_bq_project == var.bq_project ? 0 : 1
  project = var.erp_bq_project
  role    = "roles/bigquery.dataViewer"
  member  = "serviceAccount:${google_service_account.run.email}"
}

# --- Cloud SQL: Postgres instance + database + app user ---
resource "google_sql_database_instance" "pg" {
  name             = "${var.service_name}-pg"
  database_version = "POSTGRES_16"
  region           = var.region

  settings {
    tier = var.db_tier
    # Sandbox defaults. PROD: set availability_type = "REGIONAL", enable backups + PITR,
    # and prefer a private IP (ip_configuration { ipv4_enabled = false, private_network = ... }).
    ip_configuration {
      ipv4_enabled = true
    }
    backup_configuration {
      enabled = true
    }
  }

  deletion_protection = false # sandbox; set true in prod
  depends_on          = [google_project_service.apis]
}

resource "google_sql_database" "db" {
  name     = var.db_name
  instance = google_sql_database_instance.pg.name
}

resource "google_sql_user" "app" {
  name     = var.db_user
  instance = google_sql_database_instance.pg.name
  password = var.db_password
}

# --- Secret Manager: secrets the app reads at runtime ---
resource "google_secret_manager_secret" "app_db_url" {
  secret_id = "${var.service_name}-app-db-url"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "app_db_url" {
  secret      = google_secret_manager_secret.app_db_url.id
  secret_data = local.app_db_url
}

resource "google_secret_manager_secret" "jira_token" {
  secret_id = "${var.service_name}-jira-api-token"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "jira_token" {
  secret      = google_secret_manager_secret.jira_token.id
  secret_data = var.jira_api_token
}

# --- Cloud Run service ---
resource "google_cloud_run_v2_service" "app" {
  name     = var.service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.run.email

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    # Cloud SQL connection mounted at /cloudsql/<connection_name>.
    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.pg.connection_name]
      }
    }

    containers {
      image = var.image

      ports {
        container_port = 8000
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      # Plain config
      env {
        name  = "DATA_SOURCE"
        value = "bigquery"
      }
      env {
        name  = "TICKET_SINK"
        value = "jira"
      }
      env {
        name  = "GCP_PROJECT"
        value = var.bq_project
      }
      env {
        name  = "ERP_PROJECT"
        value = var.erp_bq_project
      }
      env {
        name  = "BQ_DATASET"
        value = var.bq_dataset
      }
      env {
        name  = "BQ_LEDGER_TABLE"
        value = var.bq_ledger_table
      }
      env {
        name  = "BQ_PO_TABLE"
        value = var.bq_po_table
      }
      env {
        name  = "JIRA_BASE_URL"
        value = var.jira_base_url
      }
      env {
        name  = "JIRA_EMAIL"
        value = var.jira_email
      }
      env {
        name  = "JIRA_PROJECT_KEY"
        value = var.jira_project_key
      }
      env {
        name  = "JIRA_ISSUE_TYPE"
        value = var.jira_issue_type
      }

      # Secrets
      env {
        name = "APP_DB_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.app_db_url.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "JIRA_API_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.jira_token.secret_id
            version = "latest"
          }
        }
      }
    }
  }

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_version.app_db_url,
    google_secret_manager_secret_version.jira_token,
    google_project_iam_member.run_roles,
  ]
}

# Optional public access (sandbox only). At go-live, remove this and front with IAP / Entra SSO.
resource "google_cloud_run_v2_service_iam_member" "public" {
  count    = var.allow_unauthenticated ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.app.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# --- Daily validation run: Cloud Scheduler -> POST /api/run ---
# The prod stand-in for the in-app APScheduler (which can't fire reliably while Cloud Run scales to
# zero). Keep SCHEDULER_ENABLED=false on the service so the run isn't double-triggered.
resource "google_cloud_scheduler_job" "daily_run" {
  name        = "${var.service_name}-daily-run"
  region      = var.region
  description = "Nightly Wonder DQ validation (prior data day): open/auto-close tickets."
  schedule    = var.scheduler_schedule
  time_zone   = var.scheduler_time_zone

  http_target {
    http_method = "POST"
    uri         = "${google_cloud_run_v2_service.app.uri}/api/run"

    # No SSO this launch: the service is public (allow_unauthenticated=true), so the call is
    # unauthenticated. When auth lands, set allow_unauthenticated=false and add an oidc_token
    # block here (service_account_email = a dedicated invoker SA, audience = the service URL).
    dynamic "oidc_token" {
      for_each = var.allow_unauthenticated ? [] : [1]
      content {
        service_account_email = google_service_account.run.email
        audience              = google_cloud_run_v2_service.app.uri
      }
    }
  }

  depends_on = [
    google_project_service.apis,
    google_cloud_run_v2_service.app,
  ]
}
