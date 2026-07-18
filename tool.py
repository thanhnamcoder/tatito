import sys
import os
import json
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication,
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
    QFormLayout,
    QTimeEdit,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
)
from PyQt5.QtCore import Qt, QPoint, QRect, QSize, QTimer, QThread, pyqtSignal, QTime
from PyQt5.QtGui import QPainter, QColor, QKeySequence, QPixmap, QIntValidator
from auto import click_image as auto_click_image, trigger_scheduler_reload, Job
import re
import unicodedata
import inspect


def get_job_function_names():
    """
    Lấy danh sách tên các hàm (method) công khai được định nghĩa trong
    class Job (auto.py). Đây là các tên job hợp lệ có thể gán vào lịch,
    vì scheduler() sẽ tìm hàm cùng tên để chạy.
    """
    names = []
    for name, member in inspect.getmembers(Job, predicate=inspect.isfunction):
        if name.startswith("_"):
            continue
        names.append(name)
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


class PositionPickerOverlay(QWidget):
    """
    Cửa sổ overlay toàn màn hình, nền mờ, chờ người dùng click 1 lần.
    Click vào đâu sẽ lấy tọa độ chuột (tính theo tọa độ toàn màn hình) tại đó
    rồi gọi callback với QPoint đã click. Nhấn ESC để hủy (callback nhận None).
    """

    def __init__(self, on_finished):
        super().__init__()
        self.on_finished = on_finished

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)

        desktop = QApplication.desktop()
        full_geometry = QRect()
        for i in range(desktop.screenCount()):
            full_geometry = full_geometry.united(desktop.screenGeometry(i))
        self.setGeometry(full_geometry)

        self.esc_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self.esc_shortcut.activated.connect(self.cancel_pick)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 90))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # globalPos vẫn đúng khi overlay phủ nhiều màn hình
            global_pos = event.globalPos()
            self.close()
            if self.on_finished:
                self.on_finished(global_pos)

    def cancel_pick(self):
        self.close()
        if self.on_finished:
            self.on_finished(None)


class ClickTestThread(QThread):
    """
    Chạy auto_click_image() ở luồng riêng để không làm treo giao diện
    (vì click_image có thể chờ/lặp trong nhiều giây).
    """

    finished_signal = pyqtSignal(bool, str)

    def __init__(self, image_path):
        super().__init__()
        self.image_path = image_path

    def run(self):
        try:
            result = auto_click_image(self.image_path, timeout=5)
            self.finished_signal.emit(bool(result), "")
        except Exception as e:
            self.finished_signal.emit(False, str(e))


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


class TimePickerWidget(QWidget):
    """
    Chọn giờ:phút bằng 2 dropdown (Giờ 00-23, Phút 00-59). So với QTimeEdit
    (phải bấm mũi tên tăng/giảm nhiều lần), cách này cho phép:
    - Click mở danh sách rồi chọn thẳng giá trị cần, hoặc
    - Gõ số để nhảy nhanh tới giờ/phút mong muốn.
    Vẫn giữ được độ chính xác tới từng phút (không giới hạn theo mốc 5/15 phút).
    """

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.hour_combo = QComboBox(self)
        self.hour_combo.setEditable(True)
        self.hour_combo.setInsertPolicy(QComboBox.NoInsert)
        self.hour_combo.addItems([f"{h:02d}" for h in range(24)])
        self.hour_combo.setValidator(QIntValidator(0, 23, self.hour_combo))
        self.hour_combo.setFixedWidth(52)
        self.hour_combo.setMaxVisibleItems(12)

        colon_label = QLabel(":")
        colon_label.setFixedWidth(8)
        colon_label.setAlignment(Qt.AlignCenter)

        self.minute_combo = QComboBox(self)
        self.minute_combo.setEditable(True)
        self.minute_combo.setInsertPolicy(QComboBox.NoInsert)
        self.minute_combo.addItems([f"{m:02d}" for m in range(60)])
        self.minute_combo.setValidator(QIntValidator(0, 59, self.minute_combo))
        self.minute_combo.setFixedWidth(52)
        self.minute_combo.setMaxVisibleItems(12)

        layout.addWidget(self.hour_combo)
        layout.addWidget(colon_label)
        layout.addWidget(self.minute_combo)

        self.now_btn = QPushButton("Now", self)
        self.now_btn.setToolTip("Chọn giờ:phút hiện tại")
        self.now_btn.setFixedWidth(40)
        self.now_btn.clicked.connect(self.set_to_now)
        layout.addWidget(self.now_btn)

        layout.addStretch(1)

        self.hour_combo.currentIndexChanged.connect(self.changed.emit)
        self.minute_combo.currentIndexChanged.connect(self.changed.emit)

    def _set_combo_value(self, combo, value):
        combo.blockSignals(True)
        try:
            idx = combo.findText(value)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            else:
                combo.setEditText(value)
        finally:
            combo.blockSignals(False)

    def set_to_now(self):
        now = QTime.currentTime()
        self._set_combo_value(self.hour_combo, f"{now.hour():02d}")
        self._set_combo_value(self.minute_combo, f"{now.minute():02d}")
        self.changed.emit()

    def set_time_str(self, text):
        t = QTime.fromString(text, "HH:mm") if text else QTime()
        if not t.isValid():
            t = QTime(8, 0)
        self._set_combo_value(self.hour_combo, f"{t.hour():02d}")
        self._set_combo_value(self.minute_combo, f"{t.minute():02d}")

    def time_str(self):
        try:
            hour = int(self.hour_combo.currentText())
        except ValueError:
            hour = 0
        try:
            minute = int(self.minute_combo.currentText())
        except ValueError:
            minute = 0
        hour = max(0, min(23, hour))
        minute = max(0, min(59, minute))
        return f"{hour:02d}:{minute:02d}"


class DayScheduleWidget(QWidget):
    """
    Widget hiển thị và chỉnh sửa danh sách job cho MỘT ngày cụ thể, dưới dạng
    bảng (tên job / giờ bắt đầu / giờ kết thúc / nút xóa) để dễ nhìn và sửa
    trực tiếp, thay vì phải chọn từng job trong danh sách rồi gõ lại form.
    """

    COL_NAME = 0
    COL_START = 1
    COL_END = 2
    COL_ACTION = 3

    def __init__(self, day_key, job_names=None, on_change=None, parent=None):
        super().__init__(parent)
        self.day_key = day_key
        self.on_change = on_change
        self.job_names = job_names or []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(
            ["Tên job", "Bắt đầu", "Kết thúc", ""]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(
            QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed
        )

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(self.COL_NAME, QHeaderView.Stretch)
        header.setSectionResizeMode(self.COL_START, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_END, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_ACTION, QHeaderView.ResizeToContents)

        layout.addWidget(self.table, 1)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ Thêm job")
        add_btn.clicked.connect(self.on_add_clicked)
        btn_row.addWidget(add_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

    def _notify_change(self):
        if self.on_change:
            self.on_change()

    def on_add_clicked(self):
        if not self.job_names:
            QMessageBox.warning(
                self,
                "Thêm job",
                "Không tìm thấy hàm nào trong class Job (auto.py) để chọn.\n"
                "Hãy thêm method vào class Job rồi thử lại.",
            )
            return
        self.add_row()

    def add_row(self, name="", start="08:00", end="09:00"):
        row = self.table.rowCount()
        self.table.insertRow(row)

        name_combo = QComboBox(self.table)
        name_combo.setEditable(False)
        if self.job_names:
            name_combo.addItems(self.job_names)
        else:
            name_combo.addItem("(Không có hàm nào trong class Job)")
            name_combo.setEnabled(False)

        if name:
            idx = name_combo.findText(name)
            if idx >= 0:
                name_combo.setCurrentIndex(idx)
            else:
                # Tên job đã lưu trước đó không còn khớp hàm nào trong class Job
                # hiện tại -> vẫn thêm vào combobox để không làm mất dữ liệu cũ.
                name_combo.addItem(name)
                name_combo.setCurrentIndex(name_combo.count() - 1)
        elif self.job_names:
            name_combo.setCurrentIndex(0)

        name_combo.currentIndexChanged.connect(self._notify_change)
        self.table.setCellWidget(row, self.COL_NAME, name_combo)

        start_widget = TimePickerWidget(self.table)
        start_widget.set_time_str(start)
        start_widget.changed.connect(self._notify_change)
        self.table.setCellWidget(row, self.COL_START, start_widget)

        end_widget = TimePickerWidget(self.table)
        end_widget.set_time_str(end)
        end_widget.changed.connect(self._notify_change)
        self.table.setCellWidget(row, self.COL_END, end_widget)

        remove_btn = QPushButton("Xóa")
        remove_btn.setFixedWidth(60)
        remove_btn.clicked.connect(
            lambda checked=False, btn=remove_btn: self.remove_row_by_widget(btn)
        )
        self.table.setCellWidget(row, self.COL_ACTION, remove_btn)

        self.table.scrollToBottom()
        self._notify_change()
        return row

    def remove_row_by_widget(self, widget):
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, self.COL_ACTION) is widget:
                self.table.removeRow(row)
                break
        self._notify_change()

    def clear_rows(self):
        self.table.setRowCount(0)

    def load_jobs(self, day_cfg):
        self.clear_rows()
        for job_name in sorted(day_cfg.keys()):
            cfg = day_cfg[job_name]
            self.add_row(job_name, cfg.get("start", "08:00"), cfg.get("end", "09:00"))
        self._notify_change()

    def collect_jobs(self):
        """
        Trả về (dict_jobs, list_loi).
        Các dòng chưa đặt tên sẽ được bỏ qua (không tính là lỗi).
        Tên job trùng nhau trong cùng 1 ngày sẽ được báo lỗi.
        """
        jobs = {}
        errors = []
        for row in range(self.table.rowCount()):
            name_combo = self.table.cellWidget(row, self.COL_NAME)
            name = name_combo.currentText().strip() if name_combo and name_combo.isEnabled() else ""
            if not name:
                continue

            start_widget = self.table.cellWidget(row, self.COL_START)
            end_widget = self.table.cellWidget(row, self.COL_END)
            start = start_widget.time_str() if start_widget else "00:00"
            end = end_widget.time_str() if end_widget else "00:00"

            if name in jobs:
                errors.append(f"Tên job \"{name}\" bị trùng lặp.")
                continue

            jobs[name] = {"start": start, "end": end}
        return jobs, errors

    def job_count(self):
        count = 0
        for row in range(self.table.rowCount()):
            name_combo = self.table.cellWidget(row, self.COL_NAME)
            if name_combo and name_combo.isEnabled() and name_combo.currentText().strip():
                count += 1
        return count


class ConfigEditorDialog(QDialog):
    """
    Giao diện chỉnh cấu hình lịch, được thiết kế lại để dễ dùng hơn:
    - Mỗi ngày trong tuần là 1 tab riêng (thay vì phải chọn ngày trong combobox
      rồi mới thấy job của ngày đó), số job trong ngày hiển thị ngay trên tab.
    - Job của từng ngày hiển thị dạng bảng, sửa tên/giờ trực tiếp trên bảng,
      không cần chọn job rồi gõ lại vào form riêng.
    - Có thể sao chép nhanh lịch từ 1 ngày sang ngày đang mở (rất hữu ích khi
      nhiều ngày có lịch giống nhau).
    """

    def __init__(self, parent, config_path):
        super().__init__(parent)
        self.config_path = config_path
        self.setWindowTitle("Cấu hình lịch")
        self.resize(860, 580)

        self.schedule_data = load_config_file(config_path)
        if not isinstance(self.schedule_data, dict):
            self.schedule_data = build_default_schedule()
        if "schedule" not in self.schedule_data or not isinstance(self.schedule_data["schedule"], dict):
            self.schedule_data["schedule"] = {}

        layout = QVBoxLayout(self)

        self.job_names = get_job_function_names()

        info_label = QLabel(
            "Mỗi tab bên dưới là 1 ngày trong tuần. Nhấn \"+ Thêm job\" để thêm job mới, "
            "chọn tên job trong danh sách các hàm có sẵn trong class Job (auto.py), "
            "chọn giờ trực tiếp bằng ô giờ, và nhấn \"Xóa\" ở cuối dòng để xóa job."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("padding: 6px; background: #f5f5f5; border-radius: 4px;")
        layout.addWidget(info_label)

        # --- Khu vực sao chép lịch giữa các ngày ---
        copy_row = QHBoxLayout()
        copy_row.addWidget(QLabel("Sao chép lịch từ:"))
        self.copy_source_combo = QComboBox(self)
        for label, value in WEEKDAY_OPTIONS:
            self.copy_source_combo.addItem(label, value)
        copy_row.addWidget(self.copy_source_combo)

        copy_row.addWidget(QLabel("→ sang tab đang mở (sẽ thay thế lịch hiện tại)"))
        copy_btn = QPushButton("Sao chép")
        copy_btn.clicked.connect(self.on_copy_from_day)
        copy_row.addWidget(copy_btn)
        copy_row.addStretch(1)
        layout.addLayout(copy_row)

        # --- Tabs cho từng ngày ---
        self.tabs = QTabWidget(self)
        self.day_widgets = {}
        for label, day_key in WEEKDAY_OPTIONS:
            day_widget = DayScheduleWidget(
                day_key,
                job_names=self.job_names,
                on_change=self.update_tab_titles,
                parent=self,
            )
            day_cfg = self.schedule_data.setdefault("schedule", {}).setdefault(day_key, {})
            day_widget.load_jobs(day_cfg)
            self.day_widgets[day_key] = day_widget
            self.tabs.addTab(day_widget, label)

        self.update_tab_titles()
        layout.addWidget(self.tabs, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        save_btn = QPushButton("Lưu")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self.on_save)
        cancel_btn = QPushButton("Hủy")
        cancel_btn.clicked.connect(self.reject)
        button_row.addWidget(save_btn)
        button_row.addWidget(cancel_btn)
        layout.addLayout(button_row)

    def update_tab_titles(self):
        for index, (label, day_key) in enumerate(WEEKDAY_OPTIONS):
            widget = self.day_widgets.get(day_key)
            count = widget.job_count() if widget else 0
            suffix = f" ({count})" if count else ""
            self.tabs.setTabText(index, f"{label}{suffix}")

    def on_copy_from_day(self):
        source_key = self.copy_source_combo.currentData()
        target_index = self.tabs.currentIndex()
        target_label, target_key = WEEKDAY_OPTIONS[target_index]

        if source_key == target_key:
            QMessageBox.information(
                self, "Sao chép", "Ngày nguồn và ngày đích đang trùng nhau."
            )
            return

        target_widget = self.day_widgets[target_key]
        if target_widget.job_count() > 0:
            reply = QMessageBox.question(
                self,
                "Sao chép lịch",
                f"Tab \"{target_label}\" đang có job. Sao chép sẽ THAY THẾ toàn bộ "
                f"job hiện tại của tab này. Bạn có chắc muốn tiếp tục?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        source_widget = self.day_widgets[source_key]
        source_jobs, _ = source_widget.collect_jobs()
        target_widget.load_jobs(source_jobs)
        self.update_tab_titles()

    def on_save(self):
        new_schedule = {}
        all_errors = []
        for label, day_key in WEEKDAY_OPTIONS:
            jobs, errors = self.day_widgets[day_key].collect_jobs()
            new_schedule[day_key] = jobs
            for err in errors:
                all_errors.append(f"[{label}] {err}")

        if all_errors:
            QMessageBox.warning(
                self,
                "Cấu hình",
                "Vui lòng sửa các lỗi sau trước khi lưu:\n\n" + "\n".join(all_errors),
            )
            return

        self.schedule_data["schedule"] = new_schedule

        try:
            save_config_file(self.config_path, self.schedule_data)
            trigger_scheduler_reload()
        except Exception as e:
            QMessageBox.warning(self, "Cấu hình", f"Không thể lưu file:\n{e}")
            return

        QMessageBox.information(self, "Cấu hình", "Đã lưu cấu hình thành công.")
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("App")
        self.setMinimumSize(700, 400)
        self.overlay = None
        self.selected_rect = None
        self.captured_rect = None
        self.captured_pixmap = None
        self.captured_image_path = None
        self.mouse_position = None
        self.gallery_files = []  # keep current display order of filenames
        self.gallery_test_threads = []  # giữ tham chiếu các thread Test trong gallery
        self.active_test_count = 0  # đếm số lượt test đang chạy để ẩn/hiện cửa sổ đúng lúc
        self.config_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        self.init_ui()

    def init_ui(self):
        self.central_widget = QWidget(self)
        self.setCentralWidget(self.central_widget)
        self.create_toolbar()

        main_layout = QVBoxLayout(self.central_widget)

        # Left frame with buttons
        left_frame = QFrame(self)
        left_frame.setFrameShape(QFrame.StyledPanel)
        left_frame.setMinimumWidth(240)
        left_layout = QVBoxLayout(left_frame)
        left_layout.setContentsMargins(20, 20, 20, 20)
        left_layout.setSpacing(15)

        label = QLabel("Chức năng")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("font-size: 18px; font-weight: bold;")
        left_layout.addWidget(label)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)

        button_width = 130

        # --- Nút "Chọn vùng" + ô hiển thị kết quả bên dưới ---
        self.btn_select_area = QPushButton("Chọn vùng")
        self.btn_select_area.setFixedWidth(button_width)
        self.btn_select_area.clicked.connect(self.on_select_area)
        select_layout = QVBoxLayout()
        select_layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        select_layout.addWidget(self.btn_select_area, alignment=Qt.AlignHCenter)

        self.select_result_label = QLabel("Chưa chọn")
        self.select_result_label.setAlignment(Qt.AlignCenter)
        self.select_result_label.setWordWrap(True)
        self.select_result_label.setFrameShape(QFrame.Box)
        self.select_result_label.setFixedSize(button_width, 80)
        self.select_result_label.setStyleSheet("padding: 4px; font-size: 11px;")
        select_layout.addWidget(self.select_result_label, alignment=Qt.AlignHCenter)

        self.btn_copy_select = QPushButton("Copy")
        self.btn_copy_select.setFixedWidth(button_width)
        self.btn_copy_select.clicked.connect(self.on_copy_select)
        select_layout.addWidget(self.btn_copy_select, alignment=Qt.AlignHCenter)
        button_row.addLayout(select_layout)

        self.btn_capture_area = QPushButton("Chọn vùng chụp")
        self.btn_capture_area.setFixedWidth(button_width)
        self.btn_capture_area.clicked.connect(self.on_capture_area)
        capture_layout = QVBoxLayout()
        capture_layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        capture_layout.addWidget(self.btn_capture_area, alignment=Qt.AlignHCenter)

        self.capture_result_label = QLabel("Chưa chụp")
        self.capture_result_label.setAlignment(Qt.AlignCenter)
        self.capture_result_label.setWordWrap(True)
        self.capture_result_label.setFrameShape(QFrame.Box)
        self.capture_result_label.setFixedSize(button_width, 80)
        self.capture_result_label.setStyleSheet("padding: 4px; font-size: 11px;")
        capture_layout.addWidget(self.capture_result_label, alignment=Qt.AlignHCenter)

        copy_test_row = QHBoxLayout()
        copy_test_row.setSpacing(6)

        self.btn_copy_capture = QPushButton("Copy")
        self.btn_copy_capture.setFixedWidth((button_width - 6) // 2)
        self.btn_copy_capture.clicked.connect(self.on_copy_capture)
        copy_test_row.addWidget(self.btn_copy_capture)

        self.btn_test_capture = QPushButton("Test")
        self.btn_test_capture.setFixedWidth((button_width - 6) // 2)
        self.btn_test_capture.clicked.connect(self.on_test_capture)
        copy_test_row.addWidget(self.btn_test_capture)

        capture_layout.addLayout(copy_test_row)
        button_row.addLayout(capture_layout)

        self.btn_get_mouse_position = QPushButton("Lấy vị trí chuột")
        self.btn_get_mouse_position.setFixedWidth(button_width)
        self.btn_get_mouse_position.clicked.connect(self.on_get_mouse_position)
        mouse_layout = QVBoxLayout()
        mouse_layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        mouse_layout.addWidget(self.btn_get_mouse_position, alignment=Qt.AlignHCenter)

        self.mouse_result_label = QLabel("Chưa lấy")
        self.mouse_result_label.setAlignment(Qt.AlignCenter)
        self.mouse_result_label.setWordWrap(True)
        self.mouse_result_label.setFrameShape(QFrame.Box)
        self.mouse_result_label.setFixedSize(button_width, 80)
        self.mouse_result_label.setStyleSheet("padding: 4px; font-size: 11px;")
        mouse_layout.addWidget(self.mouse_result_label, alignment=Qt.AlignHCenter)

        self.btn_copy_mouse = QPushButton("Copy")
        self.btn_copy_mouse.setFixedWidth(button_width)
        self.btn_copy_mouse.clicked.connect(self.on_copy_mouse)
        mouse_layout.addWidget(self.btn_copy_mouse, alignment=Qt.AlignHCenter)
        button_row.addLayout(mouse_layout)

        left_layout.addLayout(button_row)
        left_layout.addStretch(1)

        # Right frame: hiển thị toàn bộ ảnh trong thư mục Images
        right_frame = QFrame(self)
        right_frame.setFrameShape(QFrame.StyledPanel)
        right_frame_layout = QVBoxLayout(right_frame)
        right_frame_layout.setContentsMargins(15, 15, 15, 15)
        right_frame_layout.setSpacing(10)

        gallery_title = QLabel("Ảnh trong thư mục Images")
        gallery_title.setStyleSheet("font-size: 16px; font-weight: bold;")
        right_frame_layout.addWidget(gallery_title)

        self.gallery_scroll = QScrollArea()
        self.gallery_scroll.setWidgetResizable(True)
        self.gallery_scroll.setFrameShape(QFrame.NoFrame)

        self.gallery_content = QWidget()
        self.gallery_layout = QVBoxLayout(self.gallery_content)
        self.gallery_layout.setSpacing(8)
        self.gallery_layout.setAlignment(Qt.AlignTop)

        self.gallery_scroll.setWidget(self.gallery_content)
        right_frame_layout.addWidget(self.gallery_scroll, 1)

        main_layout.addWidget(left_frame)
        main_layout.addWidget(right_frame, 1)

        self.refresh_images_gallery()

    def create_toolbar(self):
        toolbar = QToolBar("Công cụ")
        toolbar.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, toolbar)

        action_config = QAction("Config", self)
        action_config.setToolTip("Mở cửa sổ cấu hình lịch")
        action_config.triggered.connect(self.open_config_dialog)
        toolbar.addAction(action_config)

    def open_config_dialog(self):
        dialog = ConfigEditorDialog(self, self.config_file_path)
        dialog.exec_()

    def on_select_area(self):
        # Ẩn cửa sổ chính trước, đợi 1 chút cho hiệu ứng ẩn hoàn tất
        # rồi mới mở overlay chọn vùng (tránh overlay bị chụp/ảnh hưởng bởi cửa sổ chính).
        self.hide()
        QTimer.singleShot(150, self.start_selection)

    def start_selection(self):
        self.overlay = SelectionOverlay(self.on_area_selected)
        self.overlay.showFullScreen()

    def on_area_selected(self, rect):
        # Hiện lại cửa sổ chính sau khi chọn xong (hoặc hủy)
        self.show()
        self.raise_()
        self.activateWindow()

        if rect is None or rect.width() == 0 or rect.height() == 0:
            self.select_result_label.setText("Đã hủy chọn")
            self.selected_rect = None
            return

        self.selected_rect = rect
        text = (
            f"X: {rect.x()}, Y: {rect.y()}\n"
            f"W: {rect.width()}, H: {rect.height()}"
        )
        self.select_result_label.setText(text)

    def on_capture_area(self):
        # Ẩn cửa sổ chính trước, đợi 1 chút cho hiệu ứng ẩn hoàn tất
        # rồi mới mở overlay chọn vùng cần chụp.
        self.hide()
        QTimer.singleShot(150, self.start_capture_selection)

    def start_capture_selection(self):
        self.overlay = SelectionOverlay(self.on_capture_area_selected)
        self.overlay.showFullScreen()

    def on_capture_area_selected(self, rect):
        if rect is None or rect.width() == 0 or rect.height() == 0:
            self.show()
            self.raise_()
            self.activateWindow()
            self.capture_result_label.setText("Đã hủy chọn")
            return

        # store the captured rect so we can use its coords when saving
        self.captured_rect = rect

        # Đợi 1 chút để overlay biến mất hoàn toàn khỏi màn hình
        # (tránh chụp phải lớp phủ mờ / viền rubber band còn sót lại),
        # rồi mới thực sự chụp ảnh.
        QTimer.singleShot(100, lambda: self.grab_and_show_capture(rect))

    def grab_and_show_capture(self, rect):
        screen = QApplication.primaryScreen()
        pixmap = screen.grabWindow(
            0, rect.x(), rect.y(), rect.width(), rect.height()
        )

        # Sau khi chụp xong mới hiện lại cửa sổ chính
        self.show()
        self.raise_()
        self.activateWindow()

        if pixmap.isNull():
            self.capture_result_label.setText("Chụp thất bại")
            return

        self.captured_pixmap = pixmap
        self.display_capture_thumbnail(pixmap)
        self.save_captured_image(pixmap)

    def get_images_dir(self):
        # Thư mục Images nằm cạnh file chương trình
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "Images")

    def save_captured_image(self, pixmap):
        # Hỏi tên file để lưu ảnh (hiển thị tên cơ sở không gồm toạ độ)
        default_base = f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # chuẩn bị chuỗi toạ độ (mở rộng 10px mỗi cạnh) nhưng không hiển thị
        coords_str = ""
        try:
            if hasattr(self, "captured_rect") and self.captured_rect is not None:
                r = self.captured_rect
                x = max(0, r.x() - 10)
                y = max(0, r.y() - 10)
                w = r.width() + 20
                h = r.height() + 20
                coords_str = f"{x}_{y}_{w}_{h}"
        except Exception:
            coords_str = ""

        name, ok = QInputDialog.getText(
            self,
            "Lưu ảnh",
            "Nhập tên file (không cần đuôi .png):",
            text=default_base,
        )
        if not ok or not name.strip():
            return

        name = name.strip()
        # Nếu người dùng nhập .png thì bỏ phần ext để chúng ta tự gắn lại sau khi ghép coords
        if name.lower().endswith('.png'):
            name = name[:-4]

        name = sanitize_filename_part(name)

        # Tạo tên cuối cùng bằng cách ghép tên người dùng + toạ độ (nếu có) + .png
        if coords_str:
            final_name = f"{name}={coords_str}=.png"
        else:
            final_name = f"{name}.png"

        images_dir = self.get_images_dir()
        try:
            os.makedirs(images_dir, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self, "Lưu ảnh", f"Không thể tạo thư mục Images:\n{e}")
            return

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
            QMessageBox.information(self, "Lưu ảnh", f"Đã lưu ảnh vào:\n{save_path}")
            self.captured_image_path = save_path
            self.refresh_images_gallery()
        else:
            QMessageBox.warning(self, "Lưu ảnh", "Không thể lưu ảnh.")

    def refresh_images_gallery(self):
        # Xóa toàn bộ ảnh cũ đang hiển thị trong danh sách
        while self.gallery_layout.count():
            item = self.gallery_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        images_dir = self.get_images_dir()
        valid_ext = (".png", ".jpg", ".jpeg", ".bmp", ".gif")
        disk_files = []
        if os.path.isdir(images_dir):
            disk_files = sorted(
                f for f in os.listdir(images_dir) if f.lower().endswith(valid_ext)
            )

        # Build displayed_files preserving previous order in self.gallery_files
        if not disk_files:
            placeholder = QLabel("Chưa có ảnh nào trong thư mục Images")
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet("color: #777; font-size: 14px;")
            self.gallery_layout.addWidget(placeholder)
            return
        # If we have a previous ordering, keep those files in that order
        if not self.gallery_files:
            displayed_files = disk_files[:]
        else:
            # Keep existing files in order, append any new files at the end
            remaining = disk_files[:]
            displayed_files = []
            for f in self.gallery_files:
                if f in remaining:
                    displayed_files.append(f)
                    remaining.remove(f)
            displayed_files.extend(remaining)

        # Update stored order
        self.gallery_files = displayed_files

        thumb_size = 60
        for filename in displayed_files:
            file_path = os.path.join(images_dir, filename)
            pixmap = QPixmap(file_path)
            if pixmap.isNull():
                continue
            thumb = pixmap.scaled(
                thumb_size, thumb_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )

            row_widget = QFrame()
            row_widget.setFrameShape(QFrame.StyledPanel)
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(8, 8, 8, 8)
            row_layout.setSpacing(10)

            img_label = QLabel()
            img_label.setPixmap(thumb)
            img_label.setAlignment(Qt.AlignCenter)
            img_label.setFixedSize(thumb_size, thumb_size)
            row_layout.addWidget(img_label)

            name_label = ElidedLabel(filename)
            name_label.setWordWrap(False)
            name_label.setStyleSheet("font-size: 12px;")
            name_label.setToolTip(filename)
            name_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            row_layout.addWidget(name_label, 1)

            btn_copy_path = QPushButton("Copy")
            btn_copy_path.setFixedWidth(70)
            btn_copy_path.clicked.connect(
                lambda checked=False, path=file_path: self.on_copy_image_path(path)
            )
            row_layout.addWidget(btn_copy_path)

            btn_rename = QPushButton("Rename")
            btn_rename.setFixedWidth(70)
            btn_rename.clicked.connect(
                lambda checked=False, path=file_path: self.on_rename_image(path)
            )
            row_layout.addWidget(btn_rename)

            btn_delete = QPushButton("Delete")
            btn_delete.setFixedWidth(70)
            btn_delete.clicked.connect(
                lambda checked=False, path=file_path: self.on_delete_image(path)
            )
            row_layout.addWidget(btn_delete)

            btn_test = QPushButton("Test")
            btn_test.setFixedWidth(70)
            btn_test.clicked.connect(
                lambda checked=False, path=file_path, btn=btn_test: self.on_test_image(path, btn)
            )
            row_layout.addWidget(btn_test)

            self.gallery_layout.addWidget(row_widget)

    def on_copy_image_path(self, file_path):
        QApplication.clipboard().setText(file_path)

    def on_delete_image(self, file_path):
        reply = QMessageBox.question(
            self,
            "Xóa ảnh",
            f"Bạn có chắc muốn xóa file:\n{file_path}?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            os.remove(file_path)
        except OSError as e:
            QMessageBox.warning(self, "Xóa ảnh", f"Không thể xóa file:\n{e}")
            return
        # remove from gallery_files to keep order
        basename = os.path.basename(file_path)
        if basename in self.gallery_files:
            self.gallery_files.remove(basename)
        self.refresh_images_gallery()

    def on_rename_image(self, file_path):
        dirpath = os.path.dirname(file_path)
        basename = os.path.basename(file_path)
        old_name, old_ext = os.path.splitext(basename)

        # Detect coords pattern at the end of the base name, supporting both
        # old format: name_0_180_60_52 and new format: name=0_180_60_52=
        m = re.search(r"^(?P<base>.*)=(?P<x>-?\d+)_(?P<y>-?\d+)_(?P<w>\d+)_(?P<h>\d+)=$", old_name)
        if not m:
            m = re.search(r"^(?P<base>.*)_(?P<x>-?\d+)_(?P<y>-?\d+)_(?P<w>\d+)_(?P<h>\d+)$", old_name)

        if m:
            coords = f"{m.group('x')}_{m.group('y')}_{m.group('w')}_{m.group('h')}"
            base_no_coords = m.group('base')
        else:
            coords = None
            base_no_coords = old_name

        # Show input with the prefix only (without coords) so user edits only that part
        new_input, ok = QInputDialog.getText(
            self,
            "Đổi tên",
            "Chỉ sửa phần tên trước toạ độ (phần toạ độ được giữ tự động):",
            text=base_no_coords,
        )
        if not ok or not new_input.strip():
            return
        new_input = new_input.strip()

        # If user included an extension in the input, respect it; otherwise keep old_ext
        new_root, new_ext = os.path.splitext(new_input)
        if new_ext == "":
            new_ext = old_ext

        new_root = sanitize_filename_part(new_root)

        # Construct final basename: new_root + =coords= (if existed) + ext
        if coords:
            final_basename = f"{new_root}={coords}={new_ext}"
        else:
            final_basename = f"{new_root}{new_ext}"

        new_path = os.path.join(dirpath, final_basename)
        if os.path.exists(new_path):
            reply = QMessageBox.question(
                self,
                "File đã tồn tại",
                f"File \"{final_basename}\" đã tồn tại. Ghi đè?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        try:
            os.rename(file_path, new_path)
        except OSError as e:
            QMessageBox.warning(self, "Đổi tên", f"Không thể đổi tên file:\n{e}")
            return

        # update stored order: replace old basename with new one at same index
        old_basename = os.path.basename(file_path)
        new_basename = os.path.basename(new_path)
        try:
            idx = self.gallery_files.index(old_basename)
            self.gallery_files[idx] = new_basename
        except ValueError:
            # not found -> append to end
            self.gallery_files.append(new_basename)

        self.refresh_images_gallery()

    def on_test_image(self, file_path, button):
        if not os.path.isfile(file_path):
            QMessageBox.warning(self, "Test", "File ảnh không tồn tại.")
            return

        button.setEnabled(False)
        original_text = button.text()
        button.setText("...")

        self._begin_test()
        # Đợi 1 chút để cửa sổ ẩn hoàn tất rồi mới thực sự chạy click_image
        QTimer.singleShot(
            150, lambda: self._start_test_image_thread(file_path, button, original_text)
        )

    def _start_test_image_thread(self, file_path, button, original_text):
        thread = ClickTestThread(file_path)
        self.gallery_test_threads.append(thread)

        def on_finished(success, error, btn=button, orig=original_text, th=thread):
            self._end_test()

            btn.setEnabled(True)
            btn.setText(orig)
            if th in self.gallery_test_threads:
                self.gallery_test_threads.remove(th)

            if error:
                QMessageBox.warning(self, "Test", f"Lỗi khi test click:\n{error}")
            elif success:
                QMessageBox.information(self, "Test", "Đã click thành công vào ảnh trên màn hình.")
            else:
                QMessageBox.warning(
                    self,
                    "Test",
                    "Không tìm thấy ảnh trên màn hình trong thời gian chờ (timeout).",
                )

        thread.finished_signal.connect(on_finished)
        thread.start()

    def display_capture_thumbnail(self, pixmap):
        # Hiện ảnh thu nhỏ ngay trong ô bên dưới nút "Chọn vùng chụp"
        thumb = pixmap.scaled(
            self.capture_result_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.capture_result_label.setPixmap(thumb)
        self.capture_result_label.setStyleSheet("padding: 0px;")

    def on_get_mouse_position(self):
        # Ẩn cửa sổ chính trước, đợi 1 chút rồi mới mở overlay chờ click
        self.hide()
        QTimer.singleShot(150, self.start_position_pick)

    def start_position_pick(self):
        self.overlay = PositionPickerOverlay(self.on_position_picked)
        self.overlay.showFullScreen()

    def on_position_picked(self, point):
        # Hiện lại cửa sổ chính sau khi click xong (hoặc hủy)
        self.show()
        self.raise_()
        self.activateWindow()

        if point is None:
            self.mouse_result_label.setText("Đã hủy")
            self.mouse_position = None
            return

        self.mouse_position = point
        text = f"X: {point.x()}\nY: {point.y()}"
        self.mouse_result_label.setText(text)

    def on_copy_select(self):
        if self.selected_rect is None:
            QMessageBox.information(self, "Copy", "Chưa có vùng nào được chọn.")
            return
        rect = self.selected_rect
        text = f"({rect.x()},{rect.y()},{rect.width()},{rect.height()})"
        QApplication.clipboard().setText(text)

    def on_copy_capture(self):
        if self.captured_image_path is None:
            QMessageBox.information(self, "Copy", "Chưa có ảnh nào được lưu.")
            return
        QApplication.clipboard().setText(self.captured_image_path)

    def _begin_test(self):
        # Ẩn cửa sổ khi bắt đầu test (chỉ ẩn ở lượt test đầu tiên nếu có nhiều test chạy song song)
        self.active_test_count += 1
        if self.active_test_count == 1:
            self.hide()

    def _end_test(self):
        # Hiện lại cửa sổ khi test cuối cùng đang chạy đã xong
        self.active_test_count = max(0, self.active_test_count - 1)
        if self.active_test_count == 0:
            self.show()
            self.raise_()
            self.activateWindow()

    def on_test_capture(self):
        if not self.captured_image_path or not os.path.isfile(self.captured_image_path):
            QMessageBox.information(self, "Test", "Chưa có ảnh nào được lưu để test.")
            return

        self.btn_test_capture.setEnabled(False)
        self.btn_test_capture.setText("Đang test...")

        self._begin_test()
        # Đợi 1 chút để cửa sổ ẩn hoàn tất rồi mới thực sự chạy click_image
        QTimer.singleShot(
            150, lambda: self._start_test_capture_thread(self.captured_image_path)
        )

    def _start_test_capture_thread(self, image_path):
        self.test_thread = ClickTestThread(image_path)
        self.test_thread.finished_signal.connect(self.on_test_finished)
        self.test_thread.start()

    def on_test_finished(self, success, error):
        self._end_test()

        self.btn_test_capture.setEnabled(True)
        self.btn_test_capture.setText("Test")

        if error:
            QMessageBox.warning(self, "Test", f"Lỗi khi test click:\n{error}")
        elif success:
            QMessageBox.information(self, "Test", "Đã click thành công vào ảnh trên màn hình.")
        else:
            QMessageBox.warning(
                self,
                "Test",
                "Không tìm thấy ảnh trên màn hình trong thời gian chờ (timeout).",
            )

    def on_copy_mouse(self):
        if self.mouse_position is None:
            QMessageBox.information(self, "Copy", "Chưa lấy vị trí chuột nào.")
            return
        point = self.mouse_position
        text = f"X={point.x()}, Y={point.y()}"
        QApplication.clipboard().setText(text)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()