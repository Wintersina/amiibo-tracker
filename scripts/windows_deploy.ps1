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

$ImageTag = "$Region-docker.pkg.dev/$ProjectId/$RepositoryName/$ImageName:latest"

Write-Host "Setting gcloud project to $ProjectId..."
gcloud config set project $ProjectId | Out-Host

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
