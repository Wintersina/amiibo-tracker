locals {
  formatted_allowed_hosts = length(var.allowed_hosts) > 0 ? var.allowed_hosts : ["*"]

  container_env = [
    {
      name  = "ENV_NAME"
      value = "production"
    },
    {
      name  = "DJANGO_SECRET_KEY"
      value = var.django_secret_key
    },
    {
      name  = "ALLOWED_HOSTS"
      value = join(",", local.formatted_allowed_hosts)
    },
    {
      name  = "OAUTH_REDIRECT_URI"
      value = var.oauth_redirect_uri
    },
    {
      name  = "GOOGLE_OAUTH_CLIENT_SECRETS"
      value = var.client_secret_path
    }
  ]
}
