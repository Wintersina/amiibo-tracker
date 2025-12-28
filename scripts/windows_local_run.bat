@echo off
setlocal

set "PROJECT_ROOT="
set "CURRENT_DIR=%CD%"

:find_root
if exist "%CURRENT_DIR%\manage.py" (
    set "PROJECT_ROOT=%CURRENT_DIR%"
    goto :found
)

if "%CURRENT_DIR%" == "%CURRENT_DIR:~0,3%" (
    echo Error: manage.py not found in current or parent directories.
    exit /b 1
)

set "CURRENT_DIR=%CURRENT_DIR%\.."
for %%i in ("%CURRENT_DIR%") do set "CURRENT_DIR=%%~fsi"
goto :find_root

:found
echo Found Django project root: %PROJECT_ROOT%
pushd "%PROJECT_ROOT%"

set "OAUTHLIB_INSECURE_TRANSPORT=1"

echo.
echo Running migrations...
python manage.py migrate

echo.
echo Running server...
python manage.py runserver

popd
endlocal