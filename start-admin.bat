@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
if exist "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" set "BLENDER_PATH=C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
echo.
echo  Autonomous 3D Admin
echo  http://127.0.0.1:8788/admin
echo  視窗請保持開啟。關掉這個視窗 = 關掉網站。
echo.
start "fox3d-browser" cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:8788/admin"
python -m fox3d.api
if errorlevel 1 (
  echo.
  echo 啟動失敗。請確認已安裝: python -m pip install fastapi uvicorn pydantic
  pause
)
