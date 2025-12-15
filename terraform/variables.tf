variable "project_id" {
  description = "The ID of the GCP project"
  type        = string
}

variable "region" {
  description = "The GCP region to deploy resources"
  type        = string
  default     = "us-central1"
}

variable "service_name" {
  description = "Name for the Cloud Run service"
  type        = string
  default     = "amiibo-tracker"
}

variable "image_url" {
  description = "The URL of the Docker image to deploy"
  type        = string
}

variable "django_secret_key" {
  description = "Secret key for Django"
  type        = string
  sensitive   = true
}

variable "allowed_hosts" {
  description = "List of allowed hosts for Django"
  type        = list(string)
  default     = []
}

variable "oauth_redirect_uri" {
  description = "Redirect URI used for OAuth callbacks"
  type        = string
  default     = ""
}

variable "client_secret_path" {
  description = "Filesystem path where the OAuth client secret JSON is available inside the container"
  type        = string
  default     = "/secrets/client_secret.json"
}

variable "oauth_client_secret_secret" {
  description = "Optional existing Secret Manager secret that stores the OAuth client JSON (latest version is injected as an env var)"
  type        = string
  default     = ""
}

variable "allow_unauthenticated" {
  description = "Whether to allow unauthenticated access to Cloud Run"
  type        = bool
  default     = true
}
variable "app_name" {
  type    = string
  default = null
}

variable "env_secrets" {
  type    = map(string)
  default = {}
}
