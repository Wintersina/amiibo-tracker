@echo off
setlocal

set PROJECT_ID=%1
set REGION=%2
set DJANGO_SECRET_KEY=%3
set OAUTH_REDIRECT_URI=%4
set ALLOWED_HOSTS=%5
set AUTO_APPROVE_FLAG=%6

if "%PROJECT_ID%"=="" goto usage
if "%REGION%"=="" goto usage
if "%DJANGO_SECRET_KEY%"=="" goto usage
if "%OAUTH_REDIRECT_URI%"=="" goto usage

set PS_ARGS=-ProjectId "%PROJECT_ID%" -Region "%REGION%" -DjangoSecretKey "%DJANGO_SECRET_KEY%" -OAuthRedirectUri "%OAUTH_REDIRECT_URI%"

if not "%ALLOWED_HOSTS%"=="" set PS_ARGS=%PS_ARGS% -AllowedHosts "%ALLOWED_HOSTS%"
if /I "%AUTO_APPROVE_FLAG%"=="AUTO" set PS_ARGS=%PS_ARGS% -AutoApprove

powershell -ExecutionPolicy Bypass -File "%~dp0windows_terraform.ps1" %PS_ARGS%
goto end

:usage
echo Usage: %~n0 PROJECT_ID REGION DJANGO_SECRET_KEY OAUTH_REDIRECT_URI [ALLOWED_HOSTS_COMMA_SEPARATED] [AUTO]

echo. 
:description
echo PROJECT_ID            GCP project ID

echo REGION                GCP region

echo DJANGO_SECRET_KEY     Django secret key value

echo OAUTH_REDIRECT_URI    OAuth redirect URI for your app

echo ALLOWED_HOSTS...      Optional comma-separated allowed hosts

echo AUTO                  Include the literal word AUTO to auto-approve Terraform apply

:end
endlocal
