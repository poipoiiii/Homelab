@echo off
chcp 65001 >nul
setlocal
set "SCRIPT=%~dp0Start-Panel.ps1"
where pwsh.exe >nul 2>nul && (set "PS=pwsh.exe") || (set "PS=powershell.exe")
start "" "%PS%" -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"
