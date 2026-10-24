# BigQuery Module — Agent Assurance Laboratory (Doc 1 §4-5, Doc 2 §2)
# Append-only analytical and audit dataset. NOT an OLTP database.

variable "project_id" { type = string }
variable "location" { type = string; default = "EU" }
variable "environment" { type = string }

resource "google_bigquery_dataset" "assurance" {
  dataset_id                  = "agent_assurance_${var.environment}"
  friendly_name               = "Agent Assurance Events & Findings (${var.environment})"
  description                 = "Append-only execution facts, findings, and usage records."
  location                    = var.location
  default_table_expiration_ms = null # Retained for auditable compliance
}

# 1. Runs Table (Append-only)
resource "google_bigquery_table" "runs" {
  dataset_id = google_bigquery_dataset.assurance.dataset_id
  table_id   = "runs"

  time_partitioning {
    type  = "DAY"
    field = "started_at"
  }

  clustering = ["tenant_id", "assessment_id", "status"]

  schema = jsonencode([
    { name = "run_id", type = "STRING", mode = "REQUIRED" },
    { name = "tenant_id", type = "STRING", mode = "REQUIRED" },
    { name = "assessment_id", type = "STRING", mode = "REQUIRED" },
    { name = "agent_id", type = "STRING", mode = "REQUIRED" },
    { name = "scenario_pack", type = "STRING", mode = "NULLABLE" },
    { name = "status", type = "STRING", mode = "REQUIRED" },
    { name = "correlation_id", type = "STRING", mode = "NULLABLE" },
    { name = "started_at", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "ended_at", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "summary", type = "JSON", mode = "NULLABLE" }
  ])
}

# 2. Scenario Results Table (Append-only)
resource "google_bigquery_table" "scenario_results" {
  dataset_id = google_bigquery_dataset.assurance.dataset_id
  table_id   = "scenario_results"

  time_partitioning {
    type = "DAY"
  }

  clustering = ["tenant_id", "run_id", "verdict"]

  schema = jsonencode([
    { name = "run_id", type = "STRING", mode = "REQUIRED" },
    { name = "tenant_id", type = "STRING", mode = "REQUIRED" },
    { name = "scenario_id", type = "STRING", mode = "REQUIRED" },
    { name = "verdict", type = "STRING", mode = "REQUIRED" },
    { name = "summary", type = "STRING", mode = "NULLABLE" },
    { name = "evidence_complete", type = "BOOLEAN", mode = "REQUIRED" },
    { name = "checks_passed", type = "STRING", mode = "REPEATED" },
    { name = "checks_failed", type = "STRING", mode = "REPEATED" },
    { name = "checks_inconclusive", type = "STRING", mode = "REPEATED" },
    { name = "created_at", type = "TIMESTAMP", mode = "REQUIRED" }
  ])
}

# 3. Findings & Review Events Table (Append-only)
resource "google_bigquery_table" "findings" {
  dataset_id = google_bigquery_dataset.assurance.dataset_id
  table_id   = "findings"

  time_partitioning {
    type = "DAY"
  }

  clustering = ["tenant_id", "severity", "status"]

  schema = jsonencode([
    { name = "finding_id", type = "STRING", mode = "REQUIRED" },
    { name = "tenant_id", type = "STRING", mode = "REQUIRED" },
    { name = "run_id", type = "STRING", mode = "REQUIRED" },
    { name = "scenario_id", type = "STRING", mode = "REQUIRED" },
    { name = "severity", type = "STRING", mode = "REQUIRED" },
    { name = "title", type = "STRING", mode = "REQUIRED" },
    { name = "automated_verdict", type = "STRING", mode = "REQUIRED" },
    { name = "status", type = "STRING", mode = "REQUIRED" },
    { name = "created_at", type = "TIMESTAMP", mode = "REQUIRED" }
  ])
}

# 4. Usage & Metering Table (Append-only)
resource "google_bigquery_table" "usage_events" {
  dataset_id = google_bigquery_dataset.assurance.dataset_id
  table_id   = "usage_events"

  time_partitioning {
    type  = "DAY"
    field = "event_time"
  }

  clustering = ["tenant_id", "run_id"]

  schema = jsonencode([
    { name = "event_id", type = "STRING", mode = "REQUIRED" },
    { name = "tenant_id", type = "STRING", mode = "REQUIRED" },
    { name = "run_id", type = "STRING", mode = "REQUIRED" },
    { name = "scenario_count", type = "INTEGER", mode = "REQUIRED" },
    { name = "compute_tokens", type = "INTEGER", mode = "REQUIRED" },
    { name = "billable_units", type = "INTEGER", mode = "REQUIRED" },
    { name = "event_time", type = "TIMESTAMP", mode = "REQUIRED" }
  ])
}

output "dataset_id" { value = google_bigquery_dataset.assurance.dataset_id }
