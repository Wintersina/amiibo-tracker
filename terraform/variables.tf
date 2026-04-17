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
  default     = [
    "goozamiibo.com",
    "www.goozamiibo.com",
    "amiibo-tracker-juiposodeq-ue.a.run.app",
  ]
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

variable "loki_url" {
  description = "Grafana Cloud Loki base URL (without /loki/api/v1/push suffix)"
  type        = string
  default     = ""
}

variable "loki_user" {
  description = "Grafana Cloud Loki basic-auth username (numeric stack id)"
  type        = string
  default     = ""
}

variable "loki_api_key_secret" {
  description = "Secret Manager secret id holding the Grafana Cloud API token"
  type        = string
  default     = ""
}

variable "loki_hash_salt_secret" {
  description = "Secret Manager secret id holding the salt used to hash user emails before shipping logs"
  type        = string
  default     = ""
}
