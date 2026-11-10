@echo off
setlocal enabledelayedexpansion
echo ========================================================
echo Running Automated Logic Verification Suite (Phase 1 + 2)
echo ========================================================

where g++ >nul 2>nul
if %ERRORLEVEL% equ 0 (
    set GPP=g++
) else if exist "C:\MinGW\bin\g++.exe" (
    set GPP=C:\MinGW\bin\g++.exe
) else (
    echo [ERROR] g++ compiler not found!
    exit /b 1
)

echo.
echo [Phase 1] Compiling and running Phase 1 logic tests...
%GPP% -std=c++11 test\verify_logic.cpp -o test\verify_logic.exe
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Failed to compile test\verify_logic.cpp
    exit /b 1
)
test\verify_logic.exe
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Phase 1 tests failed!
    exit /b 1
)

echo.
echo [Phase 2] Compiling and running Phase 2 command and override tests...
%GPP% -std=c++11 -I .pio\libdeps\esp32dev\ArduinoJson\src test\verify_phase2_logic.cpp -o test\verify_phase2_logic.exe
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Failed to compile test\verify_phase2_logic.cpp
    exit /b 1
)
test\verify_phase2_logic.exe
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Phase 2 tests failed!
    exit /b 1
)

echo.
echo [ALL PASS] All Phase 1 and Phase 2 tests passed cleanly!
