# 屏幕文字助手 - 安装指南

## 安装步骤

### 第一步：安装 Python

1. 下载 Python 3.8+ ：https://www.python.org/downloads/
2. 安装时勾选 **"Add Python to PATH"**（添加到环境变量）
3. 安装完成后，打开命令行验证：
   ```
   python --version
   ```

### 第二步：复制项目文件

将以下文件复制到目标电脑：
- `monster_monitor.py`（主程序）
- `run.bat`（启动脚本）
- `requirements.txt`（依赖列表）

### 第三步：安装依赖

打开命令行，进入项目目录，执行：
```
pip install -r requirements.txt
```

等待安装完成（约2-5分钟）。

### 第四步：运行程序

双击 `run.bat` 启动，或在命令行执行：
```
python monster_monitor.py
```

---

## 快速安装（一键脚本）

直接双击 `run.bat`，它会自动检查并安装缺失的依赖。

---

## 常见问题

### Q: 提示"未找到Python"
**解决**：安装Python时没有勾选"Add to PATH"，需要重新安装或手动添加环境变量。

### Q: pip安装很慢
**解决**：使用国内镜像：
```
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### Q: 提示"rapidocr安装失败"
**解决**：分步安装：
```
pip install PyQt5
pip install mss
pip install Pillow
pip install numpy
pip install rapidocr-onnxruntime
```

### Q: 程序运行报错
**解决**：检查Python版本（需要3.8+），重新安装依赖。

---

## 依赖说明

| 依赖 | 用途 |
|------|------|
| PyQt5 | 界面框架 |
| rapidocr-onnxruntime | OCR文字识别 |
| mss | 屏幕截图 |
| Pillow | 图像处理 |
| numpy | 数组运算 |

---

## 文件清单

```
屏幕文字助手/
├── monster_monitor.py   # 主程序（必须）
├── run.bat              # 启动脚本（必须）
├── requirements.txt     # 依赖列表（必须）
├── INSTALL_GUIDE.md     # 安装指南（可选）
└── PROJECT_SUMMARY.md   # 项目总结（可选）
```

---

*安装完成后，双击 run.bat 即可使用*