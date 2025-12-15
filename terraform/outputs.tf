output "cloud_run_url" {
  description = "URL of the deployed Cloud Run service"
  value       = google_cloud_run_service.amiibo_tracker.status[0].url
}

output "artifact_registry_repo" {
  description = "Artifact Registry repository for container images"
  value       = google_artifact_registry_repository.docker_repo.repository_id
}
