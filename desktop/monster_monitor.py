"""
屏幕文字识别助手
实时截图识别，提取关键文字信息
"""

import sys
import re
import time
import threading
from collections import deque
import numpy as np

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QGroupBox, QTextEdit, QFrame
)
from PyQt5.QtCore import Qt, QTimer, QRect
from PyQt5.QtGui import QColor, QPalette, QFont

try:
    from PIL import Image
    import mss
    HAS_MSS = True
except ImportError:
    HAS_MSS = False

try:
    from rapidocr_onnxruntime import RapidOCR
    _ocr = None
    def get_ocr():
        global _ocr
        if _ocr is None:
            _ocr = RapidOCR()
        return _ocr
    HAS_RAPIDOCR = True
except ImportError:
    HAS_RAPIDOCR = False

try:
    import pytesseract
    TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    import os
    if os.path.exists(TESSERACT_PATH):
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH
        HAS_TESSERACT = True
    else:
        HAS_TESSERACT = False
except ImportError:
    HAS_TESSERACT = False

# 4组地点分组（来自表格_20260529.csv）
# 每组内的地点出现概率均等：2个地点=50%, 3个=33.33%, 6个=16.67%, 4个=25%
LOCATION_GROUPS = [
    ["蓬莱仙岛", "碗子山"],  # 第1组：2个地点，各50%概率
    ["麒麟山", "北俱芦洲", "朱紫国"],  # 第2组：3个地点，各33.33%概率
    ["大唐国境", "江南野外", "建邺城", "蓬莱仙岛", "碗子山", "波月洞"],  # 第3组：6个地点，各16.67%概率
    ["傲来国", "大唐境外", "长寿郊外", "波月洞"]  # 第4组：4个地点，各25%概率
]

# 所有地点名称
ALL_LOCATIONS = [loc for group in LOCATION_GROUPS for loc in group]

# 计算每组的概率
def get_group_probability(group_index):
    """获取指定组每个地点的出现概率"""
    group_size = len(LOCATION_GROUPS[group_index])
    return 100.0 / group_size


class RegionSelector(QWidget):
    """区域选择器 - 全屏透明窗口用于框选区域"""

    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.start_pos = None
        self.end_pos = None

        # 设置窗口属性
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)
        self.setWindowTitle("框选聊天框区域")

        # 获取屏幕大小并设置窗口
        from PyQt5.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        self.setGeometry(screen.availableGeometry())
        self.showFullScreen()

    def mousePressEvent(self, event):
        self.start_pos = event.pos()

    def mouseMoveEvent(self, event):
        self.end_pos = event.pos()
        self.update()

    def mouseReleaseEvent(self, event):
        self.end_pos = event.pos()
        rect = QRect(self.start_pos, self.end_pos).normalized()
        self.close()
        if rect.width() > 5 and rect.height() > 5:
            self.callback(rect.x(), rect.y(), rect.width(), rect.height())

    def paintEvent(self, event):
        from PyQt5.QtGui import QPainter, QPen
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))

        if self.start_pos and self.end_pos:
            rect = QRect(self.start_pos, self.end_pos).normalized()
            painter.fillRect(rect, QColor(100, 100, 255, 100))
            pen = QPen(QColor(255, 0, 0), 3)
            painter.setPen(pen)
            painter.drawRect(rect)


class MonitorApp(QMainWindow):
    """主监控窗口"""

    def __init__(self):
        super().__init__()
        self.monitor_region = None  # (x, y, w, h)
        self.target_locations = []  # 要监控的地点列表
        self.last_detected_location = None  # 上次检测到的地点
        self.last_detected_time = None  # 上次检测的时间
        self.last_group_index = None  # 上次刷新的组索引（用于智能判断）
        self.current_group_index = None  # 当前刷新的组索引
        self.history = deque(maxlen=10)  # 历史刷新记录
        self.monitoring = False
        self.flash_state = False
        self.current_alert_type = None  # 当前提醒类型

        # 颜色过滤阈值（根据222.png分析得出的黄色文字范围）
        self.color_threshold = {
            'r_min': 200, 'r_max': 255,
            'g_min': 165, 'g_max': 255,
            'b_min': 0, 'b_max': 100
        }

        # 用于处理换行的文字缓冲
        self.text_buffer = ""

        # 当前高亮的组索引
        self.highlight_group_index = -1
        self.animation_offset = 0

        self.init_ui()

        # OCR检测定时器
        self.detect_timer = QTimer()
        self.detect_timer.timeout.connect(self.detect_location)

        # 跑马灯动画定时器
        self.animation_timer = QTimer()
        self.animation_timer.timeout.connect(self.update_animation)

        # 缓冲清除定时器
        self.buffer_timer = QTimer()
        self.buffer_timer.timeout.connect(self.clear_buffer)

        # 闪烁定时器
        self.flash_timer = QTimer()
        self.flash_timer.timeout.connect(self.toggle_flash)

        # 提醒消失定时器 - 已移除，改为常驻显示

    def clear_buffer(self):
        """清除文字缓冲"""
        self.text_buffer = ""

    def update_animation(self):
        """跑马灯动画更新"""
        if self.highlight_group_index < 0:
            return

        # 动画偏移增加
        self.animation_offset = (self.animation_offset + 1) % 3

        # 更新每个组的显示样式
        for i, label in enumerate(self.group_labels):
            group_info = LOCATION_GROUPS[i]
            prob = get_group_probability(i)

            if i == self.highlight_group_index:
                # 高亮当前组 - 闪烁效果
                if self.animation_offset == 0:
                    label.setStyleSheet("""
                        color: #fff;
                        font-size: 13px;
                        font-weight: bold;
                        padding: 5px;
                        border-radius: 5px;
                        background-color: #ff4757;
                        border: 2px solid #ff6b6b;
                    """)
                elif self.animation_offset == 1:
                    label.setStyleSheet("""
                        color: #fff;
                        font-size: 13px;
                        font-weight: bold;
                        padding: 5px;
                        border-radius: 5px;
                        background-color: #ff6b6b;
                        border: 2px solid #fff;
                    """)
                else:
                    label.setStyleSheet("""
                        color: #fff;
                        font-size: 13px;
                        font-weight: bold;
                        padding: 5px;
                        border-radius: 5px;
                        background-color: #ff4757;
                        border: 2px solid #ffd700;
                    """)
            elif i == (self.highlight_group_index + 1) % 4:
                # 下一组 - 黄色报警提醒（预测）
                label.setStyleSheet("""
                    color: #333;
                    font-size: 13px;
                    font-weight: bold;
                    padding: 5px;
                    border-radius: 5px;
                    background-color: #ffd700;
                    border: 2px solid #ffaa00;
                """)
            else:
                # 其他组 - 灰色
                label.setStyleSheet("""
                    color: #888;
                    font-size: 12px;
                    padding: 5px;
                    border-radius: 5px;
                    background-color: #2a2a4e;
                """)

    def set_highlight_group(self, group_index):
        """设置当前高亮的组"""
        self.highlight_group_index = group_index
        self.update_animation()
        # 启动动画定时器
        self.animation_timer.start(300)  # 300ms更新一次

    def init_ui(self):
        self.setWindowTitle("屏幕文字助手")
        self.setMinimumSize(700, 500)  # 最小尺寸
        self.resize(800, 600)  # 默认更大
        self.setStyleSheet("")

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setSpacing(8)
        layout.setContentsMargins(10, 10, 10, 10)

        # 标题 - 更紧凑
        title_label = QLabel("屏幕文字助手")
        title_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #333;")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        # 顶部一行：设置 + 监控地点 + 控制按钮
        top_row = QHBoxLayout()

        # 设置区
        setup_group = QGroupBox("设置")
        setup_layout = QHBoxLayout(setup_group)
        self.region_label = QLabel("区域: 未选择")
        self.region_label.setStyleSheet("color: #666;")
        self.select_btn = QPushButton("框选")
        self.select_btn.setFixedWidth(50)
        self.select_btn.clicked.connect(self.select_region)
        setup_layout.addWidget(self.region_label)
        setup_layout.addWidget(self.select_btn)
        top_row.addWidget(setup_group)

        # 监控地点
        target_group = QGroupBox("监控地点")
        target_layout = QHBoxLayout(target_group)
        self.location_input = QLineEdit()
        self.location_input.setPlaceholderText("输入地点...")
        self.location_input.setFixedWidth(100)
        add_btn = QPushButton("添加")
        add_btn.setFixedWidth(50)
        add_btn.clicked.connect(self.add_target_location)
        self.target_display = QLabel("无")
        self.target_display.setStyleSheet("color: #008800; font-weight: bold;")
        target_layout.addWidget(self.location_input)
        target_layout.addWidget(add_btn)
        target_layout.addWidget(self.target_display)
        top_row.addWidget(target_group)

        # 控制按钮
        self.start_btn = QPushButton("开始监控")
        self.start_btn.clicked.connect(self.toggle_monitoring)
        self.start_btn.setStyleSheet("font-size: 12px; font-weight: bold;")
        self.start_btn.setFixedWidth(80)
        top_row.addWidget(self.start_btn)

        self.clear_btn = QPushButton("清空")
        self.clear_btn.clicked.connect(self.clear_targets)
        self.clear_btn.setFixedWidth(50)
        top_row.addWidget(self.clear_btn)

        layout.addLayout(top_row)

        # 跑马灯进度 - 精简显示
        self.progress_frame = QFrame()
        self.progress_frame.setStyleSheet("background-color: #1a1a2e; border-radius: 6px;")
        progress_layout = QHBoxLayout(self.progress_frame)
        progress_layout.setContentsMargins(8, 6, 8, 6)

        self.group_labels = []
        for i in range(4):
            group_info = LOCATION_GROUPS[i]
            prob = get_group_probability(i)
            # 精简显示：只显示组号和前2个地点
            text = f"第{i+1}组\n{', '.join(group_info[:2])}\n{prob:.0f}%"
            label = QLabel(text)
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet("""
                color: #888;
                font-size: 11px;
                padding: 4px;
                border-radius: 4px;
                background-color: #2a2a4e;
            """)
            label.setMinimumWidth(100)
            progress_layout.addWidget(label)
            self.group_labels.append(label)

        layout.addWidget(self.progress_frame)

        # 状态行 - 合并到一行
        status_row = QHBoxLayout()
        self.status_label = QLabel("等待开始...")
        self.status_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #333;")
        status_row.addWidget(self.status_label, 1)

        self.current_location_label = QLabel("当前: -")
        self.current_location_label.setStyleSheet("font-size: 13px; color: #0066cc;")
        status_row.addWidget(self.current_location_label)

        self.history_label = QLabel("历史: 无")
        self.history_label.setStyleSheet("color: #888; font-size: 11px;")
        status_row.addWidget(self.history_label)
        layout.addLayout(status_row)

        # 提醒区域 - 固定高度
        self.alert_frame = QFrame()
        self.alert_frame.setMinimumHeight(80)  # 最小80px，允许扩展
        self.alert_frame.setStyleSheet("background-color: #f5f5f5; border: 2px solid #ddd;")
        alert_layout = QVBoxLayout(self.alert_frame)
        alert_layout.setContentsMargins(5, 5, 5, 5)
        self.alert_label = QLabel("")
        self.alert_label.setAlignment(Qt.AlignCenter)
        self.alert_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.alert_label.setWordWrap(True)
        alert_layout.addWidget(self.alert_label)
        layout.addWidget(self.alert_frame)

        # 日志区域 - 占据大部分空间
        log_group = QGroupBox("日志")
        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(5, 5, 5, 5)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("font-size: 11px;")
        log_layout.addWidget(self.log_text)
        layout.addWidget(log_group, 1)  # stretch=1，占据剩余空间

    def select_region(self):
        """打开区域选择器"""
        self.selector = RegionSelector(self.on_region_selected)
        self.selector.show()

    def on_region_selected(self, x, y, w, h):
        """区域选择完成回调"""
        if w > 10 and h > 10:
            self.monitor_region = (x, y, w, h)
            self.region_label.setText(f"区域: ({x}, {y}) {w}x{h}")
            self.region_label.setStyleSheet("color: #00ff00;")
            self.log(f"已选择监控区域: ({x}, {y}) {w}x{h}")
        else:
            self.log("区域选择无效，请重新选择")

    def add_target_location(self):
        """添加监控地点"""
        location = self.location_input.text().strip()
        if not location:
            return

        if location not in ALL_LOCATIONS:
            self.log(f"警告: '{location}' 不在已知地点列表中，但仍会监控")

        if location not in self.target_locations:
            self.target_locations.append(location)
            self.update_target_display()
            self.log(f"已添加监控地点: {location}")
        else:
            self.log(f"地点 '{location}' 已在监控列表中")

        self.location_input.clear()

    def update_target_display(self):
        """更新监控地点显示"""
        if self.target_locations:
            self.target_display.setText(f"当前监控: {', '.join(self.target_locations)}")
        else:
            self.target_display.setText("当前监控: 无")

    def clear_targets(self):
        """清空监控地点"""
        self.target_locations.clear()
        self.update_target_display()
        self.log("已清空监控地点列表")

    def process_detected_location(self, detected_location):
        """处理检测到的地点"""
        current_time = time.time()

        # 只有当地点相同且时间间隔小于15秒时才跳过（避免重复检测）
        # 如果超过15秒，即使是相同地点也认为是新的一轮
        if detected_location == self.last_detected_location:
            if self.last_detected_time and (current_time - self.last_detected_time) < 15:
                return

        self.last_detected_location = detected_location
        self.last_detected_time = current_time
        self.current_location_label.setText(f"当前刷新: {detected_location}")
        self.log(f"检测到刷新地点: {detected_location}")

        # 智能判断当前组索引
        self.current_group_index = self.smart_detect_group(detected_location)

        if self.current_group_index is not None:
            # 更新跑马灯高亮
            self.set_highlight_group(self.current_group_index)

            # 记录到历史
            self.history.append({
                'location': detected_location,
                'group': self.current_group_index + 1,
                'time': time.strftime("%H:%M:%S")
            })

            # 更新上次组索引
            self.last_group_index = self.current_group_index

            # 更新历史显示
            if self.history:
                recent = list(self.history)[-5:]
                history_text = " → ".join([f"{h['location']}(组{h['group']})" for h in recent])
                self.history_label.setText(f"历史: {history_text}")

            # 计算下一组
            next_group_index = (self.current_group_index + 1) % 4
            next_group = LOCATION_GROUPS[next_group_index]

            # 检查监控地点是否在下一组
            target_in_next = [loc for loc in self.target_locations if loc in next_group]

            # 检查监控地点是否在当前组但没刷到
            current_group = LOCATION_GROUPS[self.current_group_index]
            target_in_current = [loc for loc in self.target_locations if loc in current_group]
            missed_current = target_in_current and detected_location not in target_in_current

            if detected_location in self.target_locations:
                # 当前刷到的是监控地点！红色抢妖警告（最高优先级）
                prob = get_group_probability(self.current_group_index)
                self.trigger_alert("warning", f"⚡ 抢妖警告!\n{detected_location} 已刷新!\n快去抢!")
                self.status_label.setText(f"🔴 抢妖！{detected_location} 刷新了！")
                self.status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #ff0000;")
            elif target_in_next:
                # 监控地点在下一组，显示黄色准备抢妖（第二优先级）
                prob = get_group_probability(next_group_index)
                target_probs = [f"{loc}({prob:.1f}%)" for loc in target_in_next]
                self.trigger_alert("prepare", f"⚠️ 准备抢妖!\n下一轮第{next_group_index+1}组\n可能刷新: {', '.join(target_probs)}")
                self.status_label.setText(f"⚠️ 准备抢妖！下一轮可能刷新 {target_in_next[0]}")
                self.status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #ff4757;")
                # 高亮下一组标签
                for i, label in enumerate(self.group_labels):
                    if i == next_group_index:
                        label.setStyleSheet("""
                            color: #fff;
                            font-size: 13px;
                            font-weight: bold;
                            padding: 5px;
                            border-radius: 5px;
                            background-color: #ffd700;
                            border: 2px solid #ff6b6b;
                        """)
            elif missed_current:
                # 监控地点在当前组但没刷到，显示灰色提醒（最低优先级）
                self.trigger_alert("miss", f"😢 本轮没命中\n{', '.join(target_in_current)} 未刷新\n等待下一轮...")
                self.status_label.setText(f"当前第{self.current_group_index+1}组: {detected_location} (非监控)")
                self.status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #888;")
            else:
                # 正常状态，显示当前刷新信息
                self.set_normal_alert(self.current_group_index + 1, detected_location)
                self.status_label.setText(f"当前第{self.current_group_index+1}组刷新 {detected_location}")
                self.status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #333;")

    def toggle_monitoring(self):
        """切换监控状态"""
        if not self.monitoring:
            # 使用手动模式时不需要选择区域
            # if not self.monitor_region:
            #     self.log("请先选择监控区域")
            #     return
            if not self.target_locations:
                self.log("请先添加要监控的地点")
                return

            self.monitoring = True
            self.start_btn.setText("停止监控")
            self.select_btn.setEnabled(False)
            self.last_group_index = None  # 重置历史
            self.history.clear()
            self.log("开始监控... (OCR自动检测)")
            self.status_label.setText("状态: 监控中")
            # OCR检测定时器
            if (HAS_RAPIDOCR or HAS_TESSERACT) and HAS_MSS and self.monitor_region:
                self.detect_timer.start(1000)  # 每1秒检测一次
        else:
            self.monitoring = False
            self.start_btn.setText("开始监控")
            self.select_btn.setEnabled(True)
            self.log("已停止监控")
            self.status_label.setText("状态: 已停止")
            self.detect_timer.stop()
            self.flash_timer.stop()
            self.alert_frame.setStyleSheet("background-color: #f0f0f0; border: 2px solid #ccc;")

    def get_group_index(self, location):
        """获取地点所在的组索引（返回所有可能的组）"""
        groups = []
        for i, group in enumerate(LOCATION_GROUPS):
            if location in group:
                groups.append(i)
        return groups

    def smart_detect_group(self, location):
        """智能判断当前刷新的组索引

        根据上一轮刷新的组来推断当前组：
        - 如果上一轮是第N组，当前应该是第(N+1)组
        - 检测到的地点如果在预期组中，则确认
        - 如果地点在多个组中，优先选择预期的组
        """
        possible_groups = self.get_group_index(location)

        if not possible_groups:
            return None

        # 如果只有一个可能的组，直接返回
        if len(possible_groups) == 1:
            return possible_groups[0]

        # 如果有历史记录，根据上一轮推断
        if self.last_group_index is not None:
            expected_group = (self.last_group_index + 1) % 4
            if expected_group in possible_groups:
                return expected_group
            else:
                # 检测到的地点不在预期组，可能是异常或漏检测
                # 返回第一个可能的组，并记录警告
                self.log(f"⚠️ 注意: {location} 不在预期组{expected_group+1}中，实际在组{[g+1 for g in possible_groups]}")
                return possible_groups[0]

        # 没有历史记录时，返回第一个可能的组
        return possible_groups[0]

    def detect_location(self):
        """截图并OCR检测地点"""
        if not self.monitor_region or not HAS_MSS:
            if not self.monitor_region:
                self.log("错误: 请先框选聊天框区域")
            self.detect_timer.stop()
            return

        if not HAS_RAPIDOCR and not HAS_TESSERACT:
            self.log("错误: 未安装OCR引擎")
            self.detect_timer.stop()
            return

        try:
            x, y, w, h = self.monitor_region
            with mss.mss() as sct:
                screenshot = sct.grab({"left": x, "top": y, "width": w, "height": h})
                img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)

            # 放大图像提高识别率
            img_large = img.resize((img.width*2, img.height*2), Image.LANCZOS)
            pixels = np.array(img_large)

            # 把黄色文字转成白色（提高OCR识别率）
            yellow_mask = (
                (pixels[:,:,0] > 180) &
                (pixels[:,:,1] > 140) &
                (pixels[:,:,2] < 150)
            )
            pixels[yellow_mask] = [255, 255, 255]  # 黄色变白色

            # 使用RapidOCR识别
            if HAS_RAPIDOCR:
                ocr = get_ocr()
                result = ocr(pixels)

                if result and result[0]:
                    # result[0] 是列表，每个元素是 [坐标, 文字, 置信度]
                    # 坐标格式: [[x1,y1], [x2,y2], [x3,y3], [x4,y4]] (左上、右上、右下、左下)
                    # 只取最下面那条文字（y坐标最大的，即屏幕最下方）
                    all_texts = []
                    for r in result[0]:
                        coords = r[0]  # 坐标
                        text = r[1]    # 文字
                        # 计算平均y坐标（文字块的垂直位置）
                        avg_y = sum([p[1] for p in coords]) / len(coords)
                        all_texts.append((avg_y, text))

                    # 按y坐标排序，取最大的（最下面的）
                    all_texts.sort(key=lambda x: x[0], reverse=True)
                    bottom_text = all_texts[0][1] if all_texts else ""

                    # 只有文字内容变化时才打印日志
                    if bottom_text != self.text_buffer:
                        self.text_buffer = bottom_text
                        self.log(f"识别(最新): {bottom_text[:50]}...")

                    detected_location = self.extract_location(bottom_text)
                    if detected_location and detected_location != self.last_detected_location:
                        self.process_detected_location(detected_location)
                    return

            elif HAS_TESSERACT:
                # Tesseract备用方案 - 取最后一行作为最新信息
                text = pytesseract.image_to_string(Image.fromarray(pixels), lang='chi_sim+eng')
                lines = text.strip().split('\n')
                bottom_line = lines[-1] if lines else ""
                if bottom_line != self.text_buffer:
                    self.text_buffer = bottom_line
                    self.log(f"识别(最新): {bottom_line[:50]}...")
                detected_location = self.extract_location(bottom_line)
                if detected_location and detected_location != self.last_detected_location:
                    self.process_detected_location(detected_location)

        except Exception as e:
            self.log(f"检测错误: {str(e)}")

    def extract_location(self, text):
        """从文本中提取地点名称 - 基于2字组合匹配"""
        import re

        # 只保留中文字符（过滤英文、数字、符号、乱码）
        # 中文字符的Unicode范围: 一-鿿
        text = re.sub(r'[^一-鿿]', '', text)

        # 如果过滤后文字太少，直接返回None
        if len(text) < 2:
            return None

        # 每个地点的关键2字组合（只要匹配到任意一个就判定为该地点）
        # 越独特的组合放前面，优先匹配
        LOCATION_KEYWORDS = {
            "蓬莱仙岛": ["仙岛", "蓬莱", "蓬仙", "莱仙"],  # 仙岛最独特
            "碗子山": ["子山", "碗子", "碗山"],  # 子山最独特
            "麒麟山": ["麒麟"],
            "北俱芦洲": ["北俱", "俱芦", "芦洲"],  # 北俱最独特
            "朱紫国": ["朱紫", "紫国"],
            "大唐国境": ["国境", "大唐"],  # 国境更独特（区别于境外）
            "大唐境外": ["境外"],  # 境外最独特
            "江南野外": ["江南", "野外"],
            "建邺城": ["建邺"],
            "波月洞": ["波月", "月洞"],
            "傲来国": ["傲来"],
            "长寿郊外": ["长寿", "郊外"],
            "长安城": ["长安"],
        }

        # OCR常见单字误识别纠正（用于修正组合中的单字）
        char_corrections = {
            "菜": "莱", "篷": "蓬", "逢": "蓬", "来": "莱",
            "硼": "碗", "烷": "碗", "婉": "碗", "豌": "碗",
            "害": "唐", "竟": "境",  # 常见中文误识别
        }

        # 先修正常见单字错误
        corrected_text = text
        for wrong, correct in char_corrections.items():
            corrected_text = corrected_text.replace(wrong, correct)

        # 匹配"正在xxx寻衅闹事"格式，提取中间的地点
        match = re.search(r"正在\s*(\S+)\s*寻衅", corrected_text)
        if match:
            loc = match.group(1)
            # 在提取的地点中搜索关键词
            for location, keywords in LOCATION_KEYWORDS.items():
                for kw in keywords:
                    if kw in loc:
                        return location
            # 也检查原始文本（可能OCR后没被修正）
            for location, keywords in LOCATION_KEYWORDS.items():
                for kw in keywords:
                    if kw in text:
                        return location

        # 匹配"刷新在了xxx"格式
        match = re.search(r"刷新在了?(\S+)", corrected_text)
        if match:
            loc = match.group(1)
            for location, keywords in LOCATION_KEYWORDS.items():
                for kw in keywords:
                    if kw in loc:
                        return location

        # 直接在全文中搜索关键词组合
        for location, keywords in LOCATION_KEYWORDS.items():
            for kw in keywords:
                if kw in corrected_text or kw in text:
                    return location

        return None

    def trigger_alert(self, alert_type, message):
        """触发提醒 - 常驻显示，不自动消失"""
        # 停止之前的闪烁，重新开始
        self.flash_timer.stop()

        self.alert_label.setText(message)
        self.flash_state = True
        self.current_alert_type = alert_type  # 记录当前提醒类型

        if alert_type == "warning":
            # 真的刷到监控地点 - 红色背景
            self.alert_frame.setStyleSheet("background-color: #ff0000; border: 3px solid #ff3333;")
            self.alert_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #fff;")
            self.beep_warning()
        elif alert_type == "miss":
            # 没刷到监控地点 - 灰色背景
            self.alert_frame.setStyleSheet("background-color: #95a5a6; border: 3px solid #7f8c8d;")
            self.alert_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #fff;")
            self.beep_miss()
        else:  # prepare
            # 预测准备抢妖 - 黄色背景
            self.alert_frame.setStyleSheet("background-color: #ffd700; border: 3px solid #ffaa00;")
            self.alert_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #333;")
            self.beep_prepare()

        self.flash_timer.start(500)  # 开始闪烁动画
        self.log(f"提醒: {message.replace(chr(10), ' ')}")

    def set_normal_alert(self, group_num, location):
        """设置正常状态显示"""
        self.flash_timer.stop()
        self.current_alert_type = "normal"
        self.alert_label.setText(f"当前第{group_num}组刷新: {location}")
        self.alert_frame.setStyleSheet("background-color: #e8e8e8; border: 2px solid #ccc;")
        self.alert_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #666;")

    def beep_prepare(self):
        """准备提醒音（黄色）"""
        try:
            import winsound
            winsound.Beep(600, 200)
        except:
            pass

    def beep_miss(self):
        """没命中提醒音（灰色）"""
        try:
            import winsound
            winsound.Beep(400, 300)  # 低沉的单音
        except:
            pass

    def beep_warning(self):
        """抢妖警告音（红色）"""
        try:
            import winsound
            for _ in range(3):
                winsound.Beep(1000, 150)
                winsound.Beep(1200, 150)
        except:
            pass

    def toggle_flash(self):
        """切换闪烁状态"""
        self.flash_state = not self.flash_state
        current = self.alert_frame.styleSheet()
        if "ff0000" in current:  # 红色警告
            if self.flash_state:
                self.alert_frame.setStyleSheet("background-color: #ff0000; border: 3px solid #ff3333;")
            else:
                self.alert_frame.setStyleSheet("background-color: #cc0000; border: 3px solid #ff0000;")
        elif "ffd700" in current:  # 黄色预测
            if self.flash_state:
                self.alert_frame.setStyleSheet("background-color: #ffd700; border: 3px solid #ffaa00;")
            else:
                self.alert_frame.setStyleSheet("background-color: #ffaa00; border: 3px solid #ffd700;")
        elif "95a5a6" in current:  # 灰色没命中
            if self.flash_state:
                self.alert_frame.setStyleSheet("background-color: #95a5a6; border: 3px solid #7f8c8d;")
            else:
                self.alert_frame.setStyleSheet("background-color: #7f8c8d; border: 3px solid #95a5a6;")

    def log(self, message):
        """添加日志"""
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        # 自动滚动到底部
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())


def check_dependencies():
    """检查依赖"""
    missing = []
    if not HAS_MSS:
        missing.append("mss")
    if not HAS_TESSERACT:
        missing.append("pytesseract")

    if missing:
        print(f"缺少依赖: {', '.join(missing)}")
        print("请运行以下命令安装:")
        print(f"  pip install {' '.join(missing)}")
        if "pytesseract" in missing:
            print("\n还需要安装Tesseract OCR:")
            print("  Windows: https://github.com/UB-Mannheim/tesseract/wiki")
            print("  安装后设置环境变量或代码中指定路径")
        return False
    return True


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei", 10))

    # 显示依赖检查结果
    if not check_dependencies():
        print("\n警告: 部分功能可能不可用，请安装缺失的依赖")

    window = MonitorApp()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()