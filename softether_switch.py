"""Helpers to control SoftEther VPN Client via vpncmd for automatic VPN Gate switching."""
from __future__ import annotations

import base64
import csv
import json
import os
import random
import socket
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional


class SoftEtherCommandError(RuntimeError):
    """Raised when a vpncmd invocation fails."""

    def __init__(self, command: Iterable[str], exit_code: int, output: str) -> None:
        self.command = list(command)
        self.exit_code = exit_code
        self.output = output
        super().__init__(
            f"vpncmd {self.command[0] if self.command else ''} failed with code {exit_code}: {output.strip()}"
        )


@dataclass
class VpnGateServer:
    hostname: str
    ip: str
    port: int
    country_long: str
    country_short: str
    score: int
    ping: Optional[int]
    speed: Optional[int]
    ovpn_b64: str

    @property
    def display_host(self) -> str:
        return self.hostname or self.ip


class SoftEtherVpnSwitcher:
    """Utility class to rotate VPN Gate connections using SoftEther's vpncmd."""

    VPNGATE_API = "https://www.vpngate.net/api/iphone/"

    def __init__(
        self,
        base_dir: str,
        account_name: str = "AutoVPN",
        nic_name: str = "VPN",
        preferred_countries: Optional[Iterable[str]] = None,
        logger: Optional[Callable[[str, Optional[object]], None]] = None,
        vpncmd_path: Optional[str] = None,
        state_filename: str = "auto_switch_state.json",
        max_candidates: int = 20,
        max_attempts: int = 0,
    ) -> None:
        self.base_dir = os.path.abspath(base_dir)
        os.makedirs(self.base_dir, exist_ok=True)

        self.account_name = account_name
        self.nic_name = nic_name
        self.preferred_countries = [c.strip().upper() for c in (preferred_countries or []) if c.strip()]
        self.logger = logger or (lambda message, color=None: None)
        self.state_path = os.path.join(self.base_dir, state_filename)
        self.max_candidates = max(1, max_candidates)
        self.max_attempts = max_attempts if max_attempts > 0 else 0

        self.vpncmd_path = self._resolve_vpncmd_path(vpncmd_path)
        self.last_state = self._load_state()
        self.last_forced_disconnect = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def switch(self) -> bool:
        if not self.vpncmd_path:
            self._log(
                "Khong tim thay vpncmd.exe. Vui long cai dat SoftEther VPN Client hoac dat bien moi truong VPNCMD_PATH.",
                None,
            )
            return False

        self.last_forced_disconnect = False

        candidates = self._collect_candidate_servers()
        if not candidates:
            if self.last_forced_disconnect:
                self._log(
                    "Da tat VPN hien tai do khong tai duoc danh sach may chu. Tiep tuc voi ket noi hien tai.",
                    None,
                )
                return True
            self._log("Khong tim thay may chu VPN Gate phu hop de ket noi.", None)
            return False

        ordered = self._prioritize_servers(candidates)
        attempts = 0
        for server in ordered:
            if self.max_attempts > 0 and attempts >= self.max_attempts:
                break
            attempts += 1
            if self._try_connect(server):
                self._save_state(server)
                return True
        self._log("Khong the ket noi may chu VPN Gate nao sau khi thu chuyen.", None)
        return False

    def force_disconnect(self) -> bool:
        """Force the SoftEther client to disconnect and revert to the base network."""
        if not self.vpncmd_path:
            return False

        disconnected = self._force_disconnect_current_vpn()
        if disconnected:
            self._log("Da tat ket noi VPN hien tai, su dung IP goc.", None)
        else:
            self._log("Khong the xac nhan tat VPN hien tai.", None)
        return disconnected

    # ------------------------------------------------------------------
    # SoftEther operations
    # ------------------------------------------------------------------
    def _try_connect(self, server: VpnGateServer) -> bool:
        label = f"{server.display_host}:{server.port} ({server.country_short})"
        self._log(f"Dang thu ket noi {label}...", None)

        try:
            self._ensure_virtual_adapter()
            self._disconnect_conflicting_accounts()
            self._teardown_account()

            self._run_vpncmd(
                "AccountCreate",
                self.account_name,
                f"/SERVER:{server.ip or server.hostname}:{server.port}",
                "/HUB:VPNGATE",
                "/USERNAME:vpn",
                f"/NICNAME:{self.nic_name}",
            )
            self._run_vpncmd("AccountAnonymousSet", self.account_name, check=False)
            self._run_vpncmd("AccountStartupSet", self.account_name, check=False)

            connect_result = self._run_vpncmd("AccountConnect", self.account_name, check=False, timeout=90)
            if connect_result.returncode != 0:
                raise SoftEtherCommandError(["AccountConnect", self.account_name], connect_result.returncode, connect_result.stdout)

            deadline = time.time() + 25
            while time.time() < deadline:
                status = self._run_vpncmd("AccountStatusGet", self.account_name, check=False, timeout=10)
                if status.returncode == 0 and "Session Established" in status.stdout:
                    self._log(
                        f"Da ket noi VPN Gate: {label}",
                        None,
                    )
                    return True
                time.sleep(2)

            self._log(
                f"Trang thai ket noi khong hop le voi {label}. Thu may chu khac...",
                None,
            )
        except SoftEtherCommandError as exc:
            self._log(f"vpncmd loi: {exc}", None)
        except Exception as exc:  # pylint: disable=broad-except
            self._log(f"Loi bat ngo khi doi VPN: {exc}", None)
        finally:
            if not self._is_account_connected():
                self._teardown_account()
        return False

    def _disconnect_conflicting_accounts(self) -> None:
        result = self._run_vpncmd("AccountList", check=False)
        current_name: Optional[str] = None
        connected: List[str] = []
        for raw_line in result.stdout.splitlines():
            line = raw_line.strip()
            if not line:
                current_name = None
                continue
            if line.startswith("VPN Connection Setting Name") and "|" in line:
                current_name = line.split("|", 1)[1].strip()
                continue
            if line.startswith("Status") and "Connected" in line and current_name:
                if current_name != self.account_name:
                    connected.append(current_name)
        for name in connected:
            self._run_vpncmd("AccountDisconnect", name, check=False)

    def _ensure_virtual_adapter(self) -> None:
        output = self._run_vpncmd("NicList", check=False).stdout
        nic_exists = any(f"|{self.nic_name}" in line for line in output.splitlines())
        if not nic_exists:
            self._run_vpncmd("NicCreate", self.nic_name)
        self._run_vpncmd("NicEnable", self.nic_name, check=False)

    def _teardown_account(self) -> None:
        self._run_vpncmd("AccountDisconnect", self.account_name, check=False)
        self._run_vpncmd("AccountDelete", self.account_name, check=False)

    def _is_account_connected(self) -> bool:
        status = self._run_vpncmd("AccountStatusGet", self.account_name, check=False)
        return status.returncode == 0 and "Session Established" in status.stdout

    # ------------------------------------------------------------------
    # vpncmd wrappers
    # ------------------------------------------------------------------
    def _run_vpncmd(
        self,
        *arguments: str,
        check: bool = True,
        timeout: int = 45,
    ) -> subprocess.CompletedProcess[str]:
        command = [self.vpncmd_path, "/CLIENT", "localhost", "/CMD", *arguments]
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=timeout,
        )
        if check and result.returncode != 0:
            raise SoftEtherCommandError(arguments, result.returncode, result.stdout)
        return result

    # ------------------------------------------------------------------
    # Server discovery helpers
    # ------------------------------------------------------------------
    def _collect_candidate_servers(self) -> List[VpnGateServer]:
        raw_servers = self._fetch_servers()
        if not raw_servers:
            return []
        if not self.preferred_countries:
            return raw_servers[: self.max_candidates]

        ordered_codes = list(dict.fromkeys(c.strip().upper() for c in self.preferred_countries if c.strip()))
        preferred_buckets: Dict[str, List[VpnGateServer]] = {code: [] for code in ordered_codes}
        others: List[VpnGateServer] = []
        for server in raw_servers:
            country_code = server.country_short.upper()
            bucket = preferred_buckets.get(country_code)
            if bucket is not None:
                bucket.append(server)
            else:
                others.append(server)
        ordered: List[VpnGateServer] = []
        for code in ordered_codes:
            ordered.extend(preferred_buckets.get(code, []))
        ordered.extend(others)
        return ordered[: self.max_candidates]

    def _fetch_servers(self) -> List[VpnGateServer]:
        try:
            with urllib.request.urlopen(self.VPNGATE_API, timeout=20) as response:
                content = response.read().decode("utf-8", errors="ignore")
        except Exception as exc:  # pylint: disable=broad-except
            self._log(f"Khong the tai danh sach VPN Gate: {exc}", None)
            self._handle_server_fetch_failure(exc)
            return []

        lines: List[str] = []
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("*"):
                continue
            if line.startswith("#"):
                line = line[1:]
            lines.append(line)

        if not lines:
            return []

        reader = csv.reader(lines)
        header = next(reader, None)
        servers: List[VpnGateServer] = []
        for row in reader:
            if not row or len(row) < 14:
                continue
            servers.append(self._row_to_server(row))

        servers.sort(key=lambda item: item.score, reverse=True)
        return servers

    def _handle_server_fetch_failure(self, exc: Exception) -> None:
        if not self._is_timeout_error(exc):
            return
        self._log(
            "Loi timeout khi tai danh sach may chu VPN Gate. Dang tat VPN hien tai va tiep tuc su dung IP goc...",
            None,
        )
        disconnected = self._force_disconnect_current_vpn()
        if disconnected:
            self._log("Da tat VPN hien tai sau loi timeout danh sach may chu.", None)
        else:
            self._log("Khong the xac nhan tat VPN hien tai, tiep tuc su dung IP hien tai.", None)
        self.last_forced_disconnect = True

    def _force_disconnect_current_vpn(self) -> bool:
        if not self.vpncmd_path:
            return False

        try:
            self._run_vpncmd("AccountDisconnect", self.account_name, check=False, timeout=30)
        except Exception:  # pylint: disable=broad-except
            pass
        try:
            self._run_vpncmd("AccountDelete", self.account_name, check=False, timeout=30)
        except Exception:  # pylint: disable=broad-except
            pass

        try:
            return not self._is_account_connected()
        except Exception:  # pylint: disable=broad-except
            return False

    @staticmethod
    def _is_timeout_error(exc: Exception) -> bool:
        if isinstance(exc, (socket.timeout, TimeoutError)):
            return True
        reason = getattr(exc, "reason", None)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return True
        return False

    def _row_to_server(self, row: List[str]) -> VpnGateServer:
        hostname = row[0].strip()
        ip = row[1].strip()
        score = self._safe_int(row[2])
        ping = self._safe_int(row[3], default=None)
        speed = self._safe_int(row[4], default=None)
        country_long = row[5].strip()
        country_short = row[6].strip().upper()
        ovpn_b64 = row[14].strip() if len(row) > 14 else ""
        port = self._extract_port(ovpn_b64) or 443
        return VpnGateServer(
            hostname=hostname,
            ip=ip,
            port=port,
            country_long=country_long,
            country_short=country_short,
            score=score,
            ping=ping,
            speed=speed,
            ovpn_b64=ovpn_b64,
        )

    def _extract_port(self, ovpn_b64: str) -> Optional[int]:
        if not ovpn_b64:
            return None
        try:
            decoded = base64.b64decode(ovpn_b64 + "==", validate=False).decode("utf-8", errors="ignore")
        except Exception:  # pylint: disable=broad-except
            return None
        for line in decoded.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.lower().startswith("remote "):
                parts = stripped.split()
                if len(parts) >= 3 and parts[2].isdigit():
                    try:
                        return int(parts[2])
                    except ValueError:
                        return None
        return None

    def _prioritize_servers(self, servers: List[VpnGateServer]) -> List[VpnGateServer]:
        if not self.last_state:
            return servers
        last_ip = self.last_state.get("ip")
        last_port = self.last_state.get("port")
        fresh: List[VpnGateServer] = []
        repeats: List[VpnGateServer] = []
        for server in servers:
            if server.ip == last_ip and server.port == last_port:
                repeats.append(server)
            else:
                fresh.append(server)
        return fresh + repeats

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------
    def _load_state(self) -> Dict[str, object]:
        if not os.path.isfile(self.state_path):
            return {}
        try:
            with open(self.state_path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except Exception:  # pylint: disable=broad-except
            return {}

    def _save_state(self, server: VpnGateServer) -> None:
        state = {
            "ip": server.ip,
            "hostname": server.hostname,
            "port": server.port,
            "country_short": server.country_short,
            "country_long": server.country_long,
            "score": server.score,
            "timestamp": time.time(),
        }
        try:
            with open(self.state_path, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, indent=2)
        except Exception as exc:  # pylint: disable=broad-except
            self._log(f"Khong the luu trang thai doi VPN: {exc}", None)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    def _resolve_vpncmd_path(self, explicit: Optional[str]) -> Optional[str]:
        candidates: List[Optional[str]] = [explicit, os.environ.get("VPNCMD_PATH")]
        program_files = os.environ.get("ProgramFiles", r"C:\\Program Files")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\\Program Files (x86)")
        candidates.extend(
            [
                os.path.join(program_files, "SoftEther VPN Client", "vpncmd.exe"),
                os.path.join(program_files_x86, "SoftEther VPN Client", "vpncmd.exe"),
                os.path.join(os.environ.get("SystemRoot", r"C:\\Windows"), "System32", "vpncmd.exe"),
                os.path.join(self.base_dir, "vpncmd.exe"),
                os.path.join(self.base_dir, "build", "vpncmd.exe"),
            ]
        )
        for path in candidates:
            if path and os.path.isfile(path):
                return os.path.abspath(path)
        return None

    @staticmethod
    def _safe_int(value: str, default: Optional[int] = 0) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _log(self, message: str, color: Optional[object]) -> None:
        try:
            self.logger(message, color)
        except Exception:
            # Fallback to simple print if logger is misbehaving
            print(message)


__all__ = ["SoftEtherVpnSwitcher", "SoftEtherCommandError", "VpnGateServer"]


