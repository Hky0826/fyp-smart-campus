@echo off
title Smart Campus Cloud Setup
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_cloud.ps1" %*
pause
