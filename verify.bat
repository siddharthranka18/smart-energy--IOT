@echo off
setlocal enabledelayedexpansion
echo ========================================================
echo Running Automated Logic Verification Suite (Phase 1 + 2 + 3)
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
echo [Phase 3] Compiling and running power, energy, and alert tests...
%GPP% -std=c++11 test\verify_phase3_logic.cpp -o test\verify_phase3_logic.exe
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Failed to compile test\verify_phase3_logic.cpp
    exit /b 1
)
test\verify_phase3_logic.exe
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Phase 3 C++ tests failed!
    exit /b 1
)

echo.
echo [Phase 3] Running telemetry ingestion validation tests...
python --version >nul 2>nul
if %ERRORLEVEL% equ 0 (
    python -m unittest -v test.test_phase3_ingestion
) else (
    py -3 -m unittest -v test.test_phase3_ingestion
)
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Phase 3 Python tests failed!
    exit /b 1
)

echo.
echo [ALL PASS] All Phase 1, Phase 2, and Phase 3 tests passed cleanly!
exit /b 0
