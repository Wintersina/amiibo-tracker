<#!
.SYNOPSIS
Runs Terraform to provision the application infrastructure on GCP.

.DESCRIPTION
Initializes and applies the Terraform configuration using the latest image
published to Artifact Registry. Do not include square brackets when supplying
optional parameters.

.PARAMETER ProjectId
The GCP project ID.

.PARAMETER Region
The GCP region, e.g., "us-east1".

.PARAMETER DjangoSecretKey
The Django secret key value to inject.

.PARAMETER OAuthRedirectUri
Redirect URI configured for the OAuth client.

.PARAMETER RepositoryName
Artifact Registry repository name. Defaults to "amiibo-tracker".

.PARAMETER ImageName
Container image name. Defaults to "amiibo-tracker".

.PARAMETER SecretName
Secret Manager secret that holds the OAuth client secret. Defaults to
"amiibo-tracker-oauth-client".

.PARAMETER AllowedHosts
Optional comma-separated list of allowed hosts for Django.

.PARAMETER AutoApprove
Pass to auto-approve Terraform apply.

.EXAMPLE
./scripts/windows_terraform.ps1 -ProjectId "my-project" -Region "us-east1" -DjangoSecretKey "SECRET" -OAuthRedirectUri "https://your.app/oauth/callback" -AllowedHosts "example.com,localhost" -AutoApprove
#>

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

if ([string]::IsNullOrWhiteSpace($RepositoryName)) {
    throw "RepositoryName cannot be empty."
}

if ([string]::IsNullOrWhiteSpace($ImageName)) {
    throw "ImageName cannot be empty."
}

$RepositoryName = $RepositoryName.Trim().Trim("/")
$ImageName = $ImageName.Trim().Trim("/")
$ImageUrl = "$Region-docker.pkg.dev/$ProjectId/$RepositoryName/$ImageName:latest"

if (-not (Get-Command terraform -ErrorAction SilentlyContinue)) {
    throw "Terraform CLI is not available in PATH. Install Terraform or add it to PATH before running this script."
}

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
