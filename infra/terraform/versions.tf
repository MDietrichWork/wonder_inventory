terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # Store state in a GCS bucket (encrypted, access-controlled) — NOT locally — because the DB
  # password / Jira token flow through state. Create the bucket once, then uncomment + re-init.
  # backend "gcs" {
  #   bucket = "wonder-dq-tfstate"
  #   prefix = "cloud-run"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
