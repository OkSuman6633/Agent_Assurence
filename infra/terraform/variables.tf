variable "project_id" {
  description = "Google Cloud Project ID"
  type        = string
}

variable "region" {
  description = "Default Google Cloud deployment region"
  type        = string
  default     = "europe-west2"
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "image_digest" {
  description = "Immutable container image digest (e.g. gcr.io/my-project/assurance-web@sha256:...)"
  type        = string
  default     = "europe-west2-docker.pkg.dev/sample-project/assurance/assurance-app:v1.0.0"
}

variable "alert_email" {
  description = "Operational on-call alert email address"
  type        = string
  default     = "ops@assurance.local"
}
