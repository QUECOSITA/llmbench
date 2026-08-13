@echo off
rem Windows counterpart of down.sh - stops backend + frontend.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\down.ps1"