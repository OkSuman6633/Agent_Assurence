# IAM & Service Accounts Module (Doc 1 §5, Doc 2 §2, §4)
# Least-privilege principle: separate identities for API and Worker; no broad service accounts.

variable "project_id" { type = string }
variable "environment" { type = string }
variable "github_repo" { type = string; default = "oksum/Agent_Assurence_Lab" }

# 1. API Service Account
resource "google_service_account" "api" {
  account_id   = "assurance-api-${var.environment}"
  display_name = "Agent Assurance API Service Account (${var.environment})"
}

# 2. Worker Service Account
resource "google_service_account" "worker" {
  account_id   = "assurance-worker-${var.environment}"
  display_name = "Agent Assurance Worker Service Account (${var.environment})"
}

# 3. Workload Identity Pool for GitHub Actions (Doc 2 §2, §3)
resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github-actions-${var.environment}"
  display_name              = "GitHub Actions WIF Pool"
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-provider"
  display_name                       = "GitHub Actions Provider"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.actor"      = "assertion.actor"
    "attribute.repository" = "assertion.repository"
  }

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

output "api_service_account_email" { value = google_service_account.api.email }
output "worker_service_account_email" { value = google_service_account.worker.email }
output "workload_identity_pool_name" { value = google_iam_workload_identity_pool.github.name }
