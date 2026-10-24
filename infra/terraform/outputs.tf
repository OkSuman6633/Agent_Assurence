output "api_endpoint" {
  description = "Public URL for assurance-web Cloud Run service"
  value       = module.cloud_run.api_url
}

output "worker_endpoint" {
  description = "Internal URL for assurance-worker Cloud Run service"
  value       = module.cloud_run.worker_url
}

output "storage_buckets" {
  description = "Provisioned Cloud Storage buckets"
  value = {
    fixtures = module.storage.fixtures_bucket
    state    = module.storage.state_bucket
    evidence = module.storage.evidence_bucket
    reports  = module.storage.reports_bucket
  }
}

output "bigquery_dataset" {
  description = "Analytical BigQuery dataset"
  value       = module.bigquery.dataset_id
}

output "cloud_tasks_queue" {
  description = "Async task queue for runs"
  value       = module.cloud_tasks.queue_name
}
