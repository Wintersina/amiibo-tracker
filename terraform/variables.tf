variable "project_id" {
  description = "The ID of the GCP project"
  type        = string
}

variable "region" {
  description = "The GCP region to deploy resources"
  type        = string
  default     = "us-central1"
}

variable "image_url" {
  description = "The URL of the Docker image to deploy"
  type        = string
}

# variable "django_secret_key" {
#   description = "Django secret key"
#   type        = string
#   sensitive   = true
# }

# variable "google_client_id" {
#   description = "OAuth client ID"
#   type        = string
#   sensitive   = true
# }

# variable "google_client_secret" {
#   description = "OAuth client secret"
#   type        = string
#   sensitive   = true
# }
