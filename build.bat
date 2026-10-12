@echo off
echo ========================================================
echo Building ESP32 Firmware with PlatformIO...
echo ========================================================
"%USERPROFILE%\.platformio\penv\Scripts\pio.exe" run
if %ERRORLEVEL% equ 0 (
    echo.
    echo [SUCCESS] Firmware compiled cleanly!
    echo Firmware binary ready at: .pio\build\esp32dev\firmware.bin
) else (
    echo.
    echo [ERROR] Build failed! Check compiler errors above.
)
