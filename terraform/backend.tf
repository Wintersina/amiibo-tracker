// backend.tf
terraform {
  backend "gcs" {
    bucket = "amiibo-tracker-458804_cloudbuild"
    prefix = "terraform/state"
  }
}
