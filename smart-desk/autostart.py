"""Smart Desk-i kompüter açılanda avtomatik başlat + masaüstü qısayolu.

  python autostart.py install     # Startup-a əlavə et (gözləmədən dərhal başlayır)
  python autostart.py install --delay 10   # login-dən 10 saniyə sonra başlasın
  python autostart.py uninstall   # sil
  python autostart.py status      # yoxla
  python autostart.py shortcut    # masaüstünə və Start menyusuna "Smart Desk" qısayolu

Vacib: virtual mühit aktiv olanda işlət (.venv\\Scripts\\activate),
çünki başladıcı məhz həmin Python-u istifadə edəcək.
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DESK = BASE_DIR / "desk.py"
APP = BASE_DIR / "app.py"
ICON = BASE_DIR / "smart_desk.ico"
IS_WIN = platform.system() == "Windows"


def windows_paths() -> tuple[Path, Path]:
    startup = Path(os.environ["APPDATA"]) / r"Microsoft\Windows\Start Menu\Programs\Startup"
    return startup, startup / "SmartDesk.vbs"


def pythonw() -> Path:
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return w if w.exists() else exe


def is_installed() -> bool:
    return IS_WIN and windows_paths()[1].exists()


def install(delay: int = 0) -> str:
    """Startup-a gizli başladıcı qoyur. Xəta olsa RuntimeError."""
    if not IS_WIN:
        raise RuntimeError("Avtomatik başlatma hələlik yalnız Windows üçündür (README-yə bax).")
    if not (BASE_DIR / "config.yaml").exists():
        raise RuntimeError("config.yaml yoxdur — əvvəlcə ayarları saxla.")
    if not any((BASE_DIR / "faces").glob("*.npy")):
        raise RuntimeError("Heç kim tanıdılmayıb — əvvəlcə üzünü tanıt.")
    startup, vbs = windows_paths()
    py = pythonw()
    # VBScript: konsol pəncərəsi açmadan (0 = gizli) pythonw ilə desk.py-ı işə salır.
    # Gözləmə default olaraq yoxdur: desk.py kamera hazır olana qədər özü gözləyir.
    q = lambda p: '"""' + str(p) + '"""'  # noqa: E731 — VBS içində dırnaq
    content = (
        'Set sh = CreateObject("WScript.Shell")\r\n'
        + (f"WScript.Sleep {delay * 1000}\r\n" if delay > 0 else "")
        + f'sh.CurrentDirectory = "{BASE_DIR}"\r\n'
        + f"sh.Run {q(py)} & \" \" & {q(DESK)}, 0, False\r\n"
    )
    startup.mkdir(parents=True, exist_ok=True)
    vbs.write_text(content, encoding="mbcs")  # WSH ANSI kodlaşdırma gözləyir
    msg = f"✅ Quraşdırıldı: {vbs}\n   Python: {py}\n   Gözləmə: {delay} saniyə"
    if "venv" not in str(py).lower():
        msg += "\n⚠️  Virtual mühit aktiv görünmür — .venv\\Scripts\\activate etmək tövsiyə olunur."
    return msg


def uninstall() -> str:
    if not IS_WIN:
        raise RuntimeError("Yalnız Windows")
    vbs = windows_paths()[1]
    if vbs.exists():
        vbs.unlink()
        return "🗑️  Avtomatik başlatma söndürüldü."
    return "Onsuz da quraşdırılmayıb."


# ---------------------------------------------------------------- ikon + qısayol
def make_icon() -> Path:
    """Kiçik "göz + kamera çərçivəsi" ikonu çəkir (.ico, daxilində PNG)."""
    if ICON.exists():
        return ICON
    import struct

    import cv2
    import numpy as np

    n = 256
    img = np.zeros((n, n, 4), np.uint8)
    cv2.circle(img, (n // 2, n // 2), 120, (60, 45, 30, 255), -1, cv2.LINE_AA)          # fon
    green = (90, 220, 90, 255)
    L, m, t = 52, 52, 14
    for (x, y, dx, dy) in ((m, m, 1, 1), (n - m, m, -1, 1), (m, n - m, 1, -1), (n - m, n - m, -1, -1)):
        cv2.line(img, (x, y), (x + dx * L, y), green, t, cv2.LINE_AA)
        cv2.line(img, (x, y), (x, y + dy * L), green, t, cv2.LINE_AA)
    cv2.ellipse(img, (n // 2, n // 2), (62, 36), 0, 0, 360, (255, 255, 255, 255), -1, cv2.LINE_AA)  # göz
    cv2.circle(img, (n // 2, n // 2), 26, (240, 170, 40, 255), -1, cv2.LINE_AA)
    cv2.circle(img, (n // 2, n // 2), 11, (20, 20, 20, 255), -1, cv2.LINE_AA)
    png = cv2.imencode(".png", img)[1].tobytes()
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 6 + 16)
    ICON.write_bytes(header + entry + png)
    cv2.imwrite(str(ICON.with_suffix(".png")), img)  # tkinter pəncərə ikonu üçün
    return ICON


def create_shortcut() -> str:
    """Masaüstünə və Start menyusuna "Smart Desk" (ayarlar tətbiqi) qısayolu."""
    if not IS_WIN:
        raise RuntimeError("Qısayol yalnız Windows-da yaradılır. Başqa sistemdə: python app.py")
    icon = make_icon()
    esc = lambda s: str(s).replace("'", "''")  # noqa: E731 — PowerShell dırnağı
    ps = f"""
$ws = New-Object -ComObject WScript.Shell
$targets = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))
foreach ($dir in $targets) {{
  $lnk = $ws.CreateShortcut((Join-Path $dir 'Smart Desk.lnk'))
  $lnk.TargetPath = '{esc(pythonw())}'
  $lnk.Arguments = '"{esc(APP)}"'
  $lnk.WorkingDirectory = '{esc(BASE_DIR)}'
  $lnk.IconLocation = '{esc(icon)}'
  $lnk.Description = 'Smart Desk ayarları'
  $lnk.Save()
}}
"""
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                       capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        raise RuntimeError(f"Qısayol yaradılmadı: {r.stderr.strip()[:300]}")
    return "✅ 'Smart Desk' qısayolu masaüstünə və Start menyusuna əlavə olundu."


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    try:
        if cmd == "install":
            delay = 0
            if "--delay" in sys.argv:
                try:
                    delay = max(0, int(sys.argv[sys.argv.index("--delay") + 1]))
                except (IndexError, ValueError):
                    raise SystemExit("İstifadə: python autostart.py install --delay <saniyə>") from None
            print(install(delay))
        elif cmd == "uninstall":
            print(uninstall())
        elif cmd == "shortcut":
            print(create_shortcut())
        elif cmd == "status":
            if not IS_WIN:
                raise RuntimeError("Yalnız Windows")
            vbs = windows_paths()[1]
            print(f"{'✅ Quraşdırılıb' if vbs.exists() else '❌ Quraşdırılmayıb'}: {vbs}")
        else:
            raise SystemExit("İstifadə: python autostart.py install | uninstall | status | shortcut")
    except RuntimeError as e:
        raise SystemExit(str(e)) from None


if __name__ == "__main__":
    main()
