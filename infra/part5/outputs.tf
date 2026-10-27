output "results_bucket" {
  description = "Where each execution writes its records, traces and alert. Read back by run_part5.py --pull."
  value       = google_storage_bucket.results.name
}

output "job_name" {
  description = "The Cloud Run job to execute."
  value       = var.image == "" ? "" : google_cloud_run_v2_job.check[0].name
}

output "check_account" {
  description = "The job's service account."
  value       = google_service_account.check.email
}

output "schedule_paused" {
  description = "Whether the nightly schedule is paused."
  value       = var.image == "" ? null : google_cloud_scheduler_job.nightly[0].paused
}
