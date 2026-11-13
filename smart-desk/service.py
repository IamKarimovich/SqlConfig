"""Arxa fonda işləyən Smart Desk prosesini idarə etmək (ayarlar tətbiqi və desk.py üçün).

- desk.pid  : işləyən prosesin PID-i (eyni anda iki nüsxə kameranı tutmasın)
- desk.stop : bu fayl yarananda işləyən proses səliqə ilə dayanır (kameranı buraxır)
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PID_FILE = BASE_DIR / "desk.pid"
STOP_FILE = BASE_DIR / "desk.stop"
LOG_FILE = BASE_DIR / "desk.log"
DESK = BASE_DIR / "desk.py"

IS_WIN = os.name == "nt"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
_children: dict[int, subprocess.Popen] = {}  # bu prosesin başlatdıqları (Linux-da zombi qalmasın)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid in _children:
        return _children[pid].poll() is None
    if IS_WIN:
        # os.kill(pid, 0) Windows-da prosesi ÖLDÜRÜR — ona görə tasklist
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, creationflags=NO_WINDOW).stdout.lower()
        return "python" in out
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def read_pid() -> int | None:
    try:
        return int(PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return None


def running_pid() -> int | None:
    pid = read_pid()
    return pid if pid and _pid_alive(pid) else None


def write_pid() -> None:
    STOP_FILE.unlink(missing_ok=True)
    PID_FILE.write_text(str(os.getpid()))


def clear_pid() -> None:
    if read_pid() == os.getpid():
        PID_FILE.unlink(missing_ok=True)


def stop_requested() -> bool:
    if STOP_FILE.exists():
        STOP_FILE.unlink(missing_ok=True)
        return True
    return False


def python_exe(windowless: bool = True) -> str:
    exe = Path(sys.executable)
    if IS_WIN:
        cand = exe.with_name("pythonw.exe" if windowless else "python.exe")
        if cand.exists():
            return str(cand)
    return str(exe)


def child_env() -> dict:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"            # Windows konsolunda emoji/ə xətası olmasın
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def start() -> bool:
    """Arxa fonda, pəncərəsiz başlat. Artıq işləyirsə heç nə etmir."""
    if running_pid():
        return False
    if IS_WIN:
        p = subprocess.Popen([python_exe(True), str(DESK)], cwd=BASE_DIR, creationflags=DETACHED,
                             close_fds=True, env=child_env())
    else:
        log = open(LOG_FILE, "a", encoding="utf-8")  # noqa: SIM115
        p = subprocess.Popen([sys.executable, str(DESK)], cwd=BASE_DIR, stdout=log, stderr=log,
                             start_new_session=True, env=child_env())
    _children[p.pid] = p
    return True


def stop(timeout: float = 8.0) -> bool:
    """Əvvəlcə səliqə ilə (desk.stop), alınmasa məcburi dayandırır."""
    pid = running_pid()
    if not pid:
        return False
    STOP_FILE.touch()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            break
        time.sleep(0.3)
    else:
        if IS_WIN:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, creationflags=NO_WINDOW)
        else:
            import signal
            os.kill(pid, signal.SIGKILL)
        time.sleep(0.5)
    STOP_FILE.unlink(missing_ok=True)
    PID_FILE.unlink(missing_ok=True)
    return True


def run_exclusive(args: list[str]) -> tuple[int, str]:
    """Kameranı istifadə edən əmri (enroll, preview, whoami) işə salır.

    Arxa fon prosesi işləyirsə, əvvəlcə dayandırılır, sonra yenidən başladılır.
    (çıxış kodu, çıxış mətni) qaytarır.
    """
    was_running = stop()
    try:
        p = subprocess.run([python_exe(True), *args], cwd=BASE_DIR, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=child_env(),
                           creationflags=NO_WINDOW)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    finally:
        if was_running:
            start()


def run_capture(args: list[str], timeout: float = 120) -> tuple[int, str]:
    """Kamerasız köməkçi əmr (məs. faces.py check) — nəticəni mətn kimi qaytarır."""
    p = subprocess.run([python_exe(True), *args], cwd=BASE_DIR, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=child_env(),
                       creationflags=NO_WINDOW, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")
