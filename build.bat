@echo off
setlocal
echo ========================================================
echo Building ESP32 Firmware with PlatformIO...
echo ========================================================

where pio >nul 2>nul
if %ERRORLEVEL% equ 0 (
    pio run
) else if exist "%USERPROFILE%\.platformio\penv\Scripts\pio.exe" (
    "%USERPROFILE%\.platformio\penv\Scripts\pio.exe" run
) else (
    python -m platformio run
)

if %ERRORLEVEL% equ 0 (
    echo.
    echo [SUCCESS] Firmware compiled cleanly!
    echo Firmware binary ready at: .pio\build\esp32dev\firmware.bin
) else (
    echo.
    echo [ERROR] Build failed! Check compiler errors above.
)
