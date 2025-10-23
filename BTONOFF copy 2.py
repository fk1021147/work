# -*- coding: utf-8 -*-
"""
Bluetooth stress test and multi-device serial logging (revised).
Key fixes:
- QNX fault detection: stop if EITHER fault file exists.
- QNX command sending: send ONE command per write, terminated with '\r' (as in your working script).
- showmem collection: sequential commands with confirmation markers.
- Reader/writer: normalize newline handling for reliable pattern matching.
"""

from __future__ import annotations
from datetime import datetime
import os
import platform
import re
import subprocess
import threading
import time
from collections import deque
from typing import Optional, Pattern

import serial
from serial import SerialException

import builtins
from datetime import datetime




# ---------------------------
# Constants & Config
# ---------------------------
UCOM_COM_PORT = "COM22"
QNX_COM_PORT  = "COM3"
SAIL_COM_PORT = "COM14"
ANDROID_COM_PORT = "COM12"

DEFAULT_BAUD = 115200
READ_TIMEOUT_SEC = 1.0

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

POST_CYCLE_WAIT_SEC = 30  # required: 15 seconds after each cycle

# ---------------------------
# Utility: subprocess wrapper
# ---------------------------
RESULT_OK = 0
RESULT_NG = 1
RESULT_TO = 2


# Per-run log file for all print outputs (with timestamp)
_run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
_testflow_path = os.path.join(LOG_DIR, f"testflow_{_run_ts}.txt")

_original_print = builtins.print

def print(*args, **kwargs):
    """Print to console, and also append to logs/testflow_<ts>.txt with timestamp."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # console
    _original_print(*args, **kwargs)
    # file
    try:
        with open(_testflow_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] " + " ".join(str(a) for a in args) + "\n")
    except Exception:
        pass


def console_cmd(command_list, timeout: Optional[float] = None):
    """Run a command via subprocess and capture stdout."""
    try:
        proc = subprocess.run(
            command_list,
            capture_output=True,
            text=True,
            check=True,
            shell=False,
            timeout=timeout,
        )
        return RESULT_OK, proc.stdout
    except subprocess.TimeoutExpired:
        return RESULT_TO, ""
    except subprocess.CalledProcessError as e:
        return RESULT_NG, (e.stdout or e.stderr or "")
def run_and_log(cmd: list[str]):
    """
    Run a subprocess command, capture stdout/stderr, and print them
    so they go to both terminal and testflow log.
    """
    try:
        res = subprocess.run(cmd, text=True, capture_output=True, check=False)
        # Forward stdout/stderr through print() so they get logged
        if res.stdout:
            print(res.stdout.strip())
        if res.stderr:
            print(res.stderr.strip())
    except Exception as e:
        print(f"[Error] run_and_log failed: {cmd} -> {e}")
# ---------------------------
# ADB UI sequence 
# ---------------------------
def BT_ONOFF(adb_path: str = "adb"):
    # 1. AllApps画面表示
    run_and_log([adb_path, "shell", "input", "tap", "1014", "1157"])

    # 2. Swipe to expose Settings icon
    run_and_log([adb_path, "shell", "input", "swipe", "1500", "600", "700", "600", "300"])
    time.sleep(2)

    # Tap Settings app
    run_and_log([adb_path, "shell", "input", "tap", "1200", "325"])
    time.sleep(3)

    # 3. Connections画面表示
    run_and_log([adb_path, "shell", "input", "tap", "150", "750"])
    time.sleep(2)

    # Bluetooth OFF by command
    run_and_log([adb_path, "shell", "cmd", "bluetooth_manager", "disable"])
    time.sleep(5)

    # Navigate (example tap)
    run_and_log([adb_path, "shell", "input", "tap", "970", "290"])
    time.sleep(5)

    # "+Add"画面表示
    run_and_log([adb_path, "shell", "input", "tap", "1050", "130"])
    time.sleep(5)
    run_and_log([adb_path, "shell", "input", "tap", "890", "230"])
    time.sleep(2)

    # Back to Home
    run_and_log([adb_path, "shell", "input", "tap", "900", "1160"])

    # Bluetooth ON by command
    run_and_log([adb_path, "shell", "cmd", "bluetooth_manager", "enable"])
    time.sleep(10)

# ---------------------------
# Serial Worker
# ---------------------------
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

        # safe_port = re.sub(r'[^a-zA-Z0-9._\-]', '_', port_name)
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

    def _reader_loop(self):
        """Read lines from serial and append to log + buffer."""
        try:
            with open(self.log_filename, "a", encoding="utf-8") as f:
                while not self._stop_event.is_set():
                    try:
                        line = self.ser.readline()
                        if not line:
                            continue
                        # Normalize CRLF to '\n' and drop trailing newline
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
        cmd = text + "\r"   # match suspend_resume_test's style
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
        print(f"[{self.name}] SENT: {text!r} {run_info}")
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

# ---------------------------
# QNX helpers
# ---------------------------
def qnx_echo_tag(qnx: SerialWorker, tag: str):
    qnx.send_command(f'echo "__TAG__ {tag}"')

def qnx_path_exists(qnx: SerialWorker, path: str, timeout: float = 5.0) -> bool:
    """
    Return True if 'path' exists on QNX by probing with ls.
    Uses the same single-command-per-write style as your other script.
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
                    return True
                if pat_ng.search(ln):
                    return False
        time.sleep(0.1)
    # If we cannot confirm, assume missing to avoid false positives
    return False

def qnx_clear_old_showmem(qnx: SerialWorker):
    """
    Remove previous showmem files on QNX side.
    """
    # delete both patterns; ignore errors if nothing exists
    qnx.send_command('rm -f /var/log/showmem_*.txt /var/log/showmem_s_*.txt', run_info='[CLEAN]')
    time.sleep(0.2)
    # optional: marker so you can see the cleanup happened
    qnx.send_command('echo "__CLEARED__ SHOWMEM"', run_info='[CLEAN]')

def qnx_fault_detect(qnx: SerialWorker, timeout: float = 5.0) -> bool:
    """
    Stop test if EITHER fault file exists.
    (Fix for the 'ls two files together' problem.)
    """
    f1 = "/var/log/display_smmu_fault_info.txt"
    f2 = "/var/log/postmortem_smmu.txt"
    # Check independently and combine with OR
    found = qnx_path_exists(qnx, f1, timeout=timeout) or qnx_path_exists(qnx, f2, timeout=timeout)
    return found

def qnx_init(qnx: SerialWorker):
    """
    Called once at test start; set display logging and collect initial memory logs.
    """
    qnx_clear_old_showmem(qnx)
    qnx.send_command('echo apibtdump > /dev/displaylog0', run_info="[INIT set displaylog0]")
    qnx.send_command('echo apibtdump > /dev/displaylog1', run_info="[INIT set displaylog1]")
    qnx_collect_memorylog(qnx, flag="init")

#
def qnx_collect_memorylog(qnx: SerialWorker, flag: str = "fault", cycle: int | None = None):
    """
    Collect showmem logs on QNX side using HOST time (MMDD_HHMMSS).
    'flag' indicates context (e.g., init / ok / error / periodic).
    'cycle' optionally tags the files with the cycle number.
    """
    ts = datetime.now().strftime("%m%d_%H%M%S")  # HOST timestamp
    suffix = f"cycle{cycle:04d}_{flag}" if cycle is not None else flag
    f1 = f"/var/log/showmem_{ts}_{suffix}.txt"
    f2 = f"/var/log/showmem_s_{ts}_{suffix}.txt"

    qnx.clear_buffer()
    # send sequential commands (one-line each)
    qnx.send_command(f'showmem > "{f1}"', run_info="[MEMLOG]")
    time.sleep(0.2)
    qnx.send_command(f'showmem -s > "{f2}"', run_info="[MEMLOG]")
    time.sleep(0.2)
    qnx.send_command(f'echo "__MEMLOG__ {f1} {f2} {flag}"', run_info="[MEMLOG]")

    ok1 = qnx_path_exists(qnx, f1, timeout=5.0)
    ok2 = qnx_path_exists(qnx, f2, timeout=5.0)
    if ok1 and ok2:
        print(f"[QNX] showmem collected: {f1}, {f2} ({flag})")
    else:
        print(f"[QNX] showmem collection FAILED ({flag}). Exists? f1={ok1}, f2={ok2}")
# ---------------------------
# Test controller
# ---------------------------
class TestController:
    def __init__(self, adb_path: str = "adb"):
        self.devices = {
            "UCOM": UCOM_COM_PORT,
            "QNX":  QNX_COM_PORT,
            "SAIL": SAIL_COM_PORT,
            "ANDROID": ANDROID_COM_PORT,
        }
        self.workers: dict[str, SerialWorker] = {}
        self.adb_path = adb_path

        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.cycles_completed: int = 0
        self.faults_detected: int = 0
        self.stop_reason: str = "completed"

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
        """Run one cycle: execute BT_ONOFF() and check QNX for fault."""
        # (keep your "[Main] Cycle #..." print wherever you decided)
        BT_ONOFF(self.adb_path)

        qnx = self.workers.get("QNX")
        if qnx:
            fault = qnx_fault_detect(qnx, timeout=5.0)
            if fault:
                qnx.send_command('echo surfacedump=0xFF > /dev/displaylog', run_info="[surface dump]")
                time.sleep(1)
                print("[Cycle] Fault detected on QNX! Stopping test.")
                self.faults_detected += 1
                self.stop_reason = "fault_detected"
                # ***** CHANGE THIS LINE (add cycle and 'error') *****
                qnx_collect_memorylog(qnx, flag="error", cycle=cycle_idx)
                time.sleep(1)
                return True
            else:
                print("[Cycle] No fault detected on QNX.")
                # ***** ADD THIS LINE (collect at end of a normal cycle) *****
                qnx_collect_memorylog(qnx, flag="ok", cycle=cycle_idx)
        else:
            print("[Cycle] QNX worker not available; skipping fault check.")

        time.sleep(POST_CYCLE_WAIT_SEC)
        return False

    def run(self):
        """Run infinite cycles until a fault is detected or user presses Ctrl+C."""
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
        end_dt   = datetime.fromtimestamp(self.end_time) if self.end_time else None
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

        # keep terminal output
        print(summary_text)

        # also save to a file next to your other logs
        try:
            with open(os.path.join(LOG_DIR, "summary.txt"), "w", encoding="utf-8") as f:
                f.write(summary_text)
        except Exception as e:
            print(f"[Error] Could not write summary to file: {e}")

# Entrypoint
def main():
    controller = TestController(adb_path="adb")
    controller.run()

if __name__ == "__main__":
    main()
