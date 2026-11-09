"""Smart Desk-i kompüter açılanda avtomatik başlat.

  python autostart.py install     # Startup-a əlavə et
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


def install_windows() -> None:
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
    # 20 saniyə gözləmə: login-dən sonra Windows kameranı və şəbəkəni hazırlasın.
    q = lambda p: '"""' + str(p) + '"""'  # noqa: E731 — VBS içində dırnaq
    content = (
        'Set sh = CreateObject("WScript.Shell")\r\n'
        "WScript.Sleep 20000\r\n"
        f'sh.CurrentDirectory = "{BASE_DIR}"\r\n'
        f"sh.Run {q(py)} & \" \" & {q(DESK)}, 0, False\r\n"
    )
    startup.mkdir(parents=True, exist_ok=True)
    vbs.write_text(content, encoding="mbcs")  # WSH ANSI kodlaşdırma gözləyir
    print(f"✅ Quraşdırıldı: {vbs}")
    print(f"   Python: {py}")
    print("   Növbəti dəfə kompüter açılanda Smart Desk özü başlayacaq (pəncərəsiz).")
    print(f"   Loglar: {BASE_DIR / 'desk.log'}")
    print("   İndi sınamaq üçün həmin .vbs faylına iki dəfə kliklə və 20 saniyə gözlə.")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if platform.system() != "Windows":
        raise SystemExit("Bu skript Windows üçündür. macOS/Linux üçün README-dəki "
                         "'Kompüter açılanda avtomatik başlasın' bölməsinə bax.")
    _, vbs = windows_paths()
    if cmd == "install":
        install_windows()
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
