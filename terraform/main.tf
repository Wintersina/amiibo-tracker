// main.tf
resource "google_project_service" "enabled" {
  for_each = toset([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "secretmanager.googleapis.com",
  ])
  project = var.project_id
  service = each.key
}

resource "google_service_account" "app_sa" {
  account_id   = "${var.service_name}-sa"
  display_name = "${var.service_name} service account"
}

resource "google_service_account" "cloud_run" {
  account_id   = "${var.service_name}-runner"
  display_name = "${var.service_name} Cloud Run runtime"
}

resource "google_project_iam_member" "artifact_registry_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.cloud_run.email}"
}

resource "google_artifact_registry_repository" "docker_repo" {
  location      = var.region
  repository_id = var.service_name
  description   = "Docker repo for Amiibo Tracker app"
  format        = "DOCKER"
}

resource "google_cloud_run_service" "amiibo_tracker" {
  name     = var.service_name
  location = var.region

  depends_on = [
    google_project_service.enabled,
    google_artifact_registry_repository.docker_repo,
    google_project_iam_member.artifact_registry_reader,
    google_project_iam_member.artifact_registry_reader_app_sa,
  ]


  template {
    spec {
      containers {
        image = var.image_url

        dynamic "env" {
          for_each = local.container_env
          content {
            name  = env.value.name
            value = env.value.value
          }
        }

        dynamic "env" {
          for_each = var.oauth_client_secret_secret != "" ? [1] : []
          content {
            name = "GOOGLE_OAUTH_CLIENT_SECRETS_DATA"
            value_from {
              secret_key_ref {
                name = var.oauth_client_secret_secret
                key  = "latest"
              }


            }
          }
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
  lifecycle {
    ignore_changes = [template[0].spec[0].containers[0].image]
  }
}

resource "google_cloud_run_service_iam_member" "public" {
  count    = var.allow_unauthenticated ? 1 : 0
  location = google_cloud_run_service.amiibo_tracker.location
  project  = var.project_id
  service  = google_cloud_run_service.amiibo_tracker.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}


resource "google_secret_manager_secret_iam_member" "oauth_client_secret_accessor" {
  project   = var.project_id
  secret_id = var.oauth_client_secret_secret
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app_sa.email}"
}

resource "google_project_iam_member" "artifact_registry_reader_app_sa" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.app_sa.email}"
}

