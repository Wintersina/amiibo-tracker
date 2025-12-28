<#!
.SYNOPSIS
Builds and pushes the Docker image, then uploads the OAuth client secret.

.DESCRIPTION
This script is designed for Windows environments where gcloud is installed and
already authenticated. It builds the Docker image, pushes it to Artifact
Registry, ensures the repository exists, and uploads the OAuth client secret as
Secret Manager versions.

.PARAMETER Region
The GCP region, e.g., "us-east1".

.PARAMETER ProjectId
The GCP project ID.

.PARAMETER SecretFile
Path to the OAuth client secret JSON file.

.PARAMETER RepositoryName
Artifact Registry repository name. Defaults to "amiibo-tracker".

.PARAMETER ImageName
Container image name. Defaults to "amiibo-tracker".

.PARAMETER SecretName
Secret Manager secret name. Defaults to "amiibo-tracker-oauth-client".

.EXAMPLE
./scripts/windows_deploy.ps1 -Region "us-east1" -ProjectId "my-project" -SecretFile "./client_secret.json"
#>

Param(
    [Parameter(Mandatory = $true)]
    [string]$Region,

    [Parameter(Mandatory = $true)]
    [string]$ProjectId,

    [Parameter(Mandatory = $true)]
    [string]$SecretFile,

    [string]$RepositoryName = "amiibo-tracker",
    [string]$ImageName = "amiibo-tracker",
    [string]$SecretName = "amiibo-tracker-oauth-client"
)

$ErrorActionPreference = "Stop"

if (!(Test-Path $SecretFile)) {
    throw "Secret file '$SecretFile' not found."
}

if ([string]::IsNullOrWhiteSpace($RepositoryName)) {
    throw "RepositoryName cannot be empty."
}

if ([string]::IsNullOrWhiteSpace($ImageName)) {
    throw "ImageName cannot be empty."
}

$RepositoryName = $RepositoryName.Trim().Trim("/")
$ImageName = $ImageName.Trim().Trim("/")
$ImageTag = "$Region-docker.pkg.dev/$ProjectId/$RepositoryName/$ImageName:latest"

Write-Host "Setting gcloud project to $ProjectId..."
gcloud config set project $ProjectId | Out-Host

Write-Host "Ensuring Artifact Registry repository '$RepositoryName' exists..."
if (gcloud artifacts repositories describe "$RepositoryName" --location="$Region" --project "$ProjectId" > $null 2>&1) {
    Write-Host "Repository already exists."
} else {
    gcloud artifacts repositories create "$RepositoryName" `
        --location="$Region" `
        --repository-format=docker `
        --description="Docker repo for $ImageName" | Out-Host
}

Write-Host "Submitting Cloud Build for $ImageTag..."
gcloud builds submit --tag $ImageTag | Out-Host

Write-Host "Ensuring secret '$SecretName' exists..."
if (gcloud secrets describe $SecretName --project $ProjectId > $null 2>&1) {
    Write-Host "Secret already exists."
} else {
    gcloud secrets create $SecretName --replication-policy="automatic" --project $ProjectId | Out-Host
}

Write-Host "Adding new secret version from $SecretFile..."
gcloud secrets versions add $SecretName --data-file=$SecretFile --project $ProjectId | Out-Host

Write-Host "Deployment script complete."
