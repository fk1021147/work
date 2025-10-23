# -*- coding: utf-8 -*-
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

# ----------------------------- Constants & Config -----------------------------
UCOM_COM_PORT = "COM22"
QNX_COM_PORT = "COM13"
SAIL_COM_PORT = "COM3"
ANDROID_COM_PORT = "COM12"

DEFAULT_BAUD = 115200
READ_TIMEOUT_SEC = 1.0
_run_ts = datetime.now().strftime("%m%d_%H%M%S")

LOG_DIR = f"logs{_run_ts}"
os.makedirs(LOG_DIR, exist_ok=True)

# Local save locations on the PC
LOCAL_DIR_SHOW    = os.path.join(LOG_DIR, "showmem")
LOCAL_DIR_SHOW_S  = os.path.join(LOG_DIR, "showmem_s")
LOCAL_DIR_FAULTS  = os.path.join(LOG_DIR, "fault_files")

POST_CYCLE_WAIT_SEC = 30  # required: 15 seconds after each cycle

# ----------------------------- Utility / logging -----------------------------
RESULT_OK = 0
RESULT_NG = 1
RESULT_TO = 2

# Per-run log file for all print outputs (with timestamp)
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
        if res.stdout:
            print(res.stdout.strip())
        if res.stderr:
            print(res.stderr.strip())
    except Exception as e:
        print(f"[Error] run_and_log failed: {cmd} -> {e}")

# ----------------------------- ADB UI sequence -------------------------------
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

# ----------------------------- Serial Worker ---------------------------------
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
        cmd = text + "\r"  # match suspend_resume_test's style
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

# ----------------------------- QNX helpers -----------------------------------
def qnx_echo_tag(qnx: SerialWorker, tag: str):
    qnx.send_command(f'echo "__TAG__ {tag}"')

def qnx_path_exists(qnx: SerialWorker, path: str, timeout: float = 5.0) -> bool:
    """
    Return True if 'path' exists on QNX by probing with ls.
    Also prints the result (EXISTS/MISSING + file path + tag) to testflow.log via print().
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

def qnx_pull_files_to_local(qnx: SerialWorker, remote_paths: list[str], base_dir: str, idle_timeout: float = 10.0):
    """
    For each remote path, probe with ls (like qnx_path_exists). If exists, cat with BEGIN/END and save to PC.
    Saves under base_dir using basename. Logs success/failure per file.
    (No use of [ -f ] test and no mkdir on QNX.)
    """
    try:
        os.makedirs(base_dir, exist_ok=True)
    except Exception as e:
        print(f"[QNX][ERROR] Could not create {base_dir}: {e}")

    pat_begin = re.compile(r'^__BEGIN__\s+(/var/log/\S+)$')
    pat_end   = re.compile(r'^__END__\s+(/var/log/\S+)$')
    pat_miss  = re.compile(r'^__MISSING__\s+(/var/log/\S+)$')
    nslog_pat = re.compile(r'^\[NSLog\].*')

    for rp in remote_paths:
        qnx.clear_buffer()
        cmd = (
            f'if ls "{rp}" >/dev/null 2>&1; then '
            f'echo "__BEGIN__ {rp}"; cat "{rp}"; echo "__END__ {rp}"; '
            f'else echo "__MISSING__ {rp}"; fi'
        )
        if not qnx.send_command(cmd, run_info='[PULL FILE]'):
            print(f"[QNX][ERROR] send_command failed for {rp}")
            continue

        current_path = None
        current_lines: list[str] = []
        next_idx = 0
        last_activity = time.time()
        done = False

        while True:
            with qnx._buffer_lock:
                buf = list(qnx._buffer)

            progressed = False
            for s in buf[next_idx:]:
                sline = s.strip()

                if pat_miss.match(sline):
                    print(f"[QNX] MISSING remote file: {rp}")
                    done = True
                    progressed = True
                    break

                m = pat_begin.match(sline)
                if m and m.group(1) == rp:
                    current_path = rp
                    current_lines = []
                    progressed = True
                    last_activity = time.time()
                    continue

                m = pat_end.match(sline)
                if m and current_path and m.group(1) == current_path:
                    base = os.path.basename(current_path)
                    local_path = os.path.join(base_dir, base)
                    try:
                        with open(local_path, "w", encoding="utf-8") as f:
                            for ln in current_lines:
                                if nslog_pat.match(ln):
                                    continue
                                f.write(ln + "\n")
                        print(f"[QNX] Pulled: {local_path} ({len(current_lines)} lines)")
                    except Exception as e:
                        print(f"[QNX][ERROR] Pull save failed for {local_path}: {e}")
                    finally:
                        current_path = None
                        current_lines = []
                    done = True
                    progressed = True
                    break

                if current_path is not None:
                    current_lines.append(s)
                    progressed = True
                    last_activity = time.time()

            next_idx = len(buf)

            if done:
                break
            if not progressed:
                if time.time() - last_activity > idle_timeout:
                    print(f"[QNX][WARN] Pull idle-timeout for {rp}")
                    break
                time.sleep(0.1)

# --- REPLACE the entire qnx_fault_detect(...) with this version ---
def qnx_fault_detect(qnx: SerialWorker, timeout: float = 5.0) -> bool:
    """
    Detect fault if ANY of the files exist; also pull existing fault files to PC (logs/fault_files).
    Additionally checks /var/log/openwfd_server-QM.core via the same ls-probe mechanism,
    prints all statuses, and moves the core to ~/var when present.
    """
    # f1 = "/var/log/display_smmu_fault_info.txt"
    # f2 = "/var/log/postmortem_smmu.txt"
    # f3 = "/var/log/openwfd_server-QM.core"
    f1 = "f1.txt "
    f2 = "f2.txt" 
    f3 = "f3.txt"

    # Existence checks (each prints its own result via qnx_path_exists)
    ok1 = qnx_path_exists(qnx, f1, timeout=timeout)
    ok2 = qnx_path_exists(qnx, f2, timeout=timeout)
    ok3 = qnx_path_exists(qnx, f3, timeout=timeout)

    status1 = "EXISTS" if ok1 else "MISSING"
    status2 = "EXISTS" if ok2 else "MISSING"
    status3 = "EXISTS" if ok3 else "MISSING"
    print(f"[QNX] Fault check: {f1}={status1}, {f2}={status2}, {f3}={status3}")

    # Pull text fault files to PC when they exist
    to_pull = []
    if ok1: to_pull.append(f1)
    if ok2: to_pull.append(f2)
    if to_pull:
        qnx_pull_files_to_local(qnx, to_pull, base_dir=LOCAL_DIR_FAULTS)

    # If the core exists, move it to ~/var (no mkdir; assume it exists)
    if ok3:
        qnx_move_core_to_homevar(qnx,f3)

    # Overall "fault" condition is true if ANY of the fault indicators exist
    return ok1 or ok2 or ok3

def qnx_init(qnx: SerialWorker):
    """
    Called once at test start; set display logging and collect initial memory logs.
    """
    qnx.send_command('echo apibtdump > /dev/displaylog0', run_info="[INIT set displaylog0]")
    qnx.send_command('echo apibtdump > /dev/displaylog1', run_info="[INIT set displaylog1]")
    qnx_collect_memorylog(qnx, flag="init")

def qnx_move_core_to_homevar(qnx: SerialWorker,path):

    qnx.clear_buffer()
    mv_cmd = (
        'if ls {path} >/dev/null 2>&1; then '
        'mv {path} ~/data/ && echo "__CORE_MOVED__"; '
        'else echo "__CORE_MISSING__"; fi'
    )
    qnx.send_command(mv_cmd, run_info='[MOVE CORE]')
    time.sleep(30)
    pat_moved   = re.compile(r'^__CORE_MOVED__$')
    pat_missing = re.compile(r'^__CORE_MISSING__$')
    t0 = time.time()
    while time.time() - t0 < 5.0:
        with qnx._buffer_lock:
            buf = list(qnx._buffer)
        if any(pat_moved.match(ln.strip()) for ln in buf):
            print("[QNX] Core moved to ~/data.")
            return
        if any(pat_missing.match(ln.strip()) for ln in buf):
            print("[QNX] Core not present; nothing to move.")
            return
        time.sleep(0.1)
    print("[QNX][WARN] No confirmation about core move within timeout.")

def qnx_collect_memorylog(qnx: SerialWorker, flag: str = "fault", cycle: Optional[int] = None):
    """
    Stream 'showmem' and 'showmem -s' directly from QNX to PC and save into logs/showmem*.
    Does NOT create any files on QNX. Uses BEGIN/END markers like qnx_path_exists style.
    """
    # ensure local dirs on PC
    try:
        os.makedirs(LOCAL_DIR_SHOW, exist_ok=True)
        os.makedirs(LOCAL_DIR_SHOW_S, exist_ok=True)
    except Exception as e:
        print(f"[QNX][ERROR] Could not create local showmem dirs: {e}")

    ts = datetime.now().strftime("%m%d_%H%M%S")
    suffix = f"cycle{cycle:04d}_{flag}" if cycle is not None else flag
    tag1 = f"/var/log/showmem_{ts}_{suffix}.txt"      # just a tag for markers
    tag2 = f"/var/log/showmem_s_{ts}_{suffix}.txt"    # just a tag for markers

    pat_begin = re.compile(r'^__BEGIN__\s+(/var/log/\S+)$')
    pat_end   = re.compile(r'^__END__\s+(/var/log/\S+)$')
    nslog_pat = re.compile(r'^\[NSLog\].*')

    def stream_one(cmd: str, tag_path: str, local_dir: str, idle_timeout: float = 12.0) -> bool:
        """Wrap command with BEGIN/END markers, capture payload, and save locally."""
        qnx.clear_buffer()
        wrapped = f'echo "__BEGIN__ {tag_path}"; {cmd}; echo "__END__ {tag_path}"'
        if not qnx.send_command(wrapped, run_info='[MEM STREAM]'):
            print(f"[QNX][ERROR] send_command failed: {wrapped!r}")
            return False

        current_path = None
        current_lines: list[str] = []
        next_idx = 0
        last_activity = time.time()

        while True:
            with qnx._buffer_lock:
                buf = list(qnx._buffer)

            progressed = False
            for s in buf[next_idx:]:
                sline = s.strip()

                m = pat_begin.match(sline)
                if m and m.group(1) == tag_path:
                    current_path = tag_path
                    current_lines = []
                    progressed = True
                    last_activity = time.time()
                    continue

                m = pat_end.match(sline)
                if m and current_path and m.group(1) == current_path:
                    base = os.path.basename(tag_path)
                    local_path = os.path.join(local_dir, base)
                    try:
                        with open(local_path, "w", encoding="utf-8") as f:
                            for ln in current_lines:
                                if nslog_pat.match(ln):
                                    continue
                                f.write(ln + "\n")
                        print(f"[QNX] Saved: {local_path} ({len(current_lines)} lines)")
                        return True
                    except Exception as e:
                        print(f"[QNX][ERROR] Saving {local_path} failed: {e}")
                        return False

                if current_path is not None:
                    current_lines.append(s)
                    progressed = True
                    last_activity = time.time()

            next_idx = len(buf)

            if not progressed:
                if time.time() - last_activity > idle_timeout:
                    print(f"[QNX][WARN] Stream capture idle-timeout for {tag_path}")
                    return False
                time.sleep(0.1)

    ok1 = stream_one("showmem",   tag1, LOCAL_DIR_SHOW)
    ok2 = stream_one("showmem -s", tag2, LOCAL_DIR_SHOW_S)

    if ok1 and ok2:
        print(f"[QNX] showmem streamed and saved ({flag})")
    else:
        print(f"[QNX][WARN] showmem stream save incomplete ({flag}). ok1={ok1}, ok2={ok2}")

# ----------------------------- Test controller --------------------------------
class TestController:
    def __init__(self, adb_path: str = "adb"):
        self.devices = {
            "UCOM": UCOM_COM_PORT,
            "QNX": QNX_COM_PORT,
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
        """
        Run one cycle: execute BT_ONOFF() and check QNX for fault.
        Never stops the test automatically; keeps running even after a fault is detected.
        Always returns False so the main loop continues.
        """
        try:
            BT_ONOFF(self.adb_path)
        except Exception as e:
            print(f"[Cycle] BT_ONOFF error on cycle #{cycle_idx}: {e}")

        qnx = self.workers.get("QNX")
        if qnx:
            try:
                fault = qnx_fault_detect(qnx, timeout=5.0)
            except Exception as e:
                print(f"[Cycle] qnx_fault_detect error on cycle #{cycle_idx}: {e}")
                fault = False

            if fault:
                qnx.send_command('echo surfacedump=0xFF > /dev/displaylog', run_info="[surface dump]")
                time.sleep(10)
                print("[Cycle] Fault detected on QNX! (continuing test)")
                self.faults_detected += 1
                # Stream showmem directly to PC
                qnx_collect_memorylog(qnx, flag="error", cycle=cycle_idx)
                # Move core file on QNX (if present)
                qnx_move_core_to_homevar(qnx)
                time.sleep(1)
            else:
                print("[Cycle] No fault detected on QNX.")
                # Stream showmem directly to PC
                # Move core file on QNX (if present)
        else:
            print("[Cycle] QNX worker not available; skipping fault check.")

        time.sleep(POST_CYCLE_WAIT_SEC)
        return False  # always continue

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

# -------------------------------- Entrypoint ---------------------------------
def main():
    controller = TestController(adb_path="adb")
    controller.run()

if __name__ == "__main__":
    main()