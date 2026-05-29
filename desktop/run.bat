@echo off
chcp 65001 >nul
echo ================================
echo   屏幕文字助手 - 启动程序
echo ================================
echo.

:: 检查Python
python --version >nul 2>&1
if errorlevel 1 (
    echo 错误: 未找到Python，请先安装Python 3.8+
    pause
    exit /b 1
)

:: 检查依赖
python -c "import PyQt5" >nul 2>&1
if errorlevel 1 (
    echo 正在安装依赖...
    pip install -r requirements.txt
)

:restart
echo 启动程序...
python monster_monitor.py

echo.
echo 程序已退出，等待 5 分钟后自动重启...
echo 按 Ctrl+C 可终止自动重启
choice /t 300 /d y /n >nul
goto restart