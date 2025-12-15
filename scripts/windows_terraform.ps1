Param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,

    [Parameter(Mandatory = $true)]
    [string]$Region,

    [Parameter(Mandatory = $true)]
    [string]$DjangoSecretKey,

    [Parameter(Mandatory = $true)]
    [string]$OAuthRedirectUri,

    [string]$RepositoryName = "amiibo-tracker",
    [string]$ImageName = "amiibo-tracker",
    [string]$SecretName = "amiibo-tracker-oauth-client",
    [string]$AllowedHosts = "",
    [switch]$AutoApprove
)

$ErrorActionPreference = "Stop"

$ImageUrl = "$Region-docker.pkg.dev/$ProjectId/$RepositoryName/$ImageName:latest"

# Normalize allowed hosts into an HCL list expression
if ([string]::IsNullOrWhiteSpace($AllowedHosts)) {
    $AllowedHostsHcl = "[]"
} else {
    $AllowedHostsList = $AllowedHosts.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" }
    $QuotedHosts = $AllowedHostsList | ForEach-Object { '"' + $_ + '"' }
    $AllowedHostsHcl = "[" + ($QuotedHosts -join ", ") + "]"
}

Write-Host "Setting gcloud project to $ProjectId..."
gcloud config set project $ProjectId | Out-Host

Push-Location (Join-Path $PSScriptRoot ".." "terraform")
try {
    Write-Host "Initializing Terraform..."
    terraform init | Out-Host

    $applyArgs = @(
        "-var=project_id=$ProjectId",
        "-var=region=$Region",
        "-var=image_url=$ImageUrl",
        "-var=django_secret_key=$DjangoSecretKey",
        "-var=allowed_hosts=$AllowedHostsHcl",
        "-var=oauth_redirect_uri=$OAuthRedirectUri",
        "-var=oauth_client_secret_secret=$SecretName"
    )

    if ($AutoApprove) {
        $applyArgs += "-auto-approve"
    }

    Write-Host "Applying Terraform configuration..."
    terraform apply @applyArgs | Out-Host
}
finally {
    Pop-Location
}

Write-Host "Terraform deployment script complete."
