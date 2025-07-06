output "cloud_run_url" {
  description = "The URL of the deployed Cloud Run service"
  value = google_cloud_run_service.amiibo_tracker.status[0].url
}

output "service_account_email" {
  description = "Service account used by Cloud Run"
  value       = google_service_account.cloud_run.email
}

output "artifact_registry_repo" {
  description = "Artifact Registry Docker repo"
  value       = google_artifact_registry_repository.docker_repo.repository_id
}
