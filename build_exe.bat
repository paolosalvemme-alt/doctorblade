@echo off
setlocal

set "PYTHON_CMD=python"
%PYTHON_CMD% --version >nul 2>&1
if errorlevel 1 (
    set "PYTHON_CMD=py -3"
    py -3 --version >nul 2>&1
    if errorlevel 1 (
        echo Python 3 was not found. Install Python 3 and enable "Add python.exe to PATH".
        exit /b 1
    )
)

echo Installing or updating Python dependencies...
%PYTHON_CMD% -m pip install -r requirements.txt
if errorlevel 1 (
    echo Dependency installation failed.
    exit /b 1
)

echo Running tests...
%PYTHON_CMD% -m pytest -p no:cacheprovider
if errorlevel 1 (
    echo Tests failed. Build stopped.
    exit /b 1
)

echo Building Windows executable...
%PYTHON_CMD% -m PyInstaller --noconfirm --onefile --windowed --name DoctorBladeControllerV305 main.py
if errorlevel 1 (
    echo PyInstaller build failed.
    exit /b 1
)

echo Build complete: dist\DoctorBladeControllerV305.exe
