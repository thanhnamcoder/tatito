import os
import time
import subprocess
import pyperclip
import psutil
import pyautogui
from datetime import datetime, timedelta
import random
import json
import re
# ==========================
# CẤU HÌNH
# ==========================

pyautogui.FAILSAFE = True      # Đưa chuột lên góc trái để dừng script
pyautogui.PAUSE = 0.1          # Nghỉ 0.1s sau mỗi thao tác
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
RELOAD_SIGNAL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config_reload.signal")
WEEKDAY_NAME = [
    "Thứ 2",
    "Thứ 3",
    "Thứ 4",
    "Thứ 5",
    "Thứ 6",
    "Thứ 7",
    "Chủ nhật"
]

# ==========================
# LOG
# ==========================

def log(message):
    print(f"[{time.strftime('%H:%M:%S')}] {message}")


def trigger_scheduler_reload(signal_file=RELOAD_SIGNAL_FILE):
    try:
        with open(signal_file, "w", encoding="utf-8") as f:
            f.write(str(time.time()))
        log("Đã gửi tín hiệu reload scheduler")
        return True
    except Exception as e:
        log(f"Không gửi được tín hiệu reload: {e}")
        return False


def consume_scheduler_reload(signal_file=RELOAD_SIGNAL_FILE):
    if not os.path.exists(signal_file):
        return False

    try:
        with open(signal_file, "r", encoding="utf-8") as f:
            f.read().strip()
        os.remove(signal_file)
        return True
    except FileNotFoundError:
        return False
    except Exception as e:
        log(f"Lỗi khi xử lý tín hiệu reload: {e}")
        return False


def wait_for_reload_or_timeout(timeout_seconds, interval=1.0):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if consume_scheduler_reload():
            return True
        time.sleep(min(interval, max(0.1, deadline - time.time())))
    return False


# ==========================
# SCREENSHOT
# ==========================

def screenshot(filename=None):
    if filename is None:
        filename = f"screenshot_{int(time.time())}.png"

    pyautogui.screenshot(filename)
    log(f"Đã lưu screenshot: {filename}")


# ==========================
# MỞ APP
# ==========================

def open_app(exe_path, timeout=60):
    exe_name = os.path.basename(exe_path).lower()
    work_dir = os.path.dirname(exe_path)

    close_app(exe_path)

    # Mở lại app
    process = subprocess.Popen(
        [exe_path],
        cwd=work_dir
    )

    start = time.time()
    while time.time() - start < timeout:
        if psutil.pid_exists(process.pid):
            log(f"{exe_name} đã khởi động")
            return process

        time.sleep(0.2)

    raise TimeoutError(f"Không mở được {exe_name}")

# ==========================
# Close app
#===========================

def close_app(exe_path, timeout=10):
    exe_name = os.path.basename(exe_path).lower()

    log(f"Đóng {exe_name}...")

    # Đóng nếu app đang chạy
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if proc.info["name"] and proc.info["name"].lower() == exe_name:
                proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # Chờ app đóng hẳn
    start = time.time()
    while time.time() - start < timeout:
        running = False

        for proc in psutil.process_iter(["name"]):
            try:
                if proc.info["name"] and proc.info["name"].lower() == exe_name:
                    running = True
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        if not running:
            log(f"{exe_name} đã đóng.")
            return True
            break

        time.sleep(0.2)
    log(f"Không thể đóng {exe_name}.")
    return False
# ==========================
# CHỜ ẢNH
# ==========================

def wait_image(
    image_path,
    confidence=0.8,
    timeout=30,
    interval=0.2,
    region=None
):
    start = time.time()

    while time.time() - start < timeout:
        try:
            pos = pyautogui.locateCenterOnScreen(
                image_path,
                confidence=confidence,
                region=region
            )

            if pos:
                return pos

        except Exception:
            pass

        time.sleep(interval)

    return None


# ==========================
# TÁCH TỌA ĐỘ TỪ TÊN ẢNH
# ==========================

def extract_coords_from_image_path(image_path):
    if not image_path:
        return None

    base_name = os.path.basename(image_path)
    name, _ = os.path.splitext(base_name)

    patterns = [
        r"^(?P<base>.*)=(?P<x>-?\d+)_(?P<y>-?\d+)_(?P<w>\d+)_(?P<h>\d+)=$",
        r"^(?P<base>.*)_(?P<x>-?\d+)_(?P<y>-?\d+)_(?P<w>\d+)_(?P<h>\d+)$",
    ]

    for pattern in patterns:
        match = re.search(pattern, name)
        if match:
            return {
                "x": int(match.group("x")),
                "y": int(match.group("y")),
                "w": int(match.group("w")),
                "h": int(match.group("h")),
            }

    return None


# ==========================
# CLICK ẢNH
# ==========================

def click_image(
    image_path,
    confidence=0.8,
    timeout=30,
    interval=0.2,
    region=None,
    stable_count=3
):
    # Nếu tên file có chứa tọa độ thì dùng làm vùng tìm kiếm
    coords = extract_coords_from_image_path(image_path)
    if coords and region is None:
        region = (
            coords["x"],
            coords["y"],
            coords["w"],
            coords["h"]
        )

    last_pos = None
    stable = 0
    start = time.time()

    while time.time() - start < timeout:

        pos = wait_image(
            image_path=image_path,
            confidence=confidence,
            timeout=interval,
            interval=0.05,
            region=region
        )

        if pos:

            if (
                last_pos is not None
                and abs(last_pos.x - pos.x) <= 2
                and abs(last_pos.y - pos.y) <= 2
            ):
                stable += 1
            else:
                stable = 1

            last_pos = pos

            if stable >= stable_count:
                pyautogui.moveTo(pos.x, pos.y, duration=0.1)
                pyautogui.click()

                log(f"Clicked: {image_path}")
                return True

        time.sleep(interval)

    screenshot("click_timeout.png")
    log(f"Timeout: {image_path}")

    return False

# ==========================
# KIỂM TRA ẢNH
# ==========================

def exists_image(image_path, confidence=0.8, region=None):
    try:
        return pyautogui.locateCenterOnScreen(
            image_path,
            confidence=confidence,
            region=region
        ) is not None

    except Exception:
        return False


# ==========================
# CHỜ ẢNH BIẾN MẤT
# ==========================

def wait_disappear(
    image_path,
    confidence=0.8,
    timeout=30,
    interval=0.2,
    region=None
):
    start = time.time()

    while time.time() - start < timeout:
        if not exists_image(image_path, confidence, region):
            return True

        time.sleep(interval)

    return False

# ==========================
# CLICK THEO OFFSET
# ==========================

def click_offset(image_path,
                 offset_x=0,
                 offset_y=0,
                 confidence=0.8):

    pos = wait_image(image_path, confidence)

    if pos:
        pyautogui.click(
            pos.x + offset_x,
            pos.y + offset_y
        )
        return True

    return False


# ==========================
# PASTE
# ==========================

def paste(text):
    pyperclip.copy(str(text))
    pyautogui.hotkey("ctrl", "v")
    log("Đã thực hiện Ctrl+V")


def random_time(date, start_str, end_str):
    start = datetime.combine(
        date,
        datetime.strptime(start_str, "%H:%M").time()
    )

    end = datetime.combine(
        date,
        datetime.strptime(end_str, "%H:%M").time()
    )

    return start + timedelta(
        seconds=random.randint(0, int((end - start).total_seconds()))
    )


def random_time(date, start_str, end_str):
    start = datetime.combine(
        date,
        datetime.strptime(start_str, "%H:%M").time()
    )

    end = datetime.combine(
        date,
        datetime.strptime(end_str, "%H:%M").time()
    )

    seconds = random.randint(
        0,
        int((end - start).total_seconds())
    )

    return start + timedelta(seconds=seconds)

def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def print_day_schedule(config, date):
    weekday = str(date.weekday())
    day_cfg = config.get("schedule", {}).get(weekday, {})

    print(f"\n===== {WEEKDAY_NAME[date.weekday()]} ({date:%d/%m/%Y}) =====")

    if not day_cfg:
        print("Không có lịch.")
        return False

    for job_name, cfg in day_cfg.items():
        print(
            f"- {job_name}: {cfg['start']} -> {cfg['end']}"
        )

    return True

def print_next_schedule(config, from_date):
    print("\n===== LỊCH TIẾP THEO =====")

    for i in range(1, 8):
        d = from_date + timedelta(days=i)
        if print_day_schedule(config, d):
            return

    print("7 ngày tới không có lịch.")

def scheduler():

    while True:

        now = datetime.now()

        # Đọc config mới nhất mỗi vòng lặp
        config = load_config()

        weekday = str(now.weekday())

        day_cfg = config.get("schedule", {}).get(weekday, {})

        run_list = []

        # Tạo danh sách các job hôm nay
        for job_name, cfg in day_cfg.items():

            start = cfg.get("start")
            end = cfg.get("end")

            if not start or not end:
                continue

            run_time = random_time(
                now.date(),
                start,
                end
            )

            if run_time <= now:
                continue

            run_list.append(
                (
                    run_time,
                    job_name
                )
            )

        # Không còn job nào hôm nay
        if not run_list:

            tomorrow = (now + timedelta(days=1)).replace(
                hour=0,
                minute=0,
                second=1,
                microsecond=0
            )

            print("Không có lịch hôm nay.")

            while True:
                if consume_scheduler_reload():
                    print("Nhận tín hiệu reload config, bắt đầu lại từ đầu.")
                    break

                sleep_time = (tomorrow - datetime.now()).total_seconds()
                if sleep_time <= 0:
                    break

                time.sleep(min(1.0, sleep_time))

            continue

        # Chạy theo thứ tự thời gian
        run_list.sort(key=lambda x: x[0])

        reload_requested = False
        for run_time, job_name in run_list:

            while True:
                if consume_scheduler_reload():
                    print("Nhận tín hiệu reload config, bắt đầu lại từ đầu.")
                    reload_requested = True
                    break

                wait = (run_time - datetime.now()).total_seconds()
                if wait <= 0:
                    break

                print(
                    f"Đợi đến {run_time:%d/%m/%Y %H:%M:%S} -> {job_name}"
                )
                time.sleep(min(1.0, wait))

            if reload_requested:
                break

            # Lấy hàm theo tên
            func = globals().get(job_name)

            if not callable(func):
                print(f"Không tìm thấy hàm '{job_name}'")
                continue

            try:

                print(f"Đang chạy {job_name}")

                func()

            except Exception as e:

                print(f"Lỗi {job_name}: {e}")

        if reload_requested:
            continue

        # Chờ sang ngày mới
        today = datetime.now().date()

        print(f"\nĐã hoàn thành lịch {WEEKDAY_NAME[today.weekday()]} ({today:%d/%m/%Y})")

        print_next_schedule(config, today)

        tomorrow = (datetime.now() + timedelta(days=1)).replace(
            hour=0,
            minute=0,
            second=1,
            microsecond=0
        )

        sleep_time = (tomorrow - datetime.now()).total_seconds()

        print(
            f"\nScheduler ngủ {int(sleep_time)} giây đến "
            f"{tomorrow:%d/%m/%Y %H:%M:%S}\n"
        )

        while True:
            if consume_scheduler_reload():
                print("Nhận tín hiệu reload config, bắt đầu lại từ đầu.")
                break

            remaining = (tomorrow - datetime.now()).total_seconds()
            if remaining <= 0:
                break

            time.sleep(min(1.0, remaining))

        if consume_scheduler_reload():
            continue
# ==========================
# DEMO
# ==========================

class Job:
    def __init__(self):
        self.browser_path = r"C:\Program Files\CocCoc\Browser\Application\browser.exe"

    def test1(self):
        open_app(self.browser_path)

    def test2(self):
        close_app(self.browser_path)

    def auto_ti(self):
        app_path = r"C:\StaffAttendantClient\StaffAttClient\StaffAttClient.exe"
        open_app(app_path)
        wait_image(r"C:\Users\POS01\Downloads\OT\pyautogui-package-main\Images\xacnhan.png")
        paste("CK-HCM0332415")
        wait_image(r"C:\Users\POS01\Downloads\OT\pyautogui-package-main\Images\xacnhan.png")
        click_image(r"C:\Users\POS01\Downloads\OT\pyautogui-package-main\Images\xacnhan.png")
        wait_image(r"C:\Users\POS01\Downloads\OT\pyautogui-package-main\Images\vaoca.png")
        click_image(r"C:\Users\POS01\Downloads\OT\pyautogui-package-main\Images\vaoca.png")
        wait_image(r"C:\Users\POS01\Downloads\OT\pyautogui-package-main\Images\yes.png")
        click_image(r"C:\Users\POS01\Downloads\OT\pyautogui-package-main\Images\yes.png")
        close_app(app_path)

    def auto_to(self):
        app_path = r"C:\StaffAttendantClient\StaffAttClient\StaffAttClient.exe"
        open_app(app_path)
        wait_image(r"C:\Users\POS01\Downloads\OT\pyautogui-package-main\Images\xacnhan.png")
        paste("CK-HCM0332415")
        wait_image(r"C:\Users\POS01\Downloads\OT\pyautogui-package-main\Images\xacnhan.png")
        click_image(r"C:\Users\POS01\Downloads\OT\pyautogui-package-main\Images\xacnhan.png")
        wait_image(r"C:\Users\POS01\Downloads\OT\pyautogui-package-main\Images\raca.png")
        click_image(r"C:\Users\POS01\Downloads\OT\pyautogui-package-main\Images\raca.png")
        wait_image(r"C:\Users\POS01\Downloads\OT\pyautogui-package-main\Images\no.png")
        click_image(r"C:\Users\POS01\Downloads\OT\pyautogui-package-main\Images\no.png")
        close_app(app_path)

Jobs = Job()


def test1():
    Jobs.test1()


def test2():
    Jobs.test2()

