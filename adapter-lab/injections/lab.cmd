@echo off
rem AgencyZero lab launcher - runs lab.ps1 without the PowerShell execution-policy prompt.
rem Usage: lab.cmd help
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0lab.ps1" %*
