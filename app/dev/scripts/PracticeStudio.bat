@echo off
setlocal
if defined JAVA_HOME (
  set "PRACTICE_JAVA=%JAVA_HOME%\bin\java.exe"
) else (
  set "PRACTICE_JAVA=java.exe"
)
"%PRACTICE_JAVA%" --enable-preview -cp "%~dp0..\lib\*" com.notelite.omr.practice.PracticeStudio --browse %*
if errorlevel 1 pause
endlocal
