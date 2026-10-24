# Secret Manager Module (Doc 1 §5, Doc 2 §2)
# Manages signing keys, adapter credentials, and external tokens with accessor policies.

variable "project_id" { type = string }
variable "environment" { type = string }

resource "google_secret_manager_secret" "signing_key" {
  secret_id = "assurance-signing-key-${var.environment}"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret" "test_credentials" {
  secret_id = "assurance-test-credentials-${var.environment}"

  replication {
    auto {}
  }
}

output "signing_key_id" { value = google_secret_manager_secret.signing_key.id }
output "test_credentials_id" { value = google_secret_manager_secret.test_credentials.id }
