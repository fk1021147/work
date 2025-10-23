# -*- coding: utf-8 -*-
from __future__ import annotations

import builtins
import json
import os
import platform
import re
import subprocess
import threading
import time
from collections import deque
from datetime import datetime
from typing import Optional, Pattern, Dict, List

import serial
from serial import SerialException

# =============================================================================
# Configuration (flexible defaults; override via TEST_CONFIG JSON at runtime)
# =============================================================================
_run_ts = datetime.now().strftime("%m%d_%H%M%S")

LOG_DIR = f"logs_{_run_ts}"
os.makedirs(LOG_DIR, exist_ok=True)

DEFAULT_CONFIG = {
    "init_commands": [
        'echo apibtdump > /dev/displaylog0',
        'echo apibtdump > /dev/displaylog1',
    ],
    "monitored_files": [
        "/var/log/display_smmu_fault_info.txt",
        "/var/log/postmortem_smmu.txt",
        "/var/log/openwfd_server-QM.core",
    ],
    "core_path": "/var/log/openwfd_server-QM.core",
    "core_dest": "/data/",  # absolute destination on QNX
    "serial": {
        "ucom": "COM22",
        "qnx": "COM13",
        "sail": "COM3",
        "android": "COM12",
        "baud": 115200,
        "read_timeout_sec": 1.0,
    },
    "local_dirs": {
        "showmem": os.path.join(LOG_DIR, "showmem"),
        "showmem_s": os.path.join(LOG_DIR, "showmem_s"),
        "fault_files": os.path.join(LOG_DIR, "fault_files"),
    },
    # --- ADD inside DEFAULT_CONFIG ---
    "features": {
        "collect_showmem": True,          # stream showmem / showmem -s to PC
        "pull_fault_files": True,         # pull (cat) text fault files to PC
        "copy_core": True,  
        "print_ls_la": True,
        "surface_dump_on_fault": True,    # echo surfacedump when fault detected
        "print_ls_paths_on_fault": ["/var/log", "/var/data","/dev/shmem/"],
        # --- NEW ---
        "stop_on_fault": True,            # set True to enable auto-stop on fault
        "stop_after_fault_wait_sec": 80     # wait seconds after 
        
    },
    "post_cycle_wait_sec": 10,
}


def _load_config() -> Dict:
    """Load external JSON config pointed by TEST_CONFIG env var and merge with defaults."""
    cfg = dict(DEFAULT_CONFIG)
    path = os.environ.get("TEST_CONFIG", "").strip()
    if path:
        try:
            with open(path, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            # Shallow merge with defaults
            for k, v in user_cfg.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
            print(f"[CFG] Loaded config from {path}")
        except Exception as e:
            print(f"[CFG][WARN] Could not load TEST_CONFIG {path}: {e}")
    return cfg


CFG = _load_config()
FEAT = CFG.get("features", {})
FEAT_COLLECT_SHOWMEM        = bool(FEAT.get("collect_showmem", True))
FEAT_PULL_FAULT_FILES       = bool(FEAT.get("pull_fault_files", True))
FEAT_COPY_CORE              = bool(FEAT.get("copy_core", True))
FEAT_SURFACE_DUMP_ON_FAULT  = bool(FEAT.get("surface_dump_on_fault", True))
FEAT_STOP_ON_FAULT = bool(FEAT.get("stop_on_fault", False))
FEAT_STOP_AFTER_FAULT_WAIT_SEC = int(FEAT.get("stop_after_fault_wait_sec", 5))

FEAT_PRINT_LS_PATHS_ON_FAULT = FEAT.get("print_ls_paths_on_fault", ["/var/log", "/data"])
# =============================================================================
# Constants (from config)
# =============================================================================
UCOM_COM_PORT = CFG["serial"]["ucom"]
QNX_COM_PORT = CFG["serial"]["qnx"]
SAIL_COM_PORT = CFG["serial"]["sail"]
ANDROID_COM_PORT = CFG["serial"]["android"]
DEFAULT_BAUD = CFG["serial"]["baud"]
READ_TIMEOUT_SEC = CFG["serial"]["read_timeout_sec"]

LOCAL_DIR_SHOW = CFG["local_dirs"]["showmem"]
LOCAL_DIR_SHOW_S = CFG["local_dirs"]["showmem_s"]
LOCAL_DIR_FAULTS = CFG["local_dirs"]["fault_files"]

INIT_COMMANDS: List[str] = CFG["init_commands"]
MONITORED_FILES: List[str] = CFG["monitored_files"]
CORE_PATH: str = CFG["core_path"]
CORE_DEST: str = CFG["core_dest"]

POST_CYCLE_WAIT_SEC = CFG["post_cycle_wait_sec"]

# Ensure local save dirs exist
for d in (LOCAL_DIR_SHOW, LOCAL_DIR_SHOW_S, LOCAL_DIR_FAULTS):
    os.makedirs(d, exist_ok=True)

# =============================================================================
# Unified logging of print to testflow_<ts>.txt
# =============================================================================
_run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
_testflow_path = os.path.join(LOG_DIR, f"testflow_{_run_ts}.txt")
_original_print = builtins.print


def print(*args, **kwargs):
    """Print to console, and also append to logs/testflow_<ts>.txt with timestamp."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _original_print(*args, **kwargs)
    try:
        with open(_testflow_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] " + " ".join(str(a) for a in args) + "\n")
    except Exception:
        pass


def run_and_log(cmd: List[str]):
    """Subprocess wrapper that forwards stdout/stderr to testflow log."""
    try:
        res = subprocess.run(cmd, text=True, capture_output=True, check=False)
        if res.stdout:
            print(res.stdout.strip())
        if res.stderr:
            print(res.stderr.strip())
    except Exception as e:
        print(f"[Error] run_and_log failed: {cmd} -> {e}")

# =============================================================================
# ADB UI sequence (unchanged behavior)
# =============================================================================
def BT_ONOFF(adb_path: str = "adb"):
    # 1. AllApps画面表示
    run_and_log([adb_path, "shell", "input", "tap", "1014", "1157"])
    # 2. Swipe to expose Settings icon
    run_and_log([adb_path, "shell", "input", "swipe", "1500", "600", "700", "600", "300"])
    time.sleep(2)
    # Tap Settings app
    run_and_log([adb_path, "shell", "input", "tap", "1200", "325"])
    time.sleep(2)
    # 3. Connections画面表示
    run_and_log([adb_path, "shell", "input", "tap", "150", "750"])
    time.sleep(2)
    # Bluetooth OFF by command
    run_and_log([adb_path, "shell", "cmd", "bluetooth_manager", "disable"])
    time.sleep(5)
    # Navigate (example tap)
    run_and_log([adb_path, "shell", "input", "tap", "970", "290"])
    time.sleep(2)
    # "+Add"画面表示
    run_and_log([adb_path, "shell", "input", "tap", "1050", "130"])
    time.sleep(5)
    run_and_log([adb_path, "shell", "input", "tap", "890", "230"])
    time.sleep(2)
    # Back to Home
    run_and_log([adb_path, "shell", "input", "tap", "900", "1160"])
    # Bluetooth ON by command
    run_and_log([adb_path, "shell", "cmd", "bluetooth_manager", "enable"])
    time.sleep(5)

# =============================================================================
# Serial Worker (reliable reader/writer with in-memory buffer)
# =============================================================================
class SerialWorker:
    """
    Threaded serial reader with logging + simple pattern wait support.
    """

    def __init__(self, name: str, port_name: str, baudrate: int = DEFAULT_BAUD):
        self.name = name
        self.port_name = port_name
        self.baudrate = baudrate

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.ser: Optional[serial.Serial] = None

        self.port_path = self._resolve_port_path(port_name)

        start_ts = datetime.now().strftime("%m%d_%H%M%S")
        self.log_filename = os.path.join(LOG_DIR, f"log_{self.name}_{start_ts}.txt")

        self._buffer = deque(maxlen=2000)
        self._buffer_lock = threading.Lock()

    def _resolve_port_path(self, port_name: str) -> str:
        """Windows: COMx ; POSIX: /dev/<name> (if not already absolute)."""
        if platform.system().lower().startswith("win"):
            return port_name
        if port_name.startswith("/dev/"):
            return port_name
        return f"/dev/{port_name}"

    def start(self):
        """Start the reader thread and open serial port."""
        print(f"[{self.name}] Opening serial: {self.port_path} @ {self.baudrate}")
        try:
            self.ser = serial.Serial(self.port_path, self.baudrate, timeout=READ_TIMEOUT_SEC)
            print(f"[{self.name}] Serial opened: {self.port_path}")
        except SerialException as e:
            print(f"[{self.name}] ERROR opening {self.port_path}: {e}")
            return

        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()
        print(f"[{self.name}] Reader thread started; logging to {self.log_filename}")
    
    def stop(self):
        """Signal stop and close resources."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception:
                pass
        print(f"[{self.name}] Stopped.")

    def get_serial(self):
        return self.ser
    
    def _reader_loop(self):
        """Read lines from serial and append to log + buffer."""
        try:
            with open(self.log_filename, "a", encoding="utf-8") as f:
                while not self._stop_event.is_set():
                    try:
                        line = self.ser.readline()
                        if not line:
                            continue
                        decoded_line = (
                            line.decode("utf-8", errors="replace")
                            .replace("\r\n", "\n")
                            .replace("\r", "\n")
                            .rstrip("\n")
                        )
                        if decoded_line:
                            ts = datetime.now().strftime("%m-%d %H:%M:%S")
                            entry = f"[{ts}] {decoded_line}"
                            f.write(entry + "\n")
                            f.flush()
                            with self._buffer_lock:
                                self._buffer.append(decoded_line)
                    except Exception as e:
                        print(f"[{self.name}] Read error: {e}")
                        time.sleep(0.2)
        finally:
            print(f"[{self.name}] Reader loop exiting.")

    def clear_buffer(self):
        with self._buffer_lock:
            self._buffer.clear()

    def send_command(self, text: str, run_info: str = "") -> bool:
        """
        Send ONE command terminated with CR '\r' (matches your working script).
        """
        if not self.ser or not self.ser.is_open:
            print(f"[{self.name}] Cannot send; serial not open")
            return False
        cmd = text + "\r"  # one command per write (CR)
        try:
            self.ser.write(cmd.encode("utf-8"))
        except Exception as e:
            print(f"[{self.name}] Write error: {e}")
            return False

        ts = datetime.now().strftime("%m-%d %H:%M:%S")
        try:
            with open(self.log_filename, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] >> {text} {run_info}\n")
        except Exception as e:
            print(f"[{self.name}] Log write error: {e}")
        # print(f"[{self.name}] SENT: {text!r} {run_info}")
        return True

    def wait_for_pattern(self, pattern: Pattern[str], timeout: float = 5.0) -> bool:
        """Wait until a line matching 'pattern' appears within timeout."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._buffer_lock:
                for ln in reversed(self._buffer):
                    if pattern.search(ln):
                        return True
            time.sleep(0.1)
        return False

# =============================================================================
# QNX helpers: single generic capture (no duplication), probes, and artifacts
# =============================================================================
def qnx_ls(qnx: SerialWorker, path: str, flags: str = "la", timeout: float = 8.0) -> bool:
    """
    Print-only directory listing using qnx_capture (no file saved).
    Example: qnx_ls(qnx, "/var/log"), qnx_ls(qnx, "/data", "l").
    """
    tag = f"ls {flags} {path}"
    emit_cmd = f'ls -{flags} "{path}"'
    return qnx_capture(
        qnx=qnx,
        tag=tag,
        emit_cmd=emit_cmd,
        local_path=None,                # print-only
        idle_timeout=timeout,
        check_exists_path=path,
        filter_nslog=True,
    )
def qnx_path_exists(qnx: SerialWorker, path: str, timeout: float = 5.0) -> bool:
    """
    Return True if 'path' exists on QNX by probing with 'ls'.
    Prints EXISTS/MISSING with a unique tag to avoid cross-cycle confusion.
    """
    qnx.clear_buffer()
    tag = datetime.now().strftime("%m%d_%H%M%S")
    qnx.send_command(
        f'if ls {path} >/dev/null 2>&1; then echo "__EXISTS__ {tag}"; else echo "__MISSING__ {tag}"; fi',
        run_info="[EXISTS?]"
    )
    pat_ok = re.compile(rf"__EXISTS__\s+{re.escape(tag)}")
    pat_ng = re.compile(rf"__MISSING__\s+{re.escape(tag)}")

    deadline = time.time() + timeout
    while time.time() < deadline:
        with qnx._buffer_lock:
            for ln in reversed(qnx._buffer):
                if pat_ok.search(ln):
                    print(f"[QNX] EXISTS: {path} ({tag})")
                    return True
                if pat_ng.search(ln):
                    print(f"[QNX] MISSING: {path} ({tag})")
                    return False
        time.sleep(0.1)
    print(f"[QNX] UNKNOWN (timeout): {path} ({tag})")
    return False


def qnx_capture(
    qnx: SerialWorker,
    tag: str,
    emit_cmd: str,
    local_path: Optional[str],         # <-- allow None for print-only mode
    idle_timeout: float = 12.0,
    check_exists_path: Optional[str] = None,
    filter_nslog: bool = True,
) -> bool:
    """
    Generic capture to PC/console:
      - BEGIN/END markers using 'tag'.
      - If 'check_exists_path' is given, skip and emit MISSING when absent.
      - Save payload lines to 'local_path' when provided; if None, print-only.
    """
    nslog_pat = re.compile(r'^\[NSLog\].*')
    pat_begin = re.compile(r'^__BEGIN__\s+(.+)$')
    pat_end   = re.compile(r'^__END__\s+(.+)$')
    pat_miss  = re.compile(r'^__MISSING__\s+(.+)$')

    qnx.clear_buffer()
    if check_exists_path:
        wrapped = (
            f'if ls "{check_exists_path}" >/dev/null 2>&1; then '
            f'echo "__BEGIN__ {tag}"; {emit_cmd}; echo "__END__ {tag}"; '
            f'else echo "__MISSING__ {tag}"; fi'
        )
    else:
        wrapped = f'echo "__BEGIN__ {tag}"; {emit_cmd}; echo "__END__ {tag}"'

    if not qnx.send_command(wrapped, run_info='[CAPTURE]'):
        print(f"[QNX][ERROR] send_command failed: {wrapped!r}")
        return False

    current_tag: Optional[str] = None
    current_lines: List[str] = []
    next_idx = 0
    last_activity = time.time()

    while True:
        with qnx._buffer_lock:
            buf = list(qnx._buffer)
        progressed = False

        for s in buf[next_idx:]:
            sline = s.strip()

            # Missing guard
            m_miss = pat_miss.match(sline)
            if m_miss and m_miss.group(1) == tag:
                print(f"[QNX] MISSING: {tag} (capture skipped)")
                return False

            # Begin payload
            m_begin = pat_begin.match(sline)
            if m_begin and m_begin.group(1) == tag:
                current_tag = tag
                current_lines = []
                progressed = True
                last_activity = time.time()
                continue

            # End payload
            m_end = pat_end.match(sline)
            if m_end and current_tag and m_end.group(1) == current_tag:
                # Print-only mode when local_path is None
                if local_path is None and (
                    "ls la" in tag or
                    "display_smmu_fault_info.txt" in tag or
                    "postmortem_smmu.txt" in tag
                ):  
                    print(emit_cmd)
                    for ln in current_lines:
                        print(ln)
                    return True                   
                # Save-to-file mode
                try:
                    os.makedirs(os.path.dirname(local_path), exist_ok=True)
                    with open(local_path, "w", encoding="utf-8") as f:
                        for ln in current_lines:
                            if filter_nslog and nslog_pat.match(ln):
                                continue
                            f.write(ln + "\n")
                    print(f"[QNX] Saved: {local_path})")
                    return True
                except Exception as e:
                    print(f"[QNX][ERROR] Saving {local_path} failed: {e}")
                    return False

            # Accumulate payload (between BEGIN/END)
            if current_tag is not None:
                current_lines.append(s)
                progressed = True
                last_activity = time.time()

        next_idx = len(buf)

        if not progressed:
            if time.time() - last_activity > idle_timeout:
                # Best-effort print-only when timeout and we have lines
                if local_path is None and current_tag and current_lines:
                    print(f"[QNX][WARN] Printed partial ({tag}): {len(current_lines)} lines (timeout)")
                    return False
                print(f"[QNX][WARN] Capture idle-timeout for {tag}")
                return False
            time.sleep(0.1)

def qnx_stream_showmem(qnx: SerialWorker, flag: str, cycle: Optional[int]) -> None:
    """
    Stream 'showmem' and 'showmem -s' with tags and save to LOCAL_DIR_SHOW/LOCAL_DIR_SHOW_S.
    Uses qnx_capture() to avoid code duplication.
    """
    ts = datetime.now().strftime("%m%d_%H%M%S")
    suffix = f"cycle{cycle:04d}_{flag}" if cycle is not None else flag

    tag1 = f"/var/log/showmem_{ts}_{suffix}.txt"      # tag only
    tag2 = f"/var/log/showmem_s_{ts}_{suffix}.txt"    # tag only

    path1 = os.path.join(LOCAL_DIR_SHOW,    os.path.basename(tag1))
    path2 = os.path.join(LOCAL_DIR_SHOW_S,  os.path.basename(tag2))

    # ok1 = qnx_capture(qnx, tag1, "showmem",   path1, idle_timeout=12.0)
    # ok2 = qnx_capture(qnx, tag2, "showmem -s", path2, idle_timeout=12.0)
    qnx_capture(qnx, tag1, "showmem",   path1, idle_timeout=12.0)
    qnx_capture(qnx, tag2, "showmem -s", path2, idle_timeout=12.0)

  

# --- REPLACE qnx_init(...) tail ---
def qnx_init(qnx: SerialWorker):
    for cmd in INIT_COMMANDS:
        qnx.send_command(cmd, run_info="[INIT]")
    if FEAT_COLLECT_SHOWMEM:
        qnx_stream_showmem(qnx, flag="init", cycle=None)

def qnx_fault_scan(qnx: SerialWorker, files: List[str], timeout: float = 5.0) -> Dict[str, bool]:
    """
    Probe a list of files using the ls-exit-status method and return {path: exists_bool}.
    Prints one compact summary line.
    """
    statuses: Dict[str, bool] = {}
    for p in files:
        statuses[p] = qnx_path_exists(qnx, p, timeout=timeout)
    summary = ", ".join(f"{p}={'EXISTS' if ok else 'MISSING'}" for p, ok in statuses.items())
    print(f"[QNX] Fault scan: {summary}")
    return statuses


def qnx_process_artifacts(qnx: SerialWorker, statuses: Dict[str, bool], cycle_idx: int):
    """
    Handle artifacts once per cycle:
      - Pull text fault files (EXISTS) if enabled
      - Move core to CORE_DEST (EXISTS) if enabled
      - Stream showmem once (error/ok) if enabled
    """

    for p in FEAT_PRINT_LS_PATHS_ON_FAULT:
        try:
            qnx_ls(qnx, p, flags="la", timeout=8.0)
        except Exception as e:
            print(f"[QNX][WARN] ls print failed for {p}: {e}")
    # 1) Pull text fault files (exclude core) if enabled
    if FEAT_PULL_FAULT_FILES:
        for p, ok in statuses.items():
            if not ok or p == CORE_PATH:
                continue
            local_path = os.path.join(LOCAL_DIR_FAULTS, os.path.basename(p))
            qnx_capture(
                qnx=qnx,
                tag=p,

                emit_cmd=f'cat "{p}"; echo',  # << add a plain echo to inject a newline
                local_path=local_path,
                idle_timeout=10.0,
                check_exists_path=p,
            )

    # 2) Move core to destination if enabled
    if FEAT_COPY_CORE and statuses.get(CORE_PATH, False):
        qnx.clear_buffer()
        cp_cmd = (
            f'if ls {CORE_PATH} >/dev/null 2>&1; then '
            f'cp {CORE_PATH} {CORE_DEST} && echo "__CORE_COPIED__"; '
            f'else echo "__CORE_MISSING__"; fi'
        )
        qnx.send_command(cp_cmd, run_info='[MOVE CORE]')
        pat_moved = re.compile(r'^__CORE_COPIED__$')
        pat_missing = re.compile(r'^__CORE_MISSING__$')
        t0 = time.time()
        while time.time() - t0 < 5.0:
            with qnx._buffer_lock:
                buf = list(qnx._buffer)
            if any(pat_moved.match(ln.strip()) for ln in buf):
                print(f"[QNX] Core copied to {CORE_DEST}.")
                break
            if any(pat_missing.match(ln.strip()) for ln in buf):
                print("[QNX] Core not present; nothing to copy.")
                break
            time.sleep(0.1)

    # 3) Stream showmem once, choose flag by fault presence if enabled
    if FEAT_COLLECT_SHOWMEM:
        fault_present = any(statuses.values())
        qnx_stream_showmem(qnx, flag=("error" if fault_present else "ok"), cycle=cycle_idx)
 # 4) Print directory listings for quick visual confirmation (console + testflow)

# =============================================================================
# Test controller 
# =============================================================================
class TestController:
    def __init__(self, adb_path: str = "adb"):
        self.devices = {
            "UCOM": UCOM_COM_PORT,
            "QNX": QNX_COM_PORT,
            "SAIL": SAIL_COM_PORT,
            "ANDROID": ANDROID_COM_PORT,
        }
        self.workers: Dict[str, SerialWorker] = {}
        self.adb_path = adb_path

        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.cycles_completed: int = 0
        self.faults_detected: int = 0
        self.stop_reason: str = "completed"

        # Guard to ensure artifacts are processed once per cycle
        self._artifacts_done_cycle: Optional[int] = None

    def start_workers(self):
        for name, port in self.devices.items():
            worker = SerialWorker(name=name, port_name=port, baudrate=DEFAULT_BAUD)
            worker.start()
            self.workers[name] = worker

    def stop_workers(self):
        for w in self.workers.values():
            w.stop()

    def init_phase(self):
        qnx = self.workers.get("QNX")
        if qnx:
            qnx_init(qnx)
        else:
            print("[Init] QNX worker not available (fault checks will be skipped).")

    def run_cycle(self, cycle_idx: int) -> bool:
        """
        Run one cycle: execute BT_ONOFF() and perform a unified fault scan.
        Always returns False so the main loop continues.
        """
        try:
            BT_ONOFF(self.adb_path)
        except Exception as e:
            print(f"[Cycle] BT_ONOFF error on cycle #{cycle_idx}: {e}")

        qnx = self.workers.get("QNX")
        if qnx:
            try:
                statuses = qnx_fault_scan(qnx, MONITORED_FILES, timeout=5.0)
                fault = any(statuses.values())
            except Exception as e:
                print(f"[Cycle] qnx_fault_scan error on cycle #{cycle_idx}: {e}")
                statuses = {}
                fault = False

            # --- REPLACE fault block inside run_cycle(...) ---
        if fault:
            if FEAT_SURFACE_DUMP_ON_FAULT:
                qnx.send_command('echo surfacedump=0xFF > /dev/displaylog', run_info="[surface dump]")
            time.sleep(1)
            print("[Cycle] Fault detected on QNX!")

            self.faults_detected += 1

            # Process artifacts ONCE per cycle (pull files, move/copy core, showmem, print ls -la)
            if self._artifacts_done_cycle != cycle_idx:
                qnx_process_artifacts(qnx, statuses, cycle_idx)
                self._artifacts_done_cycle = cycle_idx

            # --- NEW: optional delayed stop after fault ---
            if FEAT_STOP_ON_FAULT:
                wait_s = max(0, FEAT_STOP_AFTER_FAULT_WAIT_SEC)
                if wait_s:
                    print(f"[Cycle] Stopping in {wait_s} second(s) after fault …")
                    time.sleep(wait_s)
                self.stop_reason = "fault_detected"
                return True  # <- tells the main loop to exit`
    def run(self):
        """Run infinite cycles until user presses Ctrl+C."""
        self.start_time = time.time()
        self.start_workers()
        print("[Main] Workers started. Beginning INIT …")
        self.init_phase()

        cycle_idx = 1
        try:
            while True:
                print(f"[Main] Cycle #{cycle_idx}")
                should_stop = self.run_cycle(cycle_idx)
                if should_stop:
                    break
                self.cycles_completed += 1
                cycle_idx += 1
        except KeyboardInterrupt:
            self.stop_reason = "user_interrupt"
            print("\n[Main] Interrupted by user. Stopping workers…")
        finally:
            self.end_time = time.time()
            self.stop_workers()
            self._print_summary()

    def _print_summary(self):
        start_dt = datetime.fromtimestamp(self.start_time) if self.start_time else None
        end_dt = datetime.fromtimestamp(self.end_time) if self.end_time else None
        duration_sec = int((self.end_time - self.start_time)) if (self.start_time and self.end_time) else 0
        hh = duration_sec // 3600
        mm = (duration_sec % 3600) // 60
        ss = duration_sec % 60

        summary_text = "\n===== TEST SUMMARY =====\n"
        if start_dt:
            summary_text += f"Start time : {start_dt.strftime('%Y-%m-%d %H:%M:%S')}\n"
        if end_dt:
            summary_text += f"End time   : {end_dt.strftime('%Y-%m-%d %H:%M:%S')}\n"
        summary_text += f"Duration   : {hh:02d}:{mm:02d}:{ss:02d}\n"
        summary_text += f"Cycles done: {self.cycles_completed}\n"
        summary_text += f"Faults     : {self.faults_detected}\n"
        summary_text += f"Stop reason: {self.stop_reason}\n"
        summary_text += "========================\n"

        print(summary_text)
        try:
            with open(os.path.join(LOG_DIR, "summary.txt"), "w", encoding="utf-8") as f:
                f.write(summary_text)
        except Exception as e:
            print(f"[Error] Could not write summary to file: {e}")

def main():
    controller = TestController(adb_path="adb")
    controller.run()


if __name__ == "__main__":
    main()
    