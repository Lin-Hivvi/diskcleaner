@echo off
title DiskCleaner Builder
echo ============================================
echo    Windows Disk Cleaner - Build Script
echo ============================================
echo.

:: ---------- Check Python ----------
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found! Please install Python 3.8+ first.
    echo Download: https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [OK] Python:
python --version

:: ---------- Check/Install PyInstaller ----------
pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Installing PyInstaller...
    pip install pyinstaller
    if %errorlevel% neq 0 (
        echo [ERROR] PyInstaller install failed!
        pause
        exit /b 1
    )
) else (
    echo [OK] PyInstaller found
)

:: ---------- Generate icon if missing ----------
if not exist "icon.ico" (
    echo [INFO] icon.ico not found, generating default...
    if exist "generate_icon.py" (
        python generate_icon.py
        if %errorlevel% equ 0 (
            echo [OK] Default icon generated
        ) else (
            echo [WARN] Icon generation failed, building without icon
        )
    ) else (
        echo [WARN] generate_icon.py not found, building without icon
    )
)

:: ---------- Clean old builds ----------
echo [INFO] Cleaning old build artifacts...
if exist "dist" rmdir /s /q dist >nul 2>&1
if exist "build" rmdir /s /q build >nul 2>&1
if exist "*.spec" del /q *.spec >nul 2>&1

:: ---------- Run PyInstaller ----------
echo.
echo ============================================
echo    Building... (1-3 minutes)
echo ============================================
echo.

set ICON_FLAG=
if exist "icon.ico" set ICON_FLAG=--icon=icon.ico

pyinstaller --onefile --noconsole ^
    --name "DiskCleaner" ^
    --add-data "icon.ico;." ^
    --version-file "version_info.txt" ^
    --hidden-import "queue" ^
    --hidden-import "json" ^
    --hidden-import "ctypes" ^
    --hidden-import "glob" ^
    --hidden-import "threading" ^
    --hidden-import "datetime" ^
    --hidden-import "pathlib" ^
    --hidden-import "math" ^
    --clean ^
    --noconfirm ^
    %ICON_FLAG% ^
    disk_cleaner.py

:: ---------- Check build result ----------
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Build failed! Check error messages above.
    pause
    exit /b 1
)

:: ---------- Copy artifacts ----------
echo [INFO] Organizing output...
if exist "dist\DiskCleaner.exe" (
    if exist "icon.ico" (
        copy /Y "icon.ico" "dist\DiskCleaner.ico" >nul 2>&1
    )
)

:: ---------- Success ----------
echo.
echo ============================================
echo    [BUILD SUCCESS]
echo ============================================
echo.
echo    Output: %CD%\dist\DiskCleaner.exe
for %%I in ("dist\DiskCleaner.exe") do echo    Size: %%~zI bytes
echo.
echo    Usage:
echo    1. Double-click dist\DiskCleaner.exe
echo    2. No Python required
echo    3. Works on Windows 10 / 11 (64-bit)
echo.
pause
