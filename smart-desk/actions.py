"""OS səviyyəli əməliyyatlar: ekranı kilidləmək, proqramları açmaq, Telegram."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import threading
import webbrowser

import requests

SYSTEM = platform.system()  # "Windows" | "Darwin" | "Linux"
OS_KEY = {"Windows": "windows", "Darwin": "macos"}.get(SYSTEM, "linux")


# ---------------------------------------------------------------- kilid
def lock_screen() -> bool:
    try:
        if SYSTEM == "Windows":
            import ctypes
            return bool(ctypes.windll.user32.LockWorkStation())
        if SYSTEM == "Darwin":
            # Ctrl+Cmd+Q — macOS-un rəsmi "Lock Screen" qısayolu
            r = subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to keystroke "q" using {control down, command down}'],
                capture_output=True)
            if r.returncode == 0:
                return True
            return subprocess.run(["pmset", "displaysleepnow"]).returncode == 0
        # Linux: ən çox yayılmış variantları ardıcıl yoxla
        for cmd in (["loginctl", "lock-session"],
                    ["xdg-screensaver", "lock"],
                    ["gnome-screensaver-command", "-l"],
                    ["dm-tool", "lock"],
                    ["xflock4"]):
            if shutil.which(cmd[0]) and subprocess.run(cmd, capture_output=True).returncode == 0:
                return True
    except Exception as e:  # noqa: BLE001
        print(f"[lock] xəta: {e}")
    return False


# ---------------------------------------------------------------- proqramlar
def _expand(path: str) -> str:
    return os.path.expandvars(os.path.expanduser(path))


def find_app(entry: dict) -> str | None:
    """{"paths": [...]} siyahısından mövcud olan ilk faylı qaytarır."""
    for p in entry.get("paths") or []:
        full = _expand(p)
        if os.path.isfile(full):
            return full
    return None


def is_running(exe_path: str) -> bool:
    """Proqram artıq açıqdırsa ikinci pəncərə açmayaq (Windows: tasklist, digərləri: pgrep)."""
    name = os.path.basename(exe_path)
    try:
        if SYSTEM == "Windows":
            out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"],
                                 capture_output=True, text=True,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            return name.lower() in out.lower()
        return subprocess.run(["pgrep", "-xi", os.path.splitext(name)[0]],
                              capture_output=True).returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _open_target(target: str) -> None:
    if SYSTEM == "Windows":
        os.startfile(target)  # noqa: S606 — exe/URL-i ayrıca prosesdə açır
    elif SYSTEM == "Darwin":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def launch_entry(entry) -> str:
    """Bir elementi açır, nə etdiyini təsvir edən sətir qaytarır.

    entry ola bilər:
      - sətir: shell əmri (məs. "code")
      - {name, paths: [...], fallback: url}: ilk tapılan exe açılır,
        heç biri yoxdursa fallback (məs. sayt) brauzerdə açılır.
    """
    if isinstance(entry, str):
        subprocess.Popen(entry, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"əmr: {entry}"
    name = entry.get("name", "?")
    exe = find_app(entry)
    if exe:
        if entry.get("skip_if_running", True) and is_running(exe):
            return f"{name}: artıq açıqdır"
        _open_target(exe)
        return f"{name}: {exe}"
    if entry.get("fallback"):
        webbrowser.open(entry["fallback"])
        return f"{name}: tapılmadı → {entry['fallback']}"
    return f"{name}: TAPILMADI (config.yaml-da yolu düzəlt)"


def launch_workspace(cfg: dict) -> None:
    """config.yaml -> on_arrival: {windows|macos|linux: [...], urls: [...]}"""
    for entry in cfg.get(OS_KEY) or []:
        try:
            print(f"[launch] {launch_entry(entry)}")
        except Exception as e:  # noqa: BLE001
            print(f"[launch] alınmadı ({entry}): {e}")
    for url in cfg.get("urls") or []:
        print(f"[launch] {url}")
        webbrowser.open(url)


def check_apps(cfg: dict) -> None:
    """--check-apps: heç nə açmadan nəyin tapıldığını göstərir."""
    for entry in cfg.get(OS_KEY) or []:
        if isinstance(entry, str):
            print(f"  •  əmr: {entry}")
            continue
        exe = find_app(entry)
        if exe:
            state = "  (indi açıqdır)" if is_running(exe) else ""
            print(f"  ✅ {entry.get('name')}: {exe}{state}")
        elif entry.get("fallback"):
            print(f"  🌐 {entry.get('name')}: exe tapılmadı, əvəzinə {entry['fallback']} açılacaq")
        else:
            print(f"  ❌ {entry.get('name')}: tapılmadı. Yoxlanan yollar:")
            for p in entry.get("paths") or []:
                print(f"       {_expand(p)}")


# ---------------------------------------------------------------- Telegram
class Telegram:
    def __init__(self, token: str | None, chat_id: str | None):
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = str(chat_id or os.getenv("TELEGRAM_CHAT_ID") or "") or None

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def _url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"

    def send_photo(self, jpg: bytes, caption: str, block: bool = False) -> None:
        if not self.enabled:
            print("[telegram] token/chat_id yoxdur — göndərilmədi")
            return

        def _go():
            try:
                r = requests.post(self._url("sendPhoto"),
                                  data={"chat_id": self.chat_id, "caption": caption},
                                  files={"photo": ("intruder.jpg", jpg, "image/jpeg")},
                                  timeout=20)
                if not r.ok:
                    print(f"[telegram] {r.status_code}: {r.text[:200]}")
            except requests.RequestException as e:
                print(f"[telegram] şəbəkə xətası: {e}")

        if block:
            _go()
        else:
            threading.Thread(target=_go, daemon=True).start()

    def send_text(self, text: str) -> bool:
        if not self.enabled:
            return False
        try:
            r = requests.post(self._url("sendMessage"),
                              data={"chat_id": self.chat_id, "text": text}, timeout=20)
            return r.ok
        except requests.RequestException:
            return False

    def find_chat_ids(self) -> list[tuple[str, str]]:
        """Bota yazılmış son mesajlardan chat_id-ləri tapır."""
        r = requests.get(self._url("getUpdates"), timeout=20)
        r.raise_for_status()
        seen = {}
        for upd in r.json().get("result", []):
            chat = (upd.get("message") or upd.get("my_chat_member") or {}).get("chat")
            if chat:
                seen[str(chat["id"])] = chat.get("username") or chat.get("first_name") or chat.get("title", "")
        return list(seen.items())
