// provider.tf
terraform {
  required_version = ">= 1.15.7"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "7.38.0"
    }
  }
}

provider "google" {
  project               = var.project_id
  region                = var.region
  user_project_override = true
  billing_project       = var.project_id
}
