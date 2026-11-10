@echo off
echo ========================================================
echo Running Automated Logic Verification Suite...
echo ========================================================
if not exist "test\verify_logic.exe" (
    echo Compiling test suite...
    where g++ >nul 2>nul
    if %ERRORLEVEL% equ 0 (
        g++ -std=c++11 test\verify_logic.cpp -o test\verify_logic.exe
    ) else if exist "C:\MinGW\bin\g++.exe" (
        C:\MinGW\bin\g++.exe -std=c++11 test\verify_logic.cpp -o test\verify_logic.exe
    ) else (
        echo [ERROR] g++ compiler not found!
        exit /b 1
    )
)
test\verify_logic.exe
