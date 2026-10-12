@echo off
echo ========================================================
echo Running Automated Logic Verification Suite...
echo ========================================================
if not exist "test\verify_logic.exe" (
    echo Compiling test suite...
    C:\MinGW\bin\g++.exe -std=c++11 test\verify_logic.cpp -o test\verify_logic.exe
)
test\verify_logic.exe
