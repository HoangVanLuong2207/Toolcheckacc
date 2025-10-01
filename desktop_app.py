"""Desktop GUI application for managing Garena accounts and output files."""

import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, simpledialog
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText


ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


class AccountsInputDialog(simpledialog.Dialog):
    """Dialog that accepts multi-line account entries in accounts.txt format."""

    def __init__(self, parent, title=None):
        self._parsed_lines: list[str] = []
        super().__init__(parent, title=title)

    def body(self, master):  # type: ignore[override]
        self.title("Thêm tài khoản")  # Chỉnh sửa
        ttk.Label(
            master,
            text="Nhập danh sách tài khoản (email:mật khẩu mỗi dòng)",  # Chỉnh sửa
        ).grid(row=0, column=0, padx=5, pady=(5, 0), sticky="w")
        self.text_widget = ScrolledText(master, width=60, height=12, wrap="none")
        self.text_widget.grid(row=1, column=0, padx=5, pady=5, sticky="nsew")
        master.rowconfigure(1, weight=1)
        master.columnconfigure(0, weight=1)
        return self.text_widget

    def validate(self):  # type: ignore[override]
        raw_lines = self.text_widget.get("1.0", tk.END).splitlines()
        parsed: list[str] = []
        invalid: list[str] = []
        for original_line in raw_lines:
            stripped = original_line.strip()
            if not stripped:
                parsed.append("")
                continue
            normalized = stripped
            if ":" not in normalized and "|" in normalized:
                normalized = normalized.replace("|", ":", 1)
            if ":" not in normalized:
                invalid.append(original_line)
            else:
                parsed.append(normalized)
        if invalid:
            message = "\n".join(invalid[:10])
            if len(invalid) > 10:
                message += "\n..."
            messagebox.showwarning(
                "Định dạng không hợp lệ",  # Chỉnh sửa
                "Những dòng sau thiếu dấu ':' hoặc '|':\n" + message,  # Chỉnh sửa
            )
            return False
        self._parsed_lines = parsed
        return True

    def apply(self):  # type: ignore[override]
        self.result = self._parsed_lines


class Application(tk.Tk):
    """Main Tkinter application window."""

    AUTO_REFRESH_MS = 2000

    def __init__(self) -> None:
        super().__init__()
        self.title("Garena Account Manager")
        self.geometry("1100x650")

        self.base_dir = Path(__file__).resolve().parent
        configured_output = os.environ.get("OUTPUT_DIR")
        if configured_output:
            self.output_dir = Path(configured_output).expanduser().resolve()
        else:
            self.output_dir = (self.base_dir / "output").resolve()
        os.environ["OUTPUT_DIR"] = str(self.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.accounts_file = self.base_dir / "accounts.txt"
        self.log_queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self._run_thread: threading.Thread | None = None
        self._current_process: subprocess.Popen | None = None
        self._running = False
        self._stop_requested = False

        self.account_lines: list[str] = []
        self.account_count: int = 0
        self.output_files: list[Path] = []
        self._seen_output_names: list[str] = []
        self.last_run_time: str | None = None
        self.current_progress: str | None = None
        self._status_base = "Sẵn sàng"  # Chỉnh sửa

        self._build_ui()
        self._load_accounts(force_update=True)
        self._refresh_output_files(force_update=True)
        self._update_status_label()
        self.after(self.AUTO_REFRESH_MS, self._auto_refresh)
        self.after(200, self._poll_log_queue)

    def _build_ui(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        accounts_frame = ttk.Frame(self, padding=10)
        accounts_frame.grid(row=0, column=0, sticky="nsew")
        accounts_frame.rowconfigure(1, weight=1)
        accounts_frame.columnconfigure(0, weight=1)

        ttk.Label(accounts_frame, text="Danh sách tài khoản").grid(row=0, column=0, sticky="w")  # Chỉnh sửa

        accounts_list_frame = ttk.Frame(accounts_frame)
        accounts_list_frame.grid(row=1, column=0, sticky="nsew", pady=(5, 10))
        accounts_list_frame.rowconfigure(0, weight=1)
        accounts_list_frame.columnconfigure(0, weight=1)

        self.accounts_listbox = tk.Listbox(
            accounts_list_frame,
            activestyle="none",
            exportselection=False,
            height=15,
        )
        accounts_scroll = ttk.Scrollbar(
            accounts_list_frame,
            orient="vertical",
            command=self.accounts_listbox.yview,
        )
        self.accounts_listbox.configure(yscrollcommand=accounts_scroll.set)
        self.accounts_listbox.grid(row=0, column=0, sticky="nsew")
        accounts_scroll.grid(row=0, column=1, sticky="ns")

        buttons_frame = ttk.Frame(accounts_frame)
        buttons_frame.grid(row=2, column=0, sticky="ew")
        buttons_frame.columnconfigure((0, 1, 2, 3, 4), weight=1)

        self.add_button = ttk.Button(buttons_frame, text="Thêm", command=self._add_account)  # Chỉnh sửa
        self.remove_button = ttk.Button(buttons_frame, text="Xóa", command=self._remove_selected_account)  # Chỉnh sửa
        self.refresh_accounts_button = ttk.Button(buttons_frame, text="Tải lại", command=lambda: self._load_accounts(True))  # Chỉnh sửa
        self.run_button = ttk.Button(buttons_frame, text="Chạy kiểm tra", command=self._start_check)  # Chỉnh sửa
        self.stop_button = ttk.Button(buttons_frame, text="Dừng kiểm tra", command=self._stop_current_run)  # Chỉnh sửa

        self.add_button.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        self.remove_button.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.refresh_accounts_button.grid(row=0, column=2, padx=5, pady=5, sticky="ew")
        self.run_button.grid(row=0, column=3, padx=5, pady=5, sticky="ew")
        self.stop_button.grid(row=0, column=4, padx=5, pady=5, sticky="ew")

        main_frame = ttk.Frame(self, padding=10)
        main_frame.grid(row=0, column=1, sticky="nsew")
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)

        files_label_frame = ttk.Frame(main_frame)
        files_label_frame.grid(row=0, column=0, sticky="ew")
        files_label_frame.columnconfigure(0, weight=1)

        ttk.Label(files_label_frame, text="File kết quả").grid(row=0, column=0, sticky="w")  # Chỉnh sửa
        self.open_dir_button = ttk.Button(files_label_frame, text="Mở thư mục", command=self._open_output_dir)  # Chỉnh sửa
        self.open_dir_button.grid(row=0, column=1, padx=5)

        files_frame = ttk.Frame(main_frame)
        files_frame.grid(row=1, column=0, sticky="nsew")
        files_frame.columnconfigure(0, weight=1)
        files_frame.rowconfigure(0, weight=1)

        self.files_listbox = tk.Listbox(
            files_frame,
            activestyle="none",
            exportselection=False,
            height=12,
        )
        self.files_listbox.grid(row=0, column=0, sticky="nsew")
        self.files_listbox.bind("<<ListboxSelect>>", self._on_file_selected)

        preview_frame = ttk.Frame(main_frame)
        preview_frame.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)

        ttk.Label(preview_frame, text="Nội dung file").grid(row=0, column=0, sticky="w")  # Chỉnh sửa
        self.file_content = ScrolledText(preview_frame, height=15, wrap="none", state="disabled")
        self.file_content.grid(row=1, column=0, sticky="nsew")

        log_frame = ttk.Frame(main_frame)
        log_frame.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(1, weight=1)

        ttk.Label(log_frame, text="Nhật ký").grid(row=0, column=0, sticky="w")  # Chỉnh sửa
        self.log_text = ScrolledText(log_frame, height=10, state="disabled", wrap="word")
        self.log_text.grid(row=1, column=0, sticky="nsew")

        self.status_var = tk.StringVar(value=self._status_base)
        status_bar = ttk.Label(self, textvariable=self.status_var, anchor="w", padding=5)
        status_bar.grid(row=1, column=0, columnspan=2, sticky="ew")

    def _load_accounts(self, force_update: bool = False) -> None:
        try:
            lines = self.accounts_file.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            lines = []
        except Exception as exc:
            self._append_log(f"[Lỗi] Không đọc được accounts.txt: {exc}")  # Chỉnh sửa
            lines = self.account_lines[:]
        if force_update or lines != self.account_lines:
            self.account_lines = lines
            self.accounts_listbox.delete(0, tk.END)
            for line in self.account_lines:
                self.accounts_listbox.insert(tk.END, line)
        self.account_count = sum(1 for line in self.account_lines if line.strip())
        self._update_status_label()

    def _save_accounts(self) -> None:
        if self.account_lines:
            data = "\n".join(self.account_lines) + "\n"
        else:
            data = ""
        self.accounts_file.write_text(data, encoding="utf-8")
        self._load_accounts(force_update=True)

    def _add_account(self) -> None:
        dialog = AccountsInputDialog(self, title="Thêm tài khoản")  # Chỉnh sửa
        if dialog.result:
            self.account_lines.extend(dialog.result)
            self._save_accounts()

    def _remove_selected_account(self) -> None:
        selection = self.accounts_listbox.curselection()
        if not selection:
            messagebox.showinfo("Chọn tài khoản", "Vui lòng chọn tài khoản.")  # Chỉnh sửa
            return
        index = selection[0]
        if index >= len(self.account_lines):
            return
        entry = self.account_lines[index]
        display_name = entry.split(":", 1)[0] if entry else "(dòng trống)"  # Chỉnh sửa
        if messagebox.askyesno("Xóa tài khoản", f"Chắc chắn xóa {display_name}?"):  # Chỉnh sửa
            self.account_lines.pop(index)
            self._save_accounts()

    def _refresh_output_files(self, force_update: bool = False) -> None:
        if not self.output_dir.exists():
            self.output_dir.mkdir(parents=True, exist_ok=True)
        files = sorted(
            [path for path in self.output_dir.iterdir() if path.is_file()],
            key=lambda p: p.name.lower(),
        )
        names = [path.name for path in files]
        if force_update or names != self._seen_output_names:
            self.output_files = files
            self._seen_output_names = names
            self.files_listbox.delete(0, tk.END)
            for path in self.output_files:
                self.files_listbox.insert(tk.END, path.name)
        self._update_status_label()

    def _auto_refresh(self) -> None:
        if not hasattr(self, "accounts_listbox"):
            return
        self._load_accounts()
        self._refresh_output_files()
        self.after(self.AUTO_REFRESH_MS, self._auto_refresh)

    def _on_file_selected(self, event):  # noqa: ARG002
        selection = self.files_listbox.curselection()
        if not selection:
            return
        index = selection[0]
        if index >= len(self.output_files):
            return
        path = self.output_files[index]
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = path.read_text(encoding="latin-1")
        except Exception as exc:
            content = f"Không đọc được nội dung: {exc}"  # Chỉnh sửa
        self.file_content.configure(state="normal")
        self.file_content.delete("1.0", tk.END)
        self.file_content.insert(tk.END, content)
        self.file_content.configure(state="disabled")

    def _open_output_dir(self) -> None:
        path = self.output_dir
        try:
            if os.name == "nt":
                os.startfile(path)  # type: ignore[arg-type]
            elif sys.platform == "darwin":
                subprocess.run(["open", str(path)], check=False)
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
        except Exception as exc:
            messagebox.showerror("Không mở được", f"Không thể mở thư mục: {exc}")  # Chỉnh sửa

    def _start_check(self) -> None:
        if self._running:
            messagebox.showinfo("Đang xử lý", "Quá trình kiểm tra đang chạy.")  # Chỉnh sửa
            return
        if not messagebox.askyesno(
            "Xác nhận",  # Chỉnh sửa
            "Bạn đã lưu lại dữ liệu và sẵn sàng chạy kiểm tra?",  # Chỉnh sửa
        ):
            return
        if not self.account_lines:
            if not messagebox.askyesno(
                "Không có tài khoản",  # Chỉnh sửa
                "Danh sách tài khoản đang trống, bạn có chắc chắn muốn chạy kiểm tra?",  # Chỉnh sửa
            ):
                return
        self.last_run_time = time.strftime("%H:%M:%S")
        self.current_progress = "Chuẩn bị"  # Chỉnh sửa
        self._set_running(True)
        self._append_log("=== Bắt đầu kiểm tra tài khoản ===")  # Chỉnh sửa
        self._stop_requested = False
        self._current_process = None
        self.file_content.configure(state="normal")
        self.file_content.delete("1.0", tk.END)
        self.file_content.configure(state="disabled")

        self._run_thread = threading.Thread(
            target=self._run_checker,
            daemon=True,
        )
        self._run_thread.start()

    def _run_checker(self) -> None:
        process: subprocess.Popen | None = None
        try:
            python_exec = Path(sys.executable)
            if python_exec.name.lower() == "pythonw.exe":
                candidate = python_exec.with_name("python.exe")
                if candidate.exists():
                    python_exec = candidate
            env = os.environ.copy()
            env.setdefault("PYTHONIOENCODING", "utf-8")
            env.setdefault("PYTHONUTF8", "1")
            env.setdefault("TERM", "xterm")
            creationflags = 0
            if os.name == "nt":
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            process = subprocess.Popen(
                [str(python_exec), "-X", "utf8", "check_garena.py"],
                cwd=str(self.base_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                creationflags=creationflags
            )
            self._current_process = process
            assert process.stdout is not None
            for raw_line in iter(process.stdout.readline, b""):
                decoded = raw_line.decode("utf-8", errors="replace")
                clean = ANSI_ESCAPE_RE.sub("", decoded).rstrip()
                if clean:
                    self.log_queue.put(("log", clean))
            process.stdout.close()
            return_code = process.wait()
            if return_code == 0:
                self.log_queue.put(("status", {"state": "completed"}))
            elif self._stop_requested:
                self.log_queue.put(("status", {"state": "cancelled"}))
            else:
                self.log_queue.put((
                    "status",
                    {
                        "state": "error",
                        "message": f"Tiến trình trả về mã lỗi {return_code}",  # Chỉnh sửa
                    },
                ))
        except Exception as exc:
            if self._stop_requested:
                self.log_queue.put(("status", {"state": "cancelled"}))
            else:
                self.log_queue.put(("status", {"state": "error", "message": str(exc)}))
        finally:
            if self._current_process is process:
                self._current_process = None
            process = None

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def _set_status(self, message: str) -> None:
        self._status_base = message
        self._update_status_label()

    def _update_status_label(self) -> None:
        parts = [self._status_base]
        parts.append(f"Tài khoản: {self.account_count}")  # Chỉnh sửa
        if self.last_run_time:
            parts.append(f"Bắt đầu: {self.last_run_time}")  # Chỉnh sửa
        if self.current_progress:
            parts.append(f"Tiến độ: {self.current_progress}")  # Chỉnh sửa
        self.status_var.set(" | ".join(parts))

    def _set_running(self, running: bool) -> None:
        self._running = running
        state = "disabled" if running else "!disabled"
        managed_buttons = (
            self.add_button,
            self.remove_button,
            self.refresh_accounts_button,
            self.run_button,
        )
        for button in managed_buttons:
            if state == "disabled":
                button.state(["disabled"])
            else:
                button.state(["!disabled"])
        if running:
            self._set_status("Đang kiểm tra tài khoản...")  # Chỉnh sửa
        else:
            self._set_status("Sẵn sàng")  # Chỉnh sửa

    def _poll_log_queue(self) -> None:
        try:
            while True:
                kind, payload = self.log_queue.get_nowait()
                if kind == "log" and isinstance(payload, str):
                    self._append_log(payload)
                    match = re.search(r"\[(\d+)/(\d+)\]", payload)
                    if match:
                        self.current_progress = f"{match.group(1)}/{match.group(2)}"
                        self._update_status_label()
                elif kind == "status" and isinstance(payload, dict):
                    state = payload.get("state")
                    if state == "completed":
                        self.current_progress = "Hoàn tất"  # Chỉnh sửa
                        self._set_running(False)
                        self._stop_requested = False
                        self._load_accounts(force_update=True)
                        self._refresh_output_files(force_update=True)
                    elif state == "cancelled":
                        self._append_log("=== Đã dừng kiểm tra theo yêu cầu ===")  # Chỉnh sửa
                        self.current_progress = "Đã dừng"  # Chỉnh sửa
                        self._set_running(False)
                        self._stop_requested = False
                        self._load_accounts(force_update=True)
                        self._refresh_output_files(force_update=True)
                    elif state == "error":
                        message = payload.get("message", "Có lỗi xảy ra")  # Chỉnh sửa
                        self._append_log(f"[Lỗi] {message}")  # Chỉnh sửa
                        self.current_progress = None
                        self._set_running(False)
                        self._stop_requested = False
                        messagebox.showerror("Lỗi", message)  # Chỉnh sửa
        except queue.Empty:
            pass
        finally:
            self.after(200, self._poll_log_queue)

    def _stop_current_run(self) -> None:
        if not self._running:
            messagebox.showinfo("Không có tiến trình", "Không có kiểm tra nào đang chạy.")  # Chỉnh sửa
            return
        self._stop_requested = True
        process = self._current_process
        if process and process.poll() is None:
            self._append_log("=== Đang dừng kiểm tra theo yêu cầu ===")  # Chỉnh sửa
            try:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
            except Exception as exc:
                self._append_log(f"[Lỗi] Không dừng được tiến trình: {exc}")  # Chỉnh sửa
        else:
            self._append_log("Không tìm thấy tiến trình đang chạy.")  # Chỉnh sửa


def main() -> None:
    app = Application()
    app.mainloop()


if __name__ == "__main__":
    main()