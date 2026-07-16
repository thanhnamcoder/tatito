import sys
import os
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
)
from PyQt5.QtCore import Qt, QPoint, QRect, QSize, QTimer
from PyQt5.QtGui import QPainter, QColor, QKeySequence, QPixmap
from PyQt5.QtWidgets import QShortcut, QSizePolicy


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


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("App")
        self.setMinimumSize(700, 400)
        self.overlay = None
        self.selected_rect = None
        self.captured_pixmap = None
        self.captured_image_path = None
        self.mouse_position = None
        self.gallery_files = []  # keep current display order of filenames
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)

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

        self.btn_copy_capture = QPushButton("Copy")
        self.btn_copy_capture.setFixedWidth(button_width)
        self.btn_copy_capture.clicked.connect(self.on_copy_capture)
        capture_layout.addWidget(self.btn_copy_capture, alignment=Qt.AlignHCenter)
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
        # Hỏi tên file để lưu ảnh
        default_name = f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        name, ok = QInputDialog.getText(
            self,
            "Lưu ảnh",
            "Nhập tên file (không cần đuôi .png):",
            text=default_name,
        )
        if not ok or not name.strip():
            return

        name = name.strip()
        if not name.lower().endswith(".png"):
            name += ".png"

        images_dir = self.get_images_dir()
        try:
            os.makedirs(images_dir, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self, "Lưu ảnh", f"Không thể tạo thư mục Images:\n{e}")
            return

        save_path = os.path.join(images_dir, name)

        if os.path.exists(save_path):
            reply = QMessageBox.question(
                self,
                "File đã tồn tại",
                f"File \"{name}\" đã tồn tại. Bạn có muốn ghi đè không?",
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
        new_name, ok = QInputDialog.getText(
            self,
            "Đổi tên",
            "Nhập tên mới (có thể kèm đuôi):",
            text=old_name,
        )
        if not ok or not new_name.strip():
            return
        new_name = new_name.strip()
        # If user didn't include an extension, keep the old one
        if os.path.splitext(new_name)[1] == "":
            new_name = new_name + old_ext
        new_path = os.path.join(dirpath, new_name)
        if os.path.exists(new_path):
            reply = QMessageBox.question(
                self,
                "File đã tồn tại",
                f"File \"{new_name}\" đã tồn tại. Ghi đè?",
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