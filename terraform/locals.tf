locals {
  // Normalize user-provided hosts by stripping protocols and trailing slashes to
  // keep Django's ALLOWED_HOSTS semantics intact. This avoids accidental
  // misconfigurations such as providing "https://example.com/" via the
  // ALLOWED_HOSTS_JSON secret.
  sanitized_allowed_hosts = [
    for host in var.allowed_hosts :
    trimsuffix(
      replace(replace(host, "https://", ""), "http://", ""),
      "/",
    )
  ]

  formatted_allowed_hosts = length(local.sanitized_allowed_hosts) > 0 ? local.sanitized_allowed_hosts : ["*"]
  csrf_trusted_origins    = [for host in local.formatted_allowed_hosts : "https://${host}" if host != "*"]

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
    },
    {
      name  = "CSRF_TRUSTED_ORIGINS"
      value = join(",", local.csrf_trusted_origins)
    },
    {
      name  = "LOKI_URL"
      value = var.loki_url
    },
    {
      name  = "LOKI_USER"
      value = var.loki_user
    },
    {
      name  = "DAILY_REPORT_TO_EMAIL"
      value = var.daily_report_to_email
    },
    {
      name  = "EMAIL_HOST_USER"
      value = var.gmail_smtp_user
    },
    {
      name  = "GCS_REPORTS_BUCKET"
      value = var.gcs_reports_bucket
    },
    {
      name  = "DAILY_REPORT_SCHEDULER_SA_EMAIL"
      value = "${var.service_name}-scheduler@${var.project_id}.iam.gserviceaccount.com"
    }
  ]
}
