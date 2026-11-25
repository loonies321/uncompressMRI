@echo off
rem Build a standalone Windows executable for users without Python.
rem Requires: python -m pip install -r requirements-dev.txt pyinstaller

python -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name uncompressMRI ^
    main.py

if errorlevel 1 (
    echo Build failed.
    exit /b 1
)

echo.
echo Done: dist\uncompressMRI.exe
