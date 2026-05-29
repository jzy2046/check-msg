@echo off
chcp 65001 >nul
echo ================================
echo   屏幕文字助手 - 安装依赖
echo ================================
echo.

:: 检查Python
python --version >nul 2>&1
if errorlevel 1 (
    echo 错误: 未找到Python！
    echo 请先安装 Python 3.8+
    echo 下载地址: https://www.python.org/downloads/
    echo 安装时请勾选 "Add Python to PATH"
    pause
    exit /b 1
)

echo 检测到Python:
python --version
echo.

echo 正在安装依赖...
echo 使用国内镜像加速...
echo.

pip install PyQt5 -i https://pypi.tuna.tsinghua.edu.cn/simple
pip install mss -i https://pypi.tuna.tsinghua.edu.cn/simple
pip install Pillow -i https://pypi.tuna.tsinghua.edu.cn/simple
pip install numpy -i https://pypi.tuna.tsinghua.edu.cn/simple
pip install rapidocr-onnxruntime -i https://pypi.tuna.tsinghua.edu.cn/simple

echo.
echo ================================
echo   安装完成！
echo ================================
echo.
echo 现在可以双击 run.bat 启动程序
echo.
pause