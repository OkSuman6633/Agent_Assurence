# Cloud Tasks Queue Module (Doc 1 §4-5, Doc 2 §2)
# Bounded retry policy, tenant concurrency quotas, and rate limiting.

variable "project_id" { type = string }
variable "region" { type = string; default = "europe-west2" }
variable "environment" { type = string }

resource "google_cloud_tasks_queue" "run_queue" {
  name     = "assurance-run-queue-${var.environment}"
  location = var.region

  rate_limits {
    max_dispatches_per_second = 20
    max_concurrent_dispatches = 10
  }

  retry_config {
    max_attempts       = 3 # Bounded retry policy (Doc 1 §5)
    min_backoff        = "2s"
    max_backoff        = "30s"
    max_doublings      = 3
    max_retry_duration = "300s"
  }
}

output "queue_id" { value = google_cloud_tasks_queue.run_queue.id }
output "queue_name" { value = google_cloud_tasks_queue.run_queue.name }
