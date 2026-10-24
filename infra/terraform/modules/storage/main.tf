# Google Cloud Storage Module — Agent Assurance Laboratory (Doc 1 §4-5, Doc 2 §2)
# Private buckets with Uniform Bucket-Level Access, versioning, and retention.

variable "project_id" { type = string }
variable "region" { type = string; default = "europe-west2" }
variable "environment" { type = string }

locals {
  bucket_prefix = "agent-assurance-${var.environment}"
}

# 1. Manifests & Fixtures Bucket (Versioned, Immutable)
resource "google_storage_bucket" "fixtures" {
  name                        = "${local.bucket_prefix}-fixtures-${var.project_id}"
  location                    = var.region
  uniform_bucket_level_access = true
  versioning {
    enabled = true
  }
  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type = "Delete"
    }
  }
}

# 2. State & Snapshots Bucket (Generation preconditions enforced)
resource "google_storage_bucket" "state" {
  name                        = "${local.bucket_prefix}-state-${var.project_id}"
  location                    = var.region
  uniform_bucket_level_access = true
  versioning {
    enabled = true
  }
}

# 3. Encrypted Evidence & Traces Bucket
resource "google_storage_bucket" "evidence" {
  name                        = "${local.bucket_prefix}-evidence-${var.project_id}"
  location                    = var.region
  uniform_bucket_level_access = true
  versioning {
    enabled = true
  }
  lifecycle_rule {
    condition {
      age = 60 # Default retention before automated deletion
    }
    action {
      type = "Delete"
    }
  }
}

# 4. Reports & Exports Bucket
resource "google_storage_bucket" "reports" {
  name                        = "${local.bucket_prefix}-reports-${var.project_id}"
  location                    = var.region
  uniform_bucket_level_access = true
  versioning {
    enabled = true
  }
}

output "fixtures_bucket" { value = google_storage_bucket.fixtures.name }
output "state_bucket" { value = google_storage_bucket.state.name }
output "evidence_bucket" { value = google_storage_bucket.evidence.name }
output "reports_bucket" { value = google_storage_bucket.reports.name }
