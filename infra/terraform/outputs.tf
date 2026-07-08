output "service_url" {
  description = "Public URL of the Cloud Run service."
  value       = google_cloud_run_v2_service.app.uri
}

output "cloudsql_connection_name" {
  description = "Cloud SQL instance connection name (PROJECT:REGION:INSTANCE)."
  value       = google_sql_database_instance.pg.connection_name
}

output "artifact_registry_repo" {
  description = "Docker repo to push the app image to."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.app.repository_id}"
}

output "runtime_service_account" {
  description = "Cloud Run runtime SA (grant BigQuery read on the source dataset if not project-wide)."
  value       = google_service_account.run.email
}

output "daily_run_scheduler_job" {
  description = "Cloud Scheduler job that POSTs the nightly validation run to /api/run."
  value       = google_cloud_scheduler_job.daily_run.name
}
