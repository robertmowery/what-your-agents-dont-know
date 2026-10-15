output "service_url" {
  description = "The context server's URL. The MCP endpoint is this plus /mcp. Read by run_part3.py; never written to results."
  value       = var.image == "" ? "" : google_cloud_run_v2_service.contract[0].uri
}

output "callers" {
  description = "The service account each agent configuration calls the contract under."
  value       = { for name, account in google_service_account.caller : name => account.email }
}

output "image_repository" {
  description = "Where the build pushes the image."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "build_staging_bucket" {
  description = "Where the build's source is staged."
  value       = google_storage_bucket.build_staging.name
}

output "builder" {
  description = "The service account the image build runs as."
  value       = google_service_account.builder.id
}
