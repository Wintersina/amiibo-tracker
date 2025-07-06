// main.tf
provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_service_account" "app_sa" {
  account_id   = "amiibo-app-sa"
  display_name = "Amiibo App Service Account"
}

resource "google_service_account" "cloud_run" {
  account_id   = "cloud-run-sa"
  display_name = "Cloud Run Service Account"
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
      service_account_name = google_service_account.app_sa.email

      containers {
        # This can remain commented during initial provisioning
        # image = var.image_url

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
    }
  }

  traffic {
    percent         = 100
    latest_revision = true
  }

  lifecycle {
    ignore_changes = [template]
  }
}


resource "google_cloud_run_service_iam_member" "invoker" {
  service  = google_cloud_run_service.amiibo_tracker.name
  location = google_cloud_run_service.amiibo_tracker.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_project_iam_member" "artifact_registry_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.app_sa.email}"
}
