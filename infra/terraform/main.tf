# Root Terraform Configuration — Agent Assurance Laboratory (Doc 2 §2)

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }

  # In staging and production, state is stored in an encrypted GCS bucket:
  # backend "gcs" {
  #   bucket = "agent-assurance-terraform-state"
  #   prefix = "environments/prod"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# 1. IAM & Service Accounts
module "iam" {
  source      = "./modules/iam"
  project_id  = var.project_id
  environment = var.environment
}

# 2. Storage Buckets (GCS)
module "storage" {
  source      = "./modules/storage"
  project_id  = var.project_id
  region      = var.region
  environment = var.environment
}

# 3. BigQuery Analytical Datasets
module "bigquery" {
  source      = "./modules/bigquery"
  project_id  = var.project_id
  environment = var.environment
}

# 4. Cloud Tasks Queue
module "cloud_tasks" {
  source      = "./modules/cloud_tasks"
  project_id  = var.project_id
  region      = var.region
  environment = var.environment
}

# 5. Secret Manager
module "secret_manager" {
  source      = "./modules/secret_manager"
  project_id  = var.project_id
  environment = var.environment
}

# 6. Cloud Run (API & Worker)
module "cloud_run" {
  source                 = "./modules/cloud_run"
  project_id             = var.project_id
  region                 = var.region
  environment            = var.environment
  image_digest           = var.image_digest
  api_service_account    = module.iam.api_service_account_email
  worker_service_account = module.iam.worker_service_account_email
}

# 7. Monitoring & Alerting
module "monitoring" {
  source             = "./modules/monitoring"
  project_id         = var.project_id
  environment        = var.environment
  notification_email = var.alert_email
}
