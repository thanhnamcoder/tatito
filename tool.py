import sys
import os
import time
import json
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication,
    QStatusBar,
    QWidget,
    QFrame,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QScrollArea,
    QLabel,
    QMessageBox,
    QRubberBand,
    QInputDialog,
    QMainWindow,
    QAction,
    QToolBar,
    QDialog,
    QSizePolicy,
    QShortcut,
    QComboBox,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QFormLayout,
    QTimeEdit,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSplitter,
    QGroupBox,
    QSpinBox,
    QDoubleSpinBox,
    QAbstractItemView,
    QFileDialog
)
from PyQt5.QtCore import Qt, QPoint, QRect, QSize, QTimer, QThread, pyqtSignal, QTime
from PyQt5.QtGui import QPainter, QColor, QKeySequence, QPixmap, QIntValidator
from auto import click_image as auto_click_image, trigger_scheduler_reload, check_scheduler_status
import re
import unicodedata
import inspect


def get_job_function_names(config_path=None):
    """
    Lấy danh sách tên job từ file config.json (từ các mục trong schedule).
    Đây là nguồn dữ liệu chính cho giao diện và scheduler.
    """
    if config_path is None:
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

    if not os.path.exists(config_path):
        return []

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception:
        return []

    names = []
    schedule = config.get("schedule", {})
    for day_cfg in schedule.values():
        if not isinstance(day_cfg, dict):
            continue
        for job_name in day_cfg.keys():
            if job_name not in names:
                names.append(job_name)
    return sorted(names)


WEEKDAY_OPTIONS = [
    ("Thứ 2", "0"),
    ("Thứ 3", "1"),
    ("Thứ 4", "2"),
    ("Thứ 5", "3"),
    ("Thứ 6", "4"),
    ("Thứ 7", "5"),
    ("Chủ nhật", "6"),
]


def build_default_schedule():
    return {
        "schedule": {
            "0": {},
            "1": {},
            "2": {},
            "3": {
                "test1": {"start": "19:24", "end": "23:26"},
                "test2": {"start": "19:26", "end": "19:27"},
            },
            "4": {
                "test1": {"start": "21:04", "end": "21:04"},
                "test2": {"start": "21:05", "end": "21:05"},
            },
            "5": {},
            "6": {},
        }
    }


def load_config_file(path):
    if not os.path.exists(path):
        return build_default_schedule()
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config_file(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        f.write("\n")


def sanitize_filename_part(name):
    if name is None:
        return "file"

    text = str(name).strip()
    if not text:
        return "file"

    # Chuyển về dạng ASCII cơ bản, loại bỏ dấu tiếng Việt
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))

    # Bổ sung một số ký tự đặc biệt thường gặp
    text = text.translate(
        str.maketrans({
            "đ": "d",
            "Đ": "D",
            "ß": "ss",
            "Æ": "AE",
            "æ": "ae",
            "Œ": "OE",
            "œ": "oe",
            "ł": "l",
            "Ł": "L",
            "þ": "th",
            "Þ": "TH",
        })
    )

    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("._-")

    return text or "file"


def normalize_app_path(path_value):
    if path_value is None:
        return ""

    path_text = str(path_value).strip()
    if not path_text:
        return ""

    path_text = path_text.strip('"').strip("'")

    if os.path.isabs(path_text):
        return path_text

    if os.path.exists(path_text):
        return os.path.abspath(path_text)

    if os.path.exists(os.path.abspath(path_text)):
        return os.path.abspath(path_text)

    # Nếu người dùng nhập dạng như C:\Program Files\... thì giữ nguyên,
    # còn nếu nhập dạng có dấu \ thay bằng / thì chuẩn hóa lại.
    normalized = path_text.replace("/", os.sep).replace("\\", os.sep)
    return normalized


class SelectionOverlay(QWidget):
    """
    Cửa sổ overlay toàn màn hình, nền mờ, cho phép người dùng kéo chuột
    để chọn 1 vùng chữ nhật. Khi chọn xong (thả chuột) sẽ gọi callback
    với QRect đã chọn. Nhấn ESC để hủy (callback được gọi với None).
    """

    def __init__(self, on_finished):
        super().__init__()
        self.on_finished = on_finished
        self.origin = QPoint()
        self._has_origin = False

        # Cửa sổ không viền, luôn nổi trên cùng, không có trong taskbar
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)

        # Phủ toàn bộ vùng làm việc (gộp tất cả màn hình, nếu có nhiều màn)
        desktop = QApplication.desktop()
        full_geometry = QRect()
        for i in range(desktop.screenCount()):
            full_geometry = full_geometry.united(desktop.screenGeometry(i))
        self.setGeometry(full_geometry)

        self.rubber_band = QRubberBand(QRubberBand.Rectangle, self)

        # Cho phép nhấn ESC để hủy chọn vùng
        self.esc_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self.esc_shortcut.activated.connect(self.cancel_selection)

    def paintEvent(self, event):
        painter = QPainter(self)
        # Lớp phủ màu đen mờ lên toàn bộ overlay
        painter.fillRect(self.rect(), QColor(0, 0, 0, 90))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.origin = event.pos()
            self._has_origin = True
            self.rubber_band.setGeometry(QRect(self.origin, QSize()))
            self.rubber_band.show()

    def mouseMoveEvent(self, event):
        if self._has_origin:
            self.rubber_band.setGeometry(
                QRect(self.origin, event.pos()).normalized()
            )

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._has_origin:
            rect = QRect(self.origin, event.pos()).normalized()
            self.rubber_band.hide()
            self._has_origin = False
            self.close()
            if self.on_finished:
                self.on_finished(rect)

    def cancel_selection(self):
        self.rubber_band.hide()
        self._has_origin = False
        self.close()
        if self.on_finished:
            self.on_finished(None)





class ElidedLabel(QLabel):
    """QLabel that automatically elides long text with '...' when resized."""

    def __init__(self, full_text="", parent=None):
        super().__init__(parent)
        self._full_text = full_text
        self.setText(full_text)

    def setFullText(self, text: str):
        self._full_text = text
        self.updateElide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.updateElide()

    def updateElide(self):
        fm = self.fontMetrics()
        avail = max(0, self.width() - 4)
        elided = fm.elidedText(self._full_text, Qt.ElideRight, avail)
        super().setText(elided)




class ImageFileRow(QFrame):
    clicked = pyqtSignal(str)
    double_clicked = pyqtSignal(str)
    delete_clicked = pyqtSignal(str)

    def __init__(self, file_path, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.setFrameShape(QFrame.StyledPanel)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(file_path)
        self._selected = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        pixmap = QPixmap(file_path)
        if not pixmap.isNull():
            thumb = pixmap.scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            img_label = QLabel()
            img_label.setPixmap(thumb)
            img_label.setFixedSize(48, 48)
            layout.addWidget(img_label)

        name_label = ElidedLabel(os.path.basename(file_path))
        name_label.setFullText(os.path.basename(file_path))
        name_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        name_label.setToolTip(file_path)
        layout.addWidget(name_label, 1)

        delete_btn = QPushButton("Delete")
        delete_btn.setFixedWidth(70)
        delete_btn.clicked.connect(lambda checked=False: self.delete_clicked.emit(self.file_path))
        layout.addWidget(delete_btn)

    def set_selected(self, selected):
        self._selected = bool(selected)
        if self._selected:
            self.setStyleSheet("background: #e8f1ff; border: 1px solid #8fb6ff;")
        else:
            self.setStyleSheet("")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.file_path)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit(self.file_path)
        super().mouseDoubleClickEvent(event)


class JobListRow(QWidget):
    def __init__(self, job_name, on_test=None, on_delete=None, parent=None):
        super().__init__(parent)
        self.job_name = job_name
        self.on_test = on_test
        self.on_delete = on_delete
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)

        label = QLabel(job_name)
        label.setWordWrap(False)
        layout.addWidget(label, 1)

        test_btn = QPushButton("Test")
        test_btn.setFixedWidth(60)
        if on_test:
            test_btn.clicked.connect(lambda: on_test(job_name))
        layout.addWidget(test_btn)

        delete_btn = QPushButton("Delete")
        delete_btn.setFixedWidth(60)
        if on_delete:
            delete_btn.clicked.connect(lambda: on_delete(job_name))
        layout.addWidget(delete_btn)


class WorkflowListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)

    def dropEvent(self, event):
        super().dropEvent(event)
        if hasattr(self.parent(), "reorder_workflow_steps"):
            self.parent().reorder_workflow_steps()


class SetJobDialog(QDialog):
    ACTIONS = [
        ("Open App", "open_app"),
        ("Close App", "close_app"),
        ("Click Image", "click_image"),
        ("Wait Image", "wait_image"),
        ("Type Text", "paste"),
        ("Sleep", "sleep"),
    ]

    def __init__(self, parent=None, config_path=None):
        super().__init__(parent)
        self.setWindowTitle("Set Job")
        self.resize(1100, 650)
        self.config_path = config_path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        self.selected_action = "Click Image"
        self.selected_action_key = self.get_action_key(self.selected_action)
        self.selected_day_key = "0"
        self.selected_job_name = ""
        self.selected_job_config = None
        self.selected_image_path = ""
        self.job_names = get_job_function_names(self.config_path)
        self.workflow_steps = []
        self.workflow_data = []
        self.init_ui()
        self.scheduler_status_timer = QTimer(self)
        self.scheduler_status_timer.timeout.connect(self.refresh_scheduler_status)
        self.scheduler_status_timer.start(3000)
        self.refresh_scheduler_status()
        self.refresh_job_list()
        self.create_new_job()

    def get_action_key(self, label):
        for name, key in self.ACTIONS:
            if name == label:
                return key
        return ""

    def refresh_scheduler_status(self):
        status = check_scheduler_status()
        if status.get("running"):
            self.scheduler_status_label.setText(f"Scheduler: Đang chạy (PID {status.get('pid')})")
            self.scheduler_status_label.setStyleSheet("font-weight: bold; color: #2e7d32;")
        else:
            self.scheduler_status_label.setText("Scheduler: Dừng")
            self.scheduler_status_label.setStyleSheet("font-weight: bold; color: #c62828;")

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        header = QLabel("Automation Workflow")
        header.setStyleSheet("font-size: 18px; font-weight: bold;")
        main_layout.addWidget(header)

        self.scheduler_status_label = QLabel("Scheduler: kiểm tra...")
        self.scheduler_status_label.setStyleSheet("font-weight: bold; color: #555;")
        main_layout.addWidget(self.scheduler_status_label)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Tìm action...")
        self.search_edit.textChanged.connect(self.filter_toolbox)
        main_layout.addWidget(self.search_edit)

        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter, 1)

        toolbox_panel = QFrame()
        toolbox_panel.setFrameShape(QFrame.StyledPanel)
        toolbox_layout = QVBoxLayout(toolbox_panel)
        toolbox_layout.setContentsMargins(8, 8, 8, 8)
        toolbox_layout.setSpacing(8)

        toolbox_label = QLabel("Toolbox")
        toolbox_label.setStyleSheet("font-weight: bold;")
        toolbox_layout.addWidget(toolbox_label)

        self.toolbox_list = QListWidget()
        self.toolbox_list.setFixedWidth(180)
        self.toolbox_list.addItems([name for name, _ in self.ACTIONS])
        self.toolbox_list.setCurrentRow(0)
        self.toolbox_list.currentItemChanged.connect(self.on_toolbox_selection_changed)
        toolbox_layout.addWidget(self.toolbox_list, 1)

        workflow_panel = QFrame()
        workflow_panel.setFrameShape(QFrame.StyledPanel)
        workflow_layout = QVBoxLayout(workflow_panel)
        workflow_layout.setContentsMargins(8, 8, 8, 8)
        workflow_layout.setSpacing(8)

        workflow_label = QLabel("Workflow")
        workflow_label.setStyleSheet("font-weight: bold;")
        workflow_layout.addWidget(workflow_label)

        self.workflow_list = WorkflowListWidget(self)
        self.workflow_list.currentItemChanged.connect(self.on_workflow_selection_changed)
        workflow_layout.addWidget(self.workflow_list, 1)

        buttons_layout = QHBoxLayout()
        add_btn = QPushButton("+ Add Step")
        add_btn.clicked.connect(self.add_current_step)
        buttons_layout.addWidget(add_btn)
        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(self.remove_current_step)
        buttons_layout.addWidget(remove_btn)
        workflow_layout.addLayout(buttons_layout)

        properties_panel = QFrame()
        properties_panel.setFrameShape(QFrame.StyledPanel)
        properties_layout = QVBoxLayout(properties_panel)
        properties_layout.setContentsMargins(8, 8, 8, 8)
        properties_layout.setSpacing(8)

        properties_title = QLabel("Properties")
        properties_title.setStyleSheet("font-weight: bold;")
        properties_layout.addWidget(properties_title)

        self.action_name_label = QLabel(self.selected_action)
        self.action_name_label.setStyleSheet("font-size: 13px; color: #2563eb;")
        properties_layout.addWidget(self.action_name_label)

        self.properties_form = QFormLayout()
        self.properties_form.setSpacing(8)

        jobs_title = QLabel("Jobs từ config.json")
        jobs_title.setStyleSheet("font-weight: bold;")
        properties_layout.addWidget(jobs_title)

        self.job_list_widget = QListWidget()
        self.job_list_widget.setFixedHeight(140)
        self.job_list_widget.itemClicked.connect(self.on_job_list_selected)
        properties_layout.addWidget(self.job_list_widget)

        new_job_row = QHBoxLayout()
        self.new_job_btn = QPushButton("Tạo job mới")
        self.new_job_btn.clicked.connect(self.create_new_job)
        new_job_row.addWidget(self.new_job_btn)
        new_job_row.addStretch(1)
        properties_layout.addLayout(new_job_row)

        self.job_name_edit = QLineEdit("new_job")
        self.properties_form.addRow("Job Name", self.job_name_edit)

        self.day_combo = QComboBox()
        self.day_combo.addItems([label for label, _ in WEEKDAY_OPTIONS])
        self.day_combo.setCurrentIndex(0)
        self.day_combo.currentIndexChanged.connect(self.on_day_changed)
        self.properties_form.addRow("Day", self.day_combo)

        self.start_edit = QLineEdit("08:00")
        self.properties_form.addRow("Start", self.start_edit)

        self.end_edit = QLineEdit("09:00")
        self.properties_form.addRow("End", self.end_edit)

        self.action_edit = QLineEdit(self.selected_action)
        self.action_edit.setReadOnly(True)
        self.properties_form.addRow("Action", self.action_edit)

        self.path_label = QLabel("Path")
        self.path_edit = QLineEdit()
        self.path_edit.textChanged.connect(lambda text: self.update_current_step("path", text))
        self.path_browse_btn = QPushButton("Browse")
        self.path_browse_btn.setFixedWidth(80)
        self.path_browse_btn.clicked.connect(self.on_browse_path)

        path_row_widget = QWidget()
        path_row_layout = QHBoxLayout(path_row_widget)
        path_row_layout.setContentsMargins(0, 0, 0, 0)
        path_row_layout.setSpacing(6)
        path_row_layout.addWidget(self.path_edit, 1)
        path_row_layout.addWidget(self.path_browse_btn)

        self.properties_form.addRow(self.path_label, path_row_widget)

        self.image_label = QLabel("Image")
        self.image_edit = QLineEdit()
        self.image_edit.textChanged.connect(lambda text: self.update_current_step("image", text))
        self.properties_form.addRow(self.image_label, self.image_edit)

        self.timeout_label = QLabel("Timeout")
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(0, 600)
        self.timeout_spin.setValue(10)
        self.timeout_spin.valueChanged.connect(lambda value: self.update_current_step("timeout", value))
        self.properties_form.addRow(self.timeout_label, self.timeout_spin)

        self.confidence_label = QLabel("Confidence")
        self.confidence_spin = QDoubleSpinBox()
        self.confidence_spin.setRange(0.0, 1.0)
        self.confidence_spin.setSingleStep(0.05)
        self.confidence_spin.setValue(0.8)
        self.confidence_spin.valueChanged.connect(lambda value: self.update_current_step("confidence", value))
        self.properties_form.addRow(self.confidence_label, self.confidence_spin)

        self.text_label = QLabel("Text")
        self.text_edit = QLineEdit()
        self.text_edit.textChanged.connect(lambda text: self.update_current_step("text", text))
        self.properties_form.addRow(self.text_label, self.text_edit)

        self.seconds_label = QLabel("Seconds")
        self.seconds_spin = QSpinBox()
        self.seconds_spin.setRange(0, 600)
        self.seconds_spin.setValue(1)
        self.seconds_spin.valueChanged.connect(lambda value: self.update_current_step("seconds", value))
        self.properties_form.addRow(self.seconds_label, self.seconds_spin)

        properties_layout.addLayout(self.properties_form)
        properties_layout.addStretch(1)

        images_panel = QFrame()
        images_panel.setFrameShape(QFrame.StyledPanel)
        images_layout = QVBoxLayout(images_panel)
        images_layout.setContentsMargins(8, 8, 8, 8)
        images_layout.setSpacing(8)

        images_title = QLabel("Images")
        images_title.setStyleSheet("font-weight: bold;")
        images_layout.addWidget(images_title)

        self.image_search_edit = QLineEdit()
        self.image_search_edit.setPlaceholderText("Tìm ảnh...")
        self.image_search_edit.textChanged.connect(self.refresh_images_list)
        images_layout.addWidget(self.image_search_edit)

        self.image_actions_row = QHBoxLayout()
        self.btn_capture_image = QPushButton("Chụp ảnh")
        self.btn_capture_image.clicked.connect(self.on_capture_image)
        self.image_actions_row.addWidget(self.btn_capture_image)

        self.btn_copy_image_path = QPushButton("Copy path")
        self.btn_copy_image_path.clicked.connect(self.on_copy_selected_image_path)
        self.image_actions_row.addWidget(self.btn_copy_image_path)

        self.btn_test_image = QPushButton("Test ảnh")
        self.btn_test_image.clicked.connect(self.on_test_selected_image)
        self.image_actions_row.addWidget(self.btn_test_image)

        self.image_actions_row.addStretch(1)
        images_layout.addLayout(self.image_actions_row)

        self.images_scroll = QScrollArea()
        self.images_scroll.setWidgetResizable(True)
        self.images_scroll.setFrameShape(QFrame.NoFrame)
        self.images_content = QWidget()
        self.images_layout = QVBoxLayout(self.images_content)
        self.images_layout.setContentsMargins(0, 0, 0, 0)
        self.images_layout.setSpacing(6)
        self.images_layout.setAlignment(Qt.AlignTop)
        self.images_scroll.setWidget(self.images_content)
        images_layout.addWidget(self.images_scroll, 1)

        splitter.addWidget(toolbox_panel)
        splitter.addWidget(workflow_panel)
        splitter.addWidget(properties_panel)
        splitter.addWidget(images_panel)

        buttons_row = QHBoxLayout()
        ok_btn = QPushButton("Save")
        ok_btn.clicked.connect(self.accept)
        buttons_row.addStretch(1)
        buttons_row.addWidget(ok_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        buttons_row.addWidget(cancel_btn)
        main_layout.addLayout(buttons_row)

        self.refresh_workflow_list()
        self.refresh_images_list()
        self.refresh_properties_for_action(self.selected_action_key)

    def accept(self):
        job_name = self.job_name_edit.text().strip()
        if not job_name:
            QMessageBox.warning(self, "Set Job", "Vui lòng nhập tên job.")
            return

        self.save_current_step_to_workflow()
        self.workflow_data = [self.normalize_workflow_step(step) for step in self.workflow_steps]
        if self.save_to_config(job_name):
            self.selected_job_name = job_name
            self.refresh_job_list()
            self.load_job_by_name(job_name)
            try:
                trigger_scheduler_reload()
            except Exception:
                pass
            return

    def save_current_step_to_workflow(self):
        row = self.workflow_list.currentRow()
        if 0 <= row < len(self.workflow_steps):
            self.workflow_steps[row] = self.build_current_step()

    def normalize_workflow_step(self, step):
        action = str(step.get("action") or self.selected_action_key or "").strip()
        normalized = {"action": action}

        if action in {"open_app", "close_app"}:
            normalized["path"] = normalize_app_path(step.get("path"))
        elif action in {"click_image", "wait_image"}:
            normalized["image"] = str(step.get("image") or "").strip()
            normalized["timeout"] = int(step.get("timeout", 10) or 10)
            normalized["confidence"] = float(step.get("confidence", 0.8) or 0.8)
        elif action == "paste":
            normalized["text"] = str(step.get("text") or "")
        elif action == "sleep":
            normalized["seconds"] = int(step.get("seconds", 1) or 1)

        return normalized

    def save_to_config(self, job_name):
        config_path = self.config_path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        try:
            config = load_config_file(config_path)
        except Exception as exc:
            QMessageBox.warning(self, "Set Job", f"Không đọc được config.json:\n{exc}")
            return False

        schedule = config.setdefault("schedule", {})
        day_cfg = schedule.setdefault(self.selected_day_key, {})
        day_cfg[job_name] = {
            "start": self.start_edit.text().strip() or "08:00",
            "end": self.end_edit.text().strip() or "09:00",
            "workflow": self.workflow_data,
        }

        try:
            save_config_file(config_path, config)
        except Exception as exc:
            QMessageBox.warning(self, "Set Job", f"Không lưu được vào config.json:\n{exc}")
            return False

        QMessageBox.information(self, "Set Job", f"Đã lưu job '{job_name}' vào config.json")
        return True

    def refresh_job_list(self):
        self.job_names = get_job_function_names(self.config_path)
        self.job_list_widget.blockSignals(True)
        self.job_list_widget.clear()
        if self.job_names:
            for job_name in self.job_names:
                row_widget = JobListRow(
                    job_name,
                    on_test=self.on_test_job_clicked,
                    on_delete=self.on_delete_job_clicked,
                )
                item = QListWidgetItem(self.job_list_widget)
                item.setSizeHint(row_widget.sizeHint())
                self.job_list_widget.setItemWidget(item, row_widget)
        else:
            item = QListWidgetItem("(Chưa có job)")
            self.job_list_widget.addItem(item)
        if self.selected_job_name and self.selected_job_name in self.job_names:
            for index in range(self.job_list_widget.count()):
                item = self.job_list_widget.item(index)
                widget = self.job_list_widget.itemWidget(item)
                if widget is not None and getattr(widget, "job_name", "") == self.selected_job_name:
                    self.job_list_widget.setCurrentRow(index)
                    break
        elif self.job_names:
            self.job_list_widget.setCurrentRow(0)
        self.job_list_widget.blockSignals(False)

    def on_job_list_selected(self):
        selected_item = self.job_list_widget.currentItem()
        if not selected_item:
            return
        widget = self.job_list_widget.itemWidget(selected_item)
        if widget is not None:
            job_name = getattr(widget, "job_name", "")
        else:
            job_name = selected_item.text().strip()
        if not job_name or job_name == "(Chưa có job)":
            return
        self.load_job_by_name(job_name)

    def on_test_job_clicked(self, job_name):
        if not job_name:
            return
        self.load_job_by_name(job_name)
        self.save_current_step_to_workflow()
        self.workflow_data = [self.normalize_workflow_step(step) for step in self.workflow_steps]
        try:
            from auto import execute_workflow
            execute_workflow(self.workflow_data)
            QMessageBox.information(self, "Test Job", f"Đã chạy thử job '{job_name}'")
        except Exception as exc:
            QMessageBox.warning(self, "Test Job", f"Không thể chạy thử job '{job_name}':\n{exc}")

    def on_delete_job_clicked(self, job_name):
        if not job_name:
            return
        reply = QMessageBox.question(
            self,
            "Xóa job",
            f"Xóa job '{job_name}' khỏi config.json?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            config = load_config_file(self.config_path)
        except Exception as exc:
            QMessageBox.warning(self, "Xóa job", f"Không đọc được config.json:\n{exc}")
            return

        schedule = config.setdefault("schedule", {})
        removed = False
        for day_key, day_cfg in schedule.items():
            if isinstance(day_cfg, dict) and job_name in day_cfg:
                del day_cfg[job_name]
                removed = True
                break

        if not removed:
            QMessageBox.warning(self, "Xóa job", f"Không tìm thấy job '{job_name}' để xóa.")
            return

        try:
            save_config_file(self.config_path, config)
            trigger_scheduler_reload()
        except Exception as exc:
            QMessageBox.warning(self, "Xóa job", f"Không thể xóa job:\n{exc}")
            return

        QMessageBox.information(self, "Xóa job", f"Đã xóa job '{job_name}' khỏi config.json.")
        self.selected_job_name = ""
        self.selected_job_config = None
        self.job_name_edit.setText("new_job")
        self.workflow_steps = []
        self.workflow_data = []
        self.refresh_job_list()
        self.refresh_workflow_list()
        self.refresh_properties_for_action(self.selected_action_key)

    def create_new_job(self):
        self.selected_job_name = ""
        self.selected_job_config = None
        self.job_name_edit.setText("new_job")
        self.job_name_edit.selectAll()
        self.day_combo.setCurrentIndex(0)
        self.start_edit.setText("08:00")
        self.end_edit.setText("09:00")
        self.workflow_steps = []
        self.refresh_workflow_list()
        self.refresh_properties_for_action(self.selected_action_key)
        self.job_list_widget.clearSelection()

    def load_job_by_name(self, job_name):
        if not job_name:
            return
        self.selected_job_name = job_name
        self.job_name_edit.setText(job_name)
        config = load_config_file(self.config_path)
        schedule = config.get("schedule", {})
        found_day_key = None
        found_job_cfg = None
        for day_key, day_cfg in schedule.items():
            if not isinstance(day_cfg, dict):
                continue
            job_cfg = day_cfg.get(job_name)
            if isinstance(job_cfg, dict):
                found_day_key = str(day_key)
                found_job_cfg = job_cfg
                break

        if found_job_cfg is None:
            self.selected_job_config = None
            self.workflow_steps = []
            self.refresh_workflow_list()
            self.refresh_properties_for_action(self.selected_action_key)
            return

        self.selected_job_config = found_job_cfg
        self.selected_day_key = found_day_key or self.selected_day_key
        self.day_combo.setCurrentIndex(int(self.selected_day_key) if self.selected_day_key.isdigit() and 0 <= int(self.selected_day_key) <= 6 else 0)
        self.start_edit.setText(found_job_cfg.get("start", "08:00"))
        self.end_edit.setText(found_job_cfg.get("end", "09:00"))

        self.workflow_steps = []
        for step in found_job_cfg.get("workflow", []):
            action = step.get("action", "")
            display_name = self.get_action_display_name(action)
            if action in {"open_app", "close_app"}:
                self.workflow_steps.append({
                    "name": display_name,
                    "action": action,
                    "path": step.get("path", ""),
                    "image": "",
                    "timeout": 10,
                    "confidence": 0.8,
                    "text": "",
                    "seconds": 1,
                })
            elif action in {"click_image", "wait_image"}:
                self.workflow_steps.append({
                    "name": display_name,
                    "action": action,
                    "path": "",
                    "image": step.get("image", ""),
                    "timeout": int(step.get("timeout", 10) or 10),
                    "confidence": float(step.get("confidence", 0.8) or 0.8),
                    "text": "",
                    "seconds": 1,
                })
            elif action == "paste":
                self.workflow_steps.append({
                    "name": display_name,
                    "action": action,
                    "path": "",
                    "image": "",
                    "timeout": 10,
                    "confidence": 0.8,
                    "text": step.get("text", ""),
                    "seconds": 1,
                })
            elif action == "sleep":
                self.workflow_steps.append({
                    "name": display_name,
                    "action": action,
                    "path": "",
                    "image": "",
                    "timeout": 10,
                    "confidence": 0.8,
                    "text": "",
                    "seconds": int(step.get("seconds", 1) or 1),
                })
            else:
                self.workflow_steps.append({
                    "name": display_name or action,
                    "action": action,
                    "path": "",
                    "image": "",
                    "timeout": 10,
                    "confidence": 0.8,
                    "text": "",
                    "seconds": 1,
                })

        self.refresh_workflow_list()
        if self.workflow_steps:
            self.workflow_list.setCurrentRow(0)
            self.on_workflow_selection_changed(self.workflow_list.item(0), None)
        else:
            self.refresh_properties_for_action(self.selected_action_key)

    def get_action_display_name(self, action_key):
        for name, key in self.ACTIONS:
            if key == action_key:
                return name
        return action_key or ""

    def on_day_changed(self, index):
        self.selected_day_key = str(index)

    def filter_toolbox(self, text):
        search = text.lower().strip()
        for index in range(self.toolbox_list.count()):
            item = self.toolbox_list.item(index)
            item.setHidden(search and search not in item.text().lower())

    def refresh_workflow_list(self, preserve_row=None):
        self.workflow_list.clear()
        for index, step in enumerate(self.workflow_steps, start=1):
            display_name = step.get("name") or self.selected_action
            item = QListWidgetItem(f"{index}. {display_name}")
            item.setData(Qt.UserRole, step)
            self.workflow_list.addItem(item)
        if self.workflow_steps:
            target_row = 0
            if preserve_row is not None:
                target_row = max(0, min(int(preserve_row), self.workflow_list.count() - 1))
            self.workflow_list.setCurrentRow(target_row)

    def reorder_workflow_steps(self):
        reordered = []
        for index in range(self.workflow_list.count()):
            item = self.workflow_list.item(index)
            if item is None:
                continue
            step = item.data(Qt.UserRole)
            if isinstance(step, dict):
                reordered.append(step)
        if len(reordered) != len(self.workflow_steps):
            return
        current_row = self.workflow_list.currentRow()
        self.workflow_steps = reordered
        self.refresh_workflow_list(preserve_row=current_row)

    def refresh_properties_for_action(self, action_key):
        is_path_action = action_key in {"open_app", "close_app"}
        is_image_action = action_key in {"click_image", "wait_image"}
        is_paste_action = action_key == "paste"
        is_sleep_action = action_key == "sleep"

        self.set_row_visible(self.path_label, self.path_browse_btn, is_path_action)
        self.path_edit.setVisible(is_path_action)
        self.path_browse_btn.setVisible(is_path_action)
        self.set_row_visible(self.image_label, self.image_edit, is_image_action)
        self.set_row_visible(self.timeout_label, self.timeout_spin, is_image_action)
        self.set_row_visible(self.confidence_label, self.confidence_spin, is_image_action)
        self.set_row_visible(self.text_label, self.text_edit, is_paste_action)
        self.set_row_visible(self.seconds_label, self.seconds_spin, is_sleep_action)

    def set_row_visible(self, label, widget, visible):
        label.setVisible(visible)
        widget.setVisible(visible)

    def on_toolbox_selection_changed(self, current, previous):
        if current is None:
            return
        self.selected_action = current.text()
        self.selected_action_key = self.get_action_key(self.selected_action)
        self.action_name_label.setText(self.selected_action)
        self.action_edit.setText(self.selected_action)
        self.refresh_properties_for_action(self.selected_action_key)

    def on_workflow_selection_changed(self, current, previous):
        if current is None:
            return
        row = self.workflow_list.currentRow()
        if 0 <= row < len(self.workflow_steps):
            step = self.workflow_steps[row]
            self.selected_action = step.get("name", self.selected_action)
            self.selected_action_key = step.get("action", self.get_action_key(self.selected_action))
            self.action_edit.setText(self.selected_action)
            self.action_name_label.setText(self.selected_action)
            self.path_edit.setText(step.get("path", ""))
            self.image_edit.setText(step.get("image", ""))
            self.timeout_spin.setValue(int(step.get("timeout", 10)))
            self.confidence_spin.setValue(float(step.get("confidence", 0.8)))
            self.text_edit.setText(step.get("text", ""))
            self.seconds_spin.setValue(int(step.get("seconds", 1)))
            self.refresh_properties_for_action(self.selected_action_key)

    def on_browse_path(self):
        if self.selected_action_key not in {"open_app", "close_app"}:
            return

        start_dir = self.path_edit.text().strip() or os.path.expanduser("~")
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn file thực thi",
            start_dir,
            "Executables (*.exe);;All files (*)"
        )
        if file_path:
            self.path_edit.setText(file_path)
            self.update_current_step("path", file_path)

    def add_current_step(self):
        step = self.build_current_step()
        self.workflow_steps.append(step)
        self.refresh_workflow_list()
        self.workflow_list.setCurrentRow(len(self.workflow_steps) - 1)

    def remove_current_step(self):
        row = self.workflow_list.currentRow()
        if 0 <= row < len(self.workflow_steps):
            del self.workflow_steps[row]
            self.refresh_workflow_list()

    def build_current_step(self):
        return {
            "name": self.selected_action,
            "action": self.selected_action_key,
            "path": self.path_edit.text().strip(),
            "image": self.image_edit.text().strip(),
            "timeout": self.timeout_spin.value(),
            "confidence": self.confidence_spin.value(),
            "text": self.text_edit.text(),
            "seconds": self.seconds_spin.value(),
        }

    def update_current_step(self, key, value):
        row = self.workflow_list.currentRow()
        if 0 <= row < len(self.workflow_steps):
            step = self.workflow_steps[row]
            step["name"] = self.selected_action
            step["action"] = self.selected_action_key
            step[key] = value

    def refresh_images_list(self, text=None):
        while self.images_layout.count():
            item = self.images_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        search = (text or self.image_search_edit.text() or "").lower().strip()
        images_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Images")
        if not os.path.isdir(images_dir):
            empty_label = QLabel("Chưa có ảnh nào trong thư mục Images")
            empty_label.setStyleSheet("color: #777;")
            self.images_layout.addWidget(empty_label)
            return

        files = []
        valid_ext = (".png", ".jpg", ".jpeg", ".bmp", ".gif")
        for filename in os.listdir(images_dir):
            if filename.lower().endswith(valid_ext):
                if search and search not in filename.lower():
                    continue
                files.append(os.path.join(images_dir, filename))

        if not files:
            empty_label = QLabel("Không tìm thấy ảnh phù hợp")
            empty_label.setStyleSheet("color: #777;")
            self.images_layout.addWidget(empty_label)
            return

        files.sort(key=lambda p: os.path.getmtime(p), reverse=True)

        for file_path in files:
            row = ImageFileRow(file_path)
            row.clicked.connect(lambda checked=False, path=file_path, row=row: self.on_image_row_clicked(path, row))
            row.double_clicked.connect(self.on_image_double_clicked)
            row.delete_clicked.connect(self.on_delete_image_from_setjob)
            self.images_layout.addWidget(row)

    def on_image_double_clicked(self, file_path):
        self.assign_image_to_current_step(file_path)

    def on_image_row_clicked(self, file_path, row):
        self.selected_image_path = file_path
        self._highlight_selected_image_row(row)

    def _highlight_selected_image_row(self, selected_row):
        for i in range(self.images_layout.count()):
            item = self.images_layout.itemAt(i)
            widget = item.widget()
            if isinstance(widget, ImageFileRow):
                widget.set_selected(widget is selected_row)

    def _get_selected_image_path(self):
        if self.selected_image_path and os.path.isfile(self.selected_image_path):
            return self.selected_image_path
        return self.image_edit.text().strip()

    def assign_image_to_current_step(self, file_path):
        row = self.workflow_list.currentRow()
        if 0 <= row < len(self.workflow_steps):
            self.workflow_steps[row]["image"] = file_path
            self.image_edit.setText(file_path)
            QMessageBox.information(self, "Set Job", f"Đã gán ảnh cho bước hiện tại:\n{os.path.basename(file_path)}")

    def on_capture_image(self):
        # Reuse the main window capture overlay behavior inside Set Job
        self.hide()
        self.capture_overlay = SelectionOverlay(self.on_capture_image_selected)
        self.capture_overlay.showFullScreen()

    def on_capture_image_selected(self, rect):
        self.show()
        self.raise_()
        if rect is None or rect.width() == 0 or rect.height() == 0:
            QMessageBox.information(self, "Set Job", "Đã hủy chọn ảnh.")
            return
        screen = QApplication.primaryScreen()
        pixmap = screen.grabWindow(0, rect.x(), rect.y(), rect.width(), rect.height())
        if pixmap.isNull():
            QMessageBox.warning(self, "Set Job", "Chụp ảnh thất bại.")
            return

        self.captured_rect = rect
        self.save_captured_image_for_setjob(pixmap)

    def save_captured_image_for_setjob(self, pixmap):
        images_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Images")
        try:
            os.makedirs(images_dir, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self, "Lưu ảnh", f"Không thể tạo thư mục Images:\n{e}")
            return

        default_base = f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        coords_str = ""
        if hasattr(self, "captured_rect") and self.captured_rect is not None:
            r = self.captured_rect
            x = max(0, r.x() - 10)
            y = max(0, r.y() - 10)
            w = r.width() + 20
            h = r.height() + 20
            coords_str = f"{x}_{y}_{w}_{h}"

        name, ok = QInputDialog.getText(
            self,
            "Lưu ảnh",
            "Nhập tên file (không cần đuôi .png):",
            text=default_base,
        )
        if not ok or not name.strip():
            return

        name = name.strip()
        if name.lower().endswith('.png'):
            name = name[:-4]

        name = sanitize_filename_part(name)
        final_name = f"{name}.png" if not coords_str else f"{name}={coords_str}=.png"
        save_path = os.path.join(images_dir, final_name)

        if os.path.exists(save_path):
            reply = QMessageBox.question(
                self,
                "File đã tồn tại",
                f"File \"{final_name}\" đã tồn tại. Bạn có muốn ghi đè không?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        if pixmap.save(save_path, "PNG"):
            QMessageBox.information(self, "Set Job", f"Đã lưu ảnh vào:\n{save_path}")
            self.refresh_images_list()
            self.assign_image_to_current_step(save_path)
        else:
            QMessageBox.warning(self, "Set Job", "Không thể lưu ảnh.")

    def on_copy_selected_image_path(self):
        path = self._get_selected_image_path()
        if path:
            QApplication.clipboard().setText(path)
            QMessageBox.information(self, "Set Job", "Đã copy đường dẫn ảnh.")
        else:
            QMessageBox.information(self, "Set Job", "Chưa chọn ảnh để copy.")

    def on_delete_image_from_setjob(self, file_path):
        reply = QMessageBox.question(
            self,
            "Xóa ảnh",
            f"Bạn có muốn xóa ảnh sau khỏi thư mục Images?\n{file_path}",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            os.remove(file_path)
        except OSError as e:
            QMessageBox.warning(self, "Xóa ảnh", f"Không thể xóa file:\n{e}")
            return

        # Nếu ảnh đang được chọn trong bước hiện tại, bỏ chọn luôn
        if self.image_edit.text().strip() == file_path:
            self.image_edit.clear()
            row = self.workflow_list.currentRow()
            if 0 <= row < len(self.workflow_steps):
                self.workflow_steps[row]["image"] = ""

        if self.selected_image_path == file_path:
            self.selected_image_path = ""
        self.refresh_images_list()

    def on_test_selected_image(self):
        path = self._get_selected_image_path()
        if not path or not os.path.isfile(path):
            QMessageBox.information(self, "Set Job", "Chưa chọn ảnh hợp lệ để test.")
            return
        from auto import click_image

        self.hide()
        QTimer.singleShot(150, lambda: self._test_image_path(path, click_image))

    def _test_image_path(self, path, click_image_func):
        try:
            click_image_func(path)
            QMessageBox.information(self, "Set Job", "Test ảnh thành công.")
        except Exception as exc:
            QMessageBox.warning(self, "Set Job", f"Lỗi khi test ảnh:\n{exc}")
        finally:
            self.show()
            self.raise_()





def main():
    app = QApplication(sys.argv)
    window = SetJobDialog(None)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()