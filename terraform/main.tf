// main.tf
provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_artifact_registry_repository" "docker_repo" {
  location      = var.region
  repository_id = "amiibo-tracker"
  description   = "Docker repo for Amiibo Tracker app"
  format        = "DOCKER"
}

resource "google_cloud_run_service" "amiibo_tracker" {
  name     = "amiibo-tracker"
  location = var.region

  template {
    spec {
      containers {
        image = var.image_url

        env {
          name  = "DJANGO_SECRET_KEY"
          value = var.django_secret_key
        }
        env {
          name  = "GOOGLE_CLIENT_ID"
          value = var.google_client_id
        }
        env {
          name  = "GOOGLE_CLIENT_SECRET"
          value = var.google_client_secret
        }
      }
      service_account_name = google_service_account.app_sa.email
    }
  }

  traffic {
    percent         = 100
    latest_revision = true
  }

  autogenerate_revision_name = true
}

resource "google_cloud_run_service_iam_member" "invoker" {
  service  = google_cloud_run_service.amiibo_tracker.name
  location = google_cloud_run_service.amiibo_tracker.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}
