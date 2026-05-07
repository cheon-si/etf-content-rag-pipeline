@echo off
REM ETF 주간 트렌드 분석 자동 스케줄 등록
REM 매주 월요일 오전 09:00 자동 실행

SET PYTHON=C:\Users\Owner\AppData\Local\Programs\Python\Python314\python.exe
SET SCRIPT=%~dp0run_all.py
SET TASK_NAME=ETF Weekly Report

echo ======================================
echo  ETF 주간 보고서 자동 스케줄 등록
echo ======================================
echo.
echo Python: %PYTHON%
echo Script: %SCRIPT%
echo 실행 일시: 매주 월요일 09:00
echo.

REM 기존 작업 삭제 (재등록 시 충돌 방지)
schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1

REM 새 작업 등록
schtasks /create ^
  /tn "%TASK_NAME%" ^
  /tr "\"%PYTHON%\" \"%SCRIPT%\"" ^
  /sc weekly ^
  /d MON ^
  /st 09:00 ^
  /sd %date% ^
  /ru "%USERNAME%" ^
  /rl HIGHEST ^
  /f

IF %ERRORLEVEL% EQU 0 (
    echo.
    echo [성공] 스케줄 등록 완료!
    echo 매주 월요일 09:00에 자동 실행됩니다.
    echo 로그 파일: %~dp0logs\run_YYYYMMDD_HHMMSS.log
) ELSE (
    echo.
    echo [오류] 스케줄 등록 실패. 관리자 권한으로 실행해보세요.
)

echo.
pause
