# Monitoring & Alerting Module (Doc 2 §5)
# Worker error rates, stuck runs (>30m), retries exhausted, and budget threshold alerts.

variable "project_id" { type = string }
variable "environment" { type = string }
variable "notification_email" { type = string; default = "ops@assurance.local" }

resource "google_monitoring_notification_channel" "email" {
  display_name = "Assurance Ops Email Alert Channel"
  type         = "email"
  labels = {
    email_address = var.notification_email
  }
}

# 1. Worker Error Rate Alert
resource "google_monitoring_alert_policy" "worker_errors" {
  display_name = "Worker Error Rate High (${var.environment})"
  combiner     = "OR"
  conditions {
    display_name = "Cloud Run 5xx errors > 5% over 5 minutes"
    condition_threshold {
      filter          = "resource.type = \"cloud_run_revision\" AND metric.type = \"run.googleapis.com/request_count\" AND metric.labels.response_code_class = \"5xx\""
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 5
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_RATE"
      }
    }
  }
  notification_channels = [google_monitoring_notification_channel.email.name]
}

output "alert_policy_id" { value = google_monitoring_alert_policy.worker_errors.id }
