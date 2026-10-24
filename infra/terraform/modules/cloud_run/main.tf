# Cloud Run Services Module — assurance-web and assurance-worker (Doc 1 §4-5, Doc 2 §2)

variable "project_id" { type = string }
variable "region" { type = string; default = "europe-west2" }
variable "environment" { type = string }
variable "image_digest" { type = string }
variable "api_service_account" { type = string }
variable "worker_service_account" { type = string }

# 1. API Service (assurance-web)
resource "google_cloud_run_v2_service" "api" {
  name     = "assurance-web-${var.environment}"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = var.api_service_account
    scaling {
      min_instance_count = 0
      max_instance_count = var.environment == "prod" ? 10 : 3
    }

    containers {
      image = var.image_digest

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
      }

      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }
      env {
        name  = "AUTH_DISABLED"
        value = var.environment == "prod" ? "false" : "true"
      }

      startup_probe {
        http_get {
          path = "/health"
          port = 8000
        }
        initial_delay_seconds = 2
        period_seconds        = 5
      }

      liveness_probe {
        http_get {
          path = "/health"
          port = 8000
        }
        period_seconds = 15
      }
    }
  }
}

# 2. Worker Service (assurance-worker, private ingress)
resource "google_cloud_run_v2_service" "worker" {
  name     = "assurance-worker-${var.environment}"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_INTERNAL_ONLY"

  template {
    service_account = var.worker_service_account
    scaling {
      min_instance_count = 0
      max_instance_count = var.environment == "prod" ? 20 : 5
    }

    containers {
      image = var.image_digest

      resources {
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
      }

      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }
      env {
        name  = "ROLE"
        value = "worker"
      }
    }
  }
}

output "api_url" { value = google_cloud_run_v2_service.api.uri }
output "worker_url" { value = google_cloud_run_v2_service.worker.uri }
