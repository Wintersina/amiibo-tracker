@echo off
setlocal

set REGION=%1
set PROJECT_ID=%2
set SECRET_FILE=%3

if "%REGION%"=="" goto usage
if "%PROJECT_ID%"=="" goto usage
if "%SECRET_FILE%"=="" goto usage

powershell -ExecutionPolicy Bypass -File "%~dp0windows_deploy.ps1" -Region "%REGION%" -ProjectId "%PROJECT_ID%" -SecretFile "%SECRET_FILE%"
goto end

:usage
echo Usage: %~n0 REGION PROJECT_ID PATH_TO_CLIENT_SECRET_JSON

:end
endlocal
