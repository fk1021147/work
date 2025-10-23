# -*- coding: utf-8 -*-
"""
Bluetooth stress test and multi-device serial logging.

Behavior:
- Uses HOST (PC) timestamps for all filenames and terminal prints.
- Starts serial reader threads for each device (UCOM, QNX, SAIL, ANDROID).
- At INIT (once), sends "echo apibtdump" to QNX displaylog0/1, and collects initial showmem logs.
- Each cycle: run BT_ONOFF() UI actions -> QNX fault check.
- If either /var/log/display_smmu_fault_info.txt OR /var/log/postmortem_smmu.txt exists on QNX -> stop test.
- If no error, sleeps 15 seconds, increments cycle count, and continues.
- Prints a final test summary on exit (fault or Ctrl+C).
- No run.txt file is written.
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

# ------------------------------
# Constants & Config
# ------------------------------

# Port configuration (adjust for your environment)
UCOM_COM_PORT = "COM22"
QNX_COM_PORT = "COM3"
SAIL_COM_PORT = "COM14"
ANDROID_COM_PORT = "COM12"
DEFAULT_BAUD = 115200
READ_TIMEOUT_SEC = 1.0

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# Timings (seconds)
POST_CYCLE_WAIT_SEC = 15  # required: 15 seconds after each cycle

# ------------------------------
# Utility: subprocess wrapper
# ------------------------------

RESULT_OK = 0
RESULT_NG = 1
RESULT_TO = 2

def console_cmd(command_list, timeout: Optional[float] = None):
    """
    Run a command via subprocess and capture stdout.

    Returns: (result_code, stdout_text)
    result_code in {RESULT_OK, RESULT_NG, RESULT_TO}
    """
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

# ------------------------------
# ADB UI sequence for Bluetooth scenario
# ------------------------------

def BT_ONOFF(adb_path: str = "adb"):
    """
    Run your UI-driven Bluetooth OFF/ON sequence via adb input events.

    Steps:
    1. Tap All Apps.
    2. Swipe to reveal Settings (example coords).
    3. Tap Settings.
    4. Tap Connections.
    5. Disable Bluetooth via cmd.
    6. Navigate and tap UI items as per your flow.
    7. Return to Home.

    NOTE: Coordinates are device/layout-specific. Adjust if needed.
    """
    # 1. AllApps画面表示
    subprocess.run([adb_path, "shell", "input", "tap", "1014", "1157"], check=False)

    # 2. Swipe to expose Settings icon
    subprocess.run([adb_path, "shell", "input", "swipe", "1500", "600", "700", "600", "300"], check=False)
    time.sleep(2)

    # Tap Settings app
    subprocess.run([adb_path, "shell", "input", "tap", "1200", "325"], check=False)
    time.sleep(3)

    # 3. Connections画面表示
    subprocess.run([adb_path, "shell", "input", "tap", "150", "750"], check=False)
    time.sleep(2)

    # Bluetooth OFF by command (more reliable than UI toggle)
    subprocess.run([adb_path, "shell", "cmd", "bluetooth_manager", "disable"], check=False)
    time.sleep(5)

    # Navigate (example tap)
    subprocess.run([adb_path, "shell", "input", "tap", "970", "290"], check=False)
    time.sleep(5)

    # "+Add"画面表示
    subprocess.run([adb_path, "shell", "input", "tap", "1050", "130"], check=False)
    time.sleep(5)

    subprocess.run([adb_path, "shell", "input", "tap", "890", "230"], check=False)

    # Skips for Device Name selection and D shift
    time.sleep(2)

    # Back to Home
    subprocess.run([adb_path, "shell", "input", "tap", "900", "1160"], check=False)

    # Bluetooth ON by command
    subprocess.run([adb_path, "shell", "cmd", "bluetooth_manager", "enable"], check=False)
    time.sleep(10)

# ------------------------------
# Serial Worker
# ------------------------------

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

        # Resolve platform-appropriate port path
        self.port_path = self._resolve_port_path(port_name)

        # Host-based start timestamp in filename (MMDD_HHMMSS)
        safe_port = re.sub(r'[^a-zA-Z0-9._-]', '_', port_name)
        start_ts = datetime.now().strftime("%m%d_%H%M%S")
        self.log_filename = os.path.join(LOG_DIR, f"log_{safe_port}_{start_ts}.txt")

        # Internal line buffer for pattern matching
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
                        decoded_line = line.decode("utf-8", errors="replace").rstrip("\r")
                        if decoded_line:
                            ts = datetime.now().strftime("%m-%d %H:%M:%S")
                            entry = f"[{ts}] {decoded_line}"
                            f.write(entry + "\r")
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

    def send_command(self, text: str, run_info: str = ""):
        """
        Send a single command terminated with LF '\n' (no leading CR) to avoid ksh parsing issues.
        """
        if not self.ser or not self.ser.is_open:
            print(f"[{self.name}] Cannot send; serial not open")
            return False

        cmd = text + "\r"  # LF only avoids ksh mis-parsing

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

# ------------------------------
# QNX operations
# ------------------------------

def qnx_init(qnx: SerialWorker):
    """
    Called once at test start; set display logging and collect initial memory logs.
    """
    # Send apibtdump only once (first time)
    qnx.send_command("echo apibtdump > /dev/displaylog0", run_info="[INIT] set displaylog0")
    qnx.send_command("echo apibtdump > /dev/displaylog1", run_info="[INIT] set displaylog1")

    # Initial memory logs (host timestamp, separate files)
    qnx_collect_memorylog(qnx, flag="init")

def qnx_collect_memorylog(qnx: SerialWorker, flag: str = "fault"):
    """
    Collect showmem logs on QNX side using HOST time (MMDD_HHMMSS).
    Save showmem and showmem -s into separate files.
    Called at init and again when an error occurs.
    """
    ts = datetime.now().strftime("%m%d_%H%M%S")  # HOST timestamp
    f1 = f"/var/log/showmem_{ts}.txt"
    f2 = f"/var/log/showmem_s_{ts}.txt"

    cmd = (
        f'F1="{f1}"; '
        f'F2="{f2}"; '
        'echo "Collecting showmem to $F1 and showmem -s to $F2"; '
        'showmem > "$F1"; '
        'showmem -s > "$F2"; '
        f'echo "__MEMLOG__ $F1 $F2 {flag}"'
    )
    qnx.clear_buffer()  # avoid stale markers
    qnx.send_command(cmd, run_info="[MEMLOG]")

def qnx_fault_detect(qnx: SerialWorker, timeout: float = 5.0) -> bool:
    """
    Return True if either fault file exists on QNX (error condition).
    Avoid stale matches via buffer clear and a unique tag.
    Implemented using 'if ls' to avoid ksh bracket/test parsing issues.
    """
    qnx.clear_buffer()
    tag = datetime.now().strftime("%m%d_%H%M%S")  # unique tag per check

    # POSIX-safe check: ls both paths; if any exists, ls succeeds -> FOUND.
    cmd = (
        f'if ls /var/log/display_smmu_fault_info.txt /var/log/postmortem_smmu.txt >/dev/null 2>&1; '
        f'then echo "__FAULT_FOUND__ {tag}"; else echo "__FAULT_NOT_FOUND__ {tag}"; fi'
    )
    qnx.send_command(cmd, run_info="[CHECK_FAULT]")

    pat_found = re.compile(rf"__FAULT_FOUND__\s+{re.escape(tag)}")
    pat_not_found = re.compile(rf"__FAULT_NOT_FOUND__\s+{re.escape(tag)}")

    deadline = time.time() + timeout
    while time.time() < deadline:
        with qnx._buffer_lock:
            for ln in reversed(qnx._buffer):
                if pat_found.search(ln):
                    return True
                if pat_not_found.search(ln):
                    return False
        time.sleep(0.1)

    # Timeout -> consider no fault to avoid false positives
    return False

# ------------------------------
# Test controller
# ------------------------------

class TestController:
    def __init__(self, adb_path: str = "adb"):
        # Device name -> port
        self.devices = {
            "UCOM": UCOM_COM_PORT,
            "QNX": QNX_COM_PORT,
            "SAIL": SAIL_COM_PORT,
            "ANDROID": ANDROID_COM_PORT,
        }
        self.workers: dict[str, SerialWorker] = {}
        self.adb_path = adb_path

        # Summary stats
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
        """
        Run one cycle: execute BT_ONOFF() and check QNX for fault.
        Returns True if fault found (stop), False otherwise (continue).
        """
        print(f"[Main] Cycle #{cycle_idx}")

        # Your UI-driven Bluetooth sequence
        BT_ONOFF(self.adb_path)

        # Then check QNX for faults
        qnx = self.workers.get("QNX")
        if qnx:
            fault = qnx_fault_detect(qnx, timeout=5.0)
            if fault:
                qnx.send_command("echo surfacedump=0xFF > /dev/displaylog", run_info="surface dump")
                time.sleep(100)
                print("[Cycle] Fault detected on QNX! Stopping test.")
                self.faults_detected += 1
                self.stop_reason = "fault_detected"
                qnx_collect_memorylog(qnx, flag="fault")
                time.sleep(100)
                return True
            else:
                print("[Cycle] No fault detected on QNX.")
        else:
            print("[Cycle] QNX worker not available; skipping fault check.")

        time.sleep(POST_CYCLE_WAIT_SEC)
        return False

    def run(self):
        """
        Run infinite cycles until a fault is detected or user presses Ctrl+C.
        """
        self.start_time = time.time()
        self.start_workers()
        print("[Main] Workers started. Beginning INIT …")
        self.init_phase()

        cycle_idx = 1
        try:
            while True:
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
        """Print a final test summary."""
        start_dt = datetime.fromtimestamp(self.start_time) if self.start_time else None
        end_dt   = datetime.fromtimestamp(self.end_time) if self.end_time else None
        duration_sec = int((self.end_time - self.start_time)) if (self.start_time and self.end_time) else 0
        hh = duration_sec // 3600
        mm = (duration_sec % 3600) // 60
        ss = duration_sec % 60

        print("\n===== TEST SUMMARY =====")
        if start_dt:
            print(f"Start time : {start_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        if end_dt:
            print(f"End time   : {end_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Duration   : {hh:02d}:{mm:02d}:{ss:02d}")
        print(f"Cycles done: {self.cycles_completed}")
        print(f"Faults     : {self.faults_detected}")
        print(f"Stop reason: {self.stop_reason}")
        print("========================")

# ------------------------------
# Entrypoint
# ------------------------------

def main():
    controller = TestController(adb_path="adb")  # Adjust if adb is not in PATH
    controller.run()

if __name__ == "__main__":
    main()