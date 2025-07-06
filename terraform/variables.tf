variable "project_id" {
  description = "The ID of the GCP project"
  type        = string
}

variable "region" {
  description = "The GCP region to deploy resources"
  type        = string
  default     = "us-central1"
}

variable "app_name" {
  description = "The name of your Cloud Run app and related resources"
  type        = string
  default     = "amiibo-tracker"
}

variable "image_tag" {
  description = "Docker image tag to deploy"
  type        = string
  default     = "latest"
}

variable "env_secrets" {
  description = "A map of environment variables to be injected as secrets"
  type        = map(string)
  default     = {}
}


variable "image_url" {
  description = "Docker image URL"
  type        = string
}

variable "django_secret_key" {
  description = "Django secret key"
  type        = string
  sensitive   = true
}

variable "google_client_id" {
  description = "OAuth client ID"
  type        = string
  sensitive   = true
}

variable "google_client_secret" {
  description = "OAuth client secret"
  type        = string
  sensitive   = true
}
