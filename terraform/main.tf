resource "google_project_service" "enabled" {
  for_each = toset([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "secretmanager.googleapis.com",
    "cloudscheduler.googleapis.com",
    "storage.googleapis.com",
    "iam.googleapis.com",
    "firestore.googleapis.com",
    "billingbudgets.googleapis.com",
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
    google_secret_manager_secret_iam_member.oauth_client_secret_accessor,
    google_secret_manager_secret_iam_member.loki_api_key_accessor,
    google_secret_manager_secret_iam_member.loki_hash_salt_accessor,
    google_secret_manager_secret_iam_member.gmail_smtp_password_accessor,
    google_secret_manager_secret_iam_member.ebay_client_secret_accessor,
    google_firestore_database.default,
    google_project_iam_member.firestore_user_app_sa,
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

        dynamic "env" {
          for_each = var.loki_api_key_secret != "" ? [1] : []

          content {
            name = "LOKI_API_KEY"

            value_from {
              secret_key_ref {
                name = var.loki_api_key_secret
                key  = "latest"
              }
            }
          }
        }

        dynamic "env" {
          for_each = var.loki_hash_salt_secret != "" ? [1] : []

          content {
            name = "LOKI_HASH_SALT"

            value_from {
              secret_key_ref {
                name = var.loki_hash_salt_secret
                key  = "latest"
              }
            }
          }
        }

        dynamic "env" {
          for_each = var.gmail_smtp_password_secret != "" ? [1] : []

          content {
            name = "EMAIL_HOST_PASSWORD"

            value_from {
              secret_key_ref {
                name = var.gmail_smtp_password_secret
                key  = "latest"
              }
            }
          }
        }

        dynamic "env" {
          for_each = var.ebay_client_secret_secret != "" ? [1] : []

          content {
            name = "EBAY_CLIENT_SECRET"

            value_from {
              secret_key_ref {
                name = var.ebay_client_secret_secret
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

  # The container image is deployed out-of-band by the build pipeline
  # (gcloud run services update in build.yml). Terraform must not revert it
  # back to the value pinned in terraform.tfvars on every apply.
  lifecycle {
    ignore_changes = [
      template[0].spec[0].containers[0].image,
    ]
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
  count = var.oauth_client_secret_secret != "" ? 1 : 0

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

resource "google_secret_manager_secret_iam_member" "loki_api_key_accessor" {
  count = var.loki_api_key_secret != "" ? 1 : 0

  project   = var.project_id
  secret_id = var.loki_api_key_secret
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app_sa.email}"
}

resource "google_secret_manager_secret_iam_member" "loki_hash_salt_accessor" {
  count = var.loki_hash_salt_secret != "" ? 1 : 0

  project   = var.project_id
  secret_id = var.loki_hash_salt_secret
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app_sa.email}"
}

resource "google_secret_manager_secret_iam_member" "gmail_smtp_password_accessor" {
  count = var.gmail_smtp_password_secret != "" ? 1 : 0

  project   = var.project_id
  secret_id = var.gmail_smtp_password_secret
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app_sa.email}"
}

resource "google_secret_manager_secret_iam_member" "ebay_client_secret_accessor" {
  count = var.ebay_client_secret_secret != "" ? 1 : 0

  project   = var.project_id
  secret_id = var.ebay_client_secret_secret
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app_sa.email}"
}

# ---------------------------------------------------------------------------
# Firestore: amiibo page comments
# ---------------------------------------------------------------------------

resource "google_firestore_database" "default" {
  project     = var.project_id
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  depends_on = [google_project_service.enabled]
}

resource "google_project_iam_member" "firestore_user_app_sa" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.app_sa.email}"
}

resource "google_billing_budget" "monthly_cap" {
  count = var.billing_account_id != "" ? 1 : 0

  billing_account = var.billing_account_id
  display_name    = "${var.service_name} monthly budget"

  budget_filter {
    projects = ["projects/${var.project_id}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(var.monthly_budget_usd)
    }
  }

  threshold_rules {
    threshold_percent = 0.5
  }

  threshold_rules {
    threshold_percent = 0.9
  }

  threshold_rules {
    threshold_percent = 1.0
  }

  depends_on = [google_project_service.enabled]
}

resource "google_firestore_index" "amiibo_comments_by_amiibo" {
  project    = var.project_id
  database   = google_firestore_database.default.name
  collection = "amiibo_comments"

  fields {
    field_path = "amiibo_id"
    order      = "ASCENDING"
  }

  fields {
    field_path = "is_hidden"
    order      = "ASCENDING"
  }

  fields {
    field_path = "created_at"
    order      = "DESCENDING"
  }
}

resource "google_firestore_index" "blog_comments_by_slug" {
  project    = var.project_id
  database   = google_firestore_database.default.name
  collection = "blog_comments"

  fields {
    field_path = "slug"
    order      = "ASCENDING"
  }

  fields {
    field_path = "is_hidden"
    order      = "ASCENDING"
  }

  fields {
    field_path = "created_at"
    order      = "DESCENDING"
  }
}

# ---------------------------------------------------------------------------
# Daily DAU report: GCS archive bucket + Cloud Scheduler trigger
# ---------------------------------------------------------------------------

resource "google_storage_bucket" "dau_reports" {
  name                        = var.gcs_reports_bucket
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false

  lifecycle_rule {
    condition {
      age = 730
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.enabled]
}

resource "google_storage_bucket_iam_member" "dau_reports_writer" {
  bucket = google_storage_bucket.dau_reports.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.app_sa.email}"
}

resource "google_service_account" "scheduler_sa" {
  account_id   = "${var.service_name}-scheduler"
  display_name = "${var.service_name} Cloud Scheduler invoker"
}

resource "google_cloud_run_service_iam_member" "scheduler_invoker" {
  location = google_cloud_run_service.amiibo_tracker.location
  project  = var.project_id
  service  = google_cloud_run_service.amiibo_tracker.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler_sa.email}"
}

resource "google_cloud_scheduler_job" "daily_report" {
  name        = "${var.service_name}-daily-report"
  description = "Triggers the prior-day DAU report email and GCS archive"
  schedule    = var.daily_report_cron_schedule
  time_zone   = var.daily_report_time_zone
  region      = var.region

  retry_config {
    retry_count          = 3
    min_backoff_duration = "60s"
    max_backoff_duration = "600s"
  }

  http_target {
    http_method = "POST"
    uri         = "${google_cloud_run_service.amiibo_tracker.status[0].url}/internal/run-daily-report"

    headers = {
      "Content-Type" = "application/json"
    }

    body = base64encode("{}")

    oidc_token {
      service_account_email = google_service_account.scheduler_sa.email
      audience              = google_cloud_run_service.amiibo_tracker.status[0].url
    }
  }

  depends_on = [
    google_project_service.enabled,
    google_cloud_run_service_iam_member.scheduler_invoker,
  ]
}

resource "google_cloud_scheduler_job" "price_refresh" {
  name        = "${var.service_name}-price-refresh"
  description = "Refreshes AmiiboDex eBay price estimates and six-month snapshots"
  schedule    = var.price_refresh_cron_schedule
  time_zone   = var.daily_report_time_zone
  region      = var.region

  retry_config {
    retry_count          = 3
    min_backoff_duration = "60s"
    max_backoff_duration = "600s"
  }

  http_target {
    http_method = "POST"
    uri         = "${google_cloud_run_service.amiibo_tracker.status[0].url}/internal/refresh-prices"

    headers = {
      "Content-Type" = "application/json"
    }

    body = base64encode("{}")

    oidc_token {
      service_account_email = google_service_account.scheduler_sa.email
      audience              = google_cloud_run_service.amiibo_tracker.status[0].url
    }
  }

  depends_on = [
    google_project_service.enabled,
    google_cloud_run_service_iam_member.scheduler_invoker,
  ]
}
