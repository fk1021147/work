import os
import time
import re
import serial  # pyserial

# ---------------- User settings ----------------
QNX_COM_PORT = "COM3"          # Change to your QNX serial port (e.g., "COM3")
BAUDRATE      = 115200
READ_TIMEOUT  = 1.0            # seconds
IDLE_TIMEOUT  = 15             # stop if no data for ~15 sec

# Base local folder (use your chosen run stamp)
RUN_TS = time.strftime("1021_100409")  # leave as-is if you want fixed stamp

BASE_DIR          = os.path.join(os.getcwd(), RUN_TS)
LOCAL_DIR_SHOW    = os.path.join(BASE_DIR, "showmem")
LOCAL_DIR_SHOW_S  = os.path.join(BASE_DIR, "showmem_s")

# -------------- QNX side command ---------------
# Emit per-file markers and content, then a final __DONE__.
# Two loops to clearly separate showmem and showmem_s.
QNX_CMD = (
    'for f in /var/log/showmem_*_cycle*.txt; do '
    'echo "__BEGIN__ $f"; cat "$f"; echo "__END__ $f"; '
    'done; '
    'for f in /var/log/showmem_s_*_cycle*.txt; do '
    'echo "__BEGIN__ $f"; cat "$f"; echo "__END__ $f"; '
    'done; '
    'echo "__DONE__"'
)

# ---------------- Helpers ----------------
def open_qnx_serial(port: str, baud: int, timeout: float) -> serial.Serial:
    """Open the serial port to QNX."""
    ser = serial.Serial(port, baudrate=baud, timeout=timeout)
    print(f"[SHOWMEM_PULL] Serial opened: {port} @ {baud}")
    return ser

def send_one_command(ser: serial.Serial, cmd: str):
    """Send ONE command terminated with CR to QNX."""
    payload = cmd + "\r"  # CR per environment
    ser.write(payload.encode("utf-8"))
    print(f"[SHOWMEM_PULL] SENT: {cmd!r}")

def ensure_dirs():
    """Create top-level local directories for this run."""
    os.makedirs(LOCAL_DIR_SHOW,   exist_ok=True)
    os.makedirs(LOCAL_DIR_SHOW_S, exist_ok=True)
    print(f"[SHOWMEM_PULL] Saving to:\n  {LOCAL_DIR_SHOW}\n  {LOCAL_DIR_SHOW_S}")

# ---------------- Main ----------------
def pull_and_save_each_file():
    # Prepare local folders
    ensure_dirs()

    ser = None
    try:
        ser = open_qnx_serial(QNX_COM_PORT, BAUDRATE, READ_TIMEOUT)
        time.sleep(0.2)
        # Clear any pending bytes
        ser.read_all()

        # Send QNX command to emit files with markers and __DONE__
        send_one_command(ser, QNX_CMD)
        print("[SHOWMEM_PULL] Receiving…")

        # Regex for markers and filtering
        pat_begin = re.compile(r'^__BEGIN__\s+(/var/log/[^ \r\n]+)$')
        pat_end   = re.compile(r'^__END__\s+(/var/log/[^ \r\n]+)$')
        pat_done  = re.compile(r'^__DONE__\s*$')
        nslog_pat = re.compile(r'^\[NSLog\].*')  # exclude lines starting with [NSLog]

        current_path  = None
        current_lines = []
        bytes_written = 0
        lines_seen    = 0
        idle_ticks    = 0
        max_idle_ticks = int(IDLE_TIMEOUT / READ_TIMEOUT) if READ_TIMEOUT > 0 else IDLE_TIMEOUT

        def flush_current():
            """Write captured lines to the correct local file based on path."""
            nonlocal current_path, current_lines, bytes_written
            if not current_path:
                return

            base = os.path.basename(current_path)

            # Route to showmem_s or showmem based on filename
            if "_s_" in base or base.startswith("showmem_s_"):
                local_path = os.path.join(LOCAL_DIR_SHOW_S, base)
            else:
                local_path = os.path.join(LOCAL_DIR_SHOW, base)

            with open(local_path, "w", encoding="utf-8") as f:
                # Write only non-[NSLog] lines
                for ln in current_lines:
                    if nslog_pat.match(ln):
                        continue
                    f.write(ln + "\n")
                    bytes_written += len((ln + "\n").encode("utf-8"))

            print(f"[SHOWMEM_PULL] Saved: {local_path} ({len(current_lines)} lines)")
            current_path  = None
            current_lines = []

        while True:
            raw = ser.readline()
            if not raw:
                idle_ticks += 1
                if idle_ticks >= max_idle_ticks:
                    print(f"[SHOWMEM_PULL][WARN] Idle timeout. Total bytes written: {bytes_written}")
                    break
                continue

            idle_ticks = 0
            line = raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
            sline = line.strip()
            lines_seen += 1

            # DONE -> flush any open file and exit
            if pat_done.match(sline):
                flush_current()
                print(f"[SHOWMEM_PULL] Completed (__DONE__). Total bytes: {bytes_written}")
                break

            # BEGIN marker -> flush previous (if any) then start new
            m_begin = pat_begin.match(sline)
            if m_begin:
                flush_current()
                current_path  = m_begin.group(1)
                current_lines = []
                # Skip marker line itself
                continue

            # END marker -> save current file
            m_end = pat_end.match(sline)
            if m_end:
                # Safety: If END path differs, still flush current
                flush_current()
                # Skip marker line itself
                continue

            # Otherwise it's content: buffer for current file
            if current_path is not None:
                current_lines.append(line)
            # else: outside BEGIN/END -> ignore shell noise

            # Progress every 300 lines
            if lines_seen % 300 == 0:
                print(f"[SHOWMEM_PULL] Progress: {bytes_written} bytes written so far…")

        print("[SHOWMEM_PULL] Done.")

    except Exception as e:
        print(f"[SHOWMEM_PULL][ERROR] {e}")
    finally:
        if ser:
            try:
                ser.close()
                print("[SHOWMEM_PULL] Serial closed.")
            except Exception:
                pass
def qnx_delete_showmem_files(ser: serial.Serial):
    """
    Delete all files starting with 'showmem' in /var/log on QNX.
    """
    cmd = 'sh -c "rm -f /var/log/showmem_* /var/log/showmem_s_*; echo __DELETE_DONE__"'
    send_one_command(ser, cmd)
    print("[SHOWMEM_PULL] Delete command sent to QNX.")

if __name__ == "__main__":
    ser = None
    try:
        ser = open_qnx_serial(QNX_COM_PORT, BAUDRATE, READ_TIMEOUT)
        time.sleep(0.2)
        ser.read_all()  # clear buffer

        # Delete all showmem files on QNX
        qnx_delete_showmem_files(ser)

        # Optionally read QNX response
        while True:
            raw = ser.readline()
            if not raw:
                break
            print(raw.decode("utf-8", errors="replace").strip())

    except Exception as e:
        print(f"[SHOWMEM_PULL][ERROR] {e}")
    finally:
        if ser:
            try:
                ser.close()
                print("[SHOWMEM_PULL] Serial closed.")
            except Exception:
                pass