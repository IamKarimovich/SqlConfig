"""Smart Desk-i kompüter açılanda avtomatik başlat.

  python autostart.py install     # Startup-a əlavə et (gözləmədən dərhal başlayır)
  python autostart.py install --delay 10   # login-dən 10 saniyə sonra başlasın
  python autostart.py uninstall   # sil
  python autostart.py status      # yoxla

Vacib: virtual mühit aktiv olanda işlət (.venv\\Scripts\\activate),
çünki başladıcı məhz həmin Python-u istifadə edəcək.
"""
from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DESK = BASE_DIR / "desk.py"


def windows_paths() -> tuple[Path, Path]:
    startup = Path(os.environ["APPDATA"]) / r"Microsoft\Windows\Start Menu\Programs\Startup"
    return startup, startup / "SmartDesk.vbs"


def pythonw() -> Path:
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return w if w.exists() else exe


def install_windows(delay: int = 0) -> None:
    startup, vbs = windows_paths()
    py = pythonw()
    if ".venv" not in str(py).lower() and "venv" not in str(py).lower():
        print("⚠️  Virtual mühit aktiv görünmür. Davam edirəm, amma əvvəlcə "
              "'.venv\\Scripts\\activate' etmək tövsiyə olunur.")
    if not (BASE_DIR / "config.yaml").exists():
        raise SystemExit("config.yaml yoxdur — əvvəlcə: copy config.example.yaml config.yaml")
    if not any((BASE_DIR / "faces").glob("*.npy")):
        raise SystemExit("Üz tanıdılmayıb — əvvəlcə: python enroll.py --name <adın>")

    # VBScript: konsol pəncərəsi açmadan (0 = gizli) pythonw ilə desk.py-ı işə salır.
    # Gözləmə default olaraq yoxdur: desk.py kamera hazır olana qədər özü gözləyir
    # (config.yaml -> camera_wait_seconds). --delay yalnız lazım olsa.
    q = lambda p: '"""' + str(p) + '"""'  # noqa: E731 — VBS içində dırnaq
    content = (
        'Set sh = CreateObject("WScript.Shell")\r\n'
        + (f"WScript.Sleep {delay * 1000}\r\n" if delay > 0 else "")
        + f'sh.CurrentDirectory = "{BASE_DIR}"\r\n'
        + f"sh.Run {q(py)} & \" \" & {q(DESK)}, 0, False\r\n"
    )
    startup.mkdir(parents=True, exist_ok=True)
    vbs.write_text(content, encoding="mbcs")  # WSH ANSI kodlaşdırma gözləyir
    print(f"✅ Quraşdırıldı: {vbs}")
    print(f"   Python: {py}")
    print("   Növbəti dəfə kompüter açılanda Smart Desk özü başlayacaq (pəncərəsiz).")
    print(f"   Loglar: {BASE_DIR / 'desk.log'}")
    print(f"   Gözləmə: {delay} saniyə" + (" (login-dən dərhal sonra başlayır)" if delay == 0 else ""))
    print("   İndi sınamaq üçün həmin .vbs faylına iki dəfə kliklə.")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if platform.system() != "Windows":
        raise SystemExit("Bu skript Windows üçündür. macOS/Linux üçün README-dəki "
                         "'Kompüter açılanda avtomatik başlasın' bölməsinə bax.")
    _, vbs = windows_paths()
    if cmd == "install":
        delay = 0
        if "--delay" in sys.argv:
            try:
                delay = max(0, int(sys.argv[sys.argv.index("--delay") + 1]))
            except (IndexError, ValueError):
                raise SystemExit("İstifadə: python autostart.py install --delay <saniyə>") from None
        install_windows(delay)
    elif cmd == "uninstall":
        if vbs.exists():
            vbs.unlink()
            print("🗑️  Silindi. Hal-hazırda işləyən Smart Desk-i dayandırmaq üçün: "
                  "Task Manager → pythonw.exe → End task")
        else:
            print("Onsuz da quraşdırılmayıb.")
    elif cmd == "status":
        print(f"{'✅ Quraşdırılıb' if vbs.exists() else '❌ Quraşdırılmayıb'}: {vbs}")
    else:
        raise SystemExit("İstifadə: python autostart.py install | uninstall | status")


if __name__ == "__main__":
    main()
