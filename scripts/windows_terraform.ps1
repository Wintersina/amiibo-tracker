Param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,

    [Parameter(Mandatory = $true)]
    [string]$Region,

    [string]$StateBucket = $env:TF_STATE_BUCKET,

    [Parameter(Mandatory = $true)]
    [string]$DjangoSecretKey,

    [Parameter(Mandatory = $true)]
    [string]$OAuthRedirectUri,

    [string]$RepositoryName = "amiibo-tracker",
    [string]$ImageName = "amiibo-tracker",
    [string]$SecretName = "amiibo-tracker-oauth-client",

    [switch]$AutoApprove
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($StateBucket)) {
    throw "StateBucket is required. Pass -StateBucket or set env var TF_STATE_BUCKET."
}

$RepositoryName = $RepositoryName.Trim().Trim("/")
$ImageName = $ImageName.Trim().Trim("/")
$StateBucket = $StateBucket.Trim()

$ImageUrl = "$Region-docker.pkg.dev/$ProjectId/$RepositoryName/$((@($ImageName,$RepositoryName) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -First 1).Trim().Trim('/')):latest"
Write-Host "Using image: $ImageUrl"

Write-Host "Setting gcloud project to $ProjectId..."
gcloud config set project $ProjectId | Out-Host

Push-Location (Join-Path -Path $PSScriptRoot -ChildPath "..\terraform")
try {
    Write-Host "Initializing Terraform backend (bucket=$StateBucket)..."
    terraform init -reconfigure `
        -backend-config="bucket=$StateBucket" `
        -backend-config="prefix=terraform/state" | Out-Host

    $applyArgs = @(
        "-var", "project_id=$ProjectId",
        "-var", "region=$Region",
        "-var", "image_url=$ImageUrl",
        "-var", "django_secret_key=$DjangoSecretKey",
        "-var", "oauth_redirect_uri=$OAuthRedirectUri",
        "-var", "oauth_client_secret_secret=$SecretName"
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
