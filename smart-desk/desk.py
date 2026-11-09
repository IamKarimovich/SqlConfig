"""Smart Desk — üz tanıma ilə ağıllı iş masası.

  python desk.py                 # arxa fonda işləyir
  python desk.py --preview       # kamera pəncərəsi ilə (demo üçün əla)
  python desk.py --report        # bugünkü masa vaxtı hesabatı
  python desk.py --telegram-setup  # chat_id-ni tap + test mesajı göndər
  python desk.py --check-apps      # Opera/Claude və s. tapılırmı?
  python autostart.py install      # kompüter açılanda avtomatik başlasın
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import yaml

from actions import Telegram, check_apps, launch_workspace, lock_screen
from events import EventLog
from face_engine import BASE_DIR, Face, FaceDB, FaceEngine, open_camera

SNAP_DIR = BASE_DIR / "snapshots"


# ====================================================================== beyin
@dataclass
class DeskBrain:
    """Kameradan asılı olmayan vəziyyət maşını — hər kadrda nə baş verdiyini qərarlaşdırır.

    Vəziyyətlər: ABSENT (yoxsan) <-> PRESENT (masadasan).
    Qaytarılan əmrlər: "arrived", "launch", "left", "lock", "stranger".
    """
    owner: str
    arrive_frames: int = 3
    lock_after: float = 12.0
    relaunch_after: float = 30 * 60
    stranger_frames: int = 4
    stranger_cooldown: float = 60.0
    alert_when_owner_present: bool = False

    present: bool = False
    owner_streak: int = 0
    stranger_streak: int = 0
    last_seen: float | None = None
    left_at: float | None = None
    last_alert: float = field(default=-1e9)

    def step(self, now: float, names: list[str | None]) -> list[str]:
        """names: kadrdakı hər üz üçün tanınan ad, yad üçün None."""
        cmds: list[str] = []
        owner_here = self.owner in names
        stranger_here = None in names

        # --- sahib
        if owner_here:
            self.owner_streak += 1
            self.last_seen = now
        else:
            self.owner_streak = 0

        if not self.present and self.owner_streak >= self.arrive_frames:
            self.present = True
            cmds.append("arrived")
            if self.left_at is None or now - self.left_at >= self.relaunch_after:
                cmds.append("launch")
        elif self.present and self.last_seen is not None and now - self.last_seen > self.lock_after:
            self.present = False
            self.left_at = now
            cmds += ["left", "lock"]

        # --- yad şəxs
        self.stranger_streak = self.stranger_streak + 1 if stranger_here else 0
        if (self.stranger_streak >= self.stranger_frames
                and now - self.last_alert >= self.stranger_cooldown
                and (not self.present or self.alert_when_owner_present)):
            self.last_alert = now
            cmds.append("stranger")
        return cmds


# ====================================================================== çəkiliş
COLORS = {"owner": (80, 220, 80), "trusted": (230, 170, 40), "stranger": (60, 60, 240)}


def draw(frame, faces: list[Face], owner: str, brain: DeskBrain, fps: float):
    for f in faces:
        x, y, w, h = f.box
        kind = "stranger" if f.name is None else ("owner" if f.name == owner else "trusted")
        c = COLORS[kind]
        label = f"{f.name or 'YAD'}  {f.similarity:.2f}"
        cv2.rectangle(frame, (x, y), (x + w, y + h), c, 2)
        # künc "hədəf" xətləri — cool görünüş
        L = max(12, w // 5)
        for (px, py, dx, dy) in ((x, y, 1, 1), (x + w, y, -1, 1), (x, y + h, 1, -1), (x + w, y + h, -1, -1)):
            cv2.line(frame, (px, py), (px + dx * L, py), c, 4)
            cv2.line(frame, (px, py), (px, py + dy * L), c, 4)
        cv2.rectangle(frame, (x, y - 26), (x + 9 * len(label) + 10, y), c, -1)
        cv2.putText(frame, label, (x + 5, y - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA)

    status = "MASADASAN" if brain.present else "YOXSAN"
    if brain.present and brain.last_seen is not None:
        gone = time.monotonic() - brain.last_seen
        if gone > 1:
            status += f"  | kilid: {max(0, brain.lock_after - gone):.0f}s"
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (frame.shape[1], 36), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
    cv2.putText(frame, f"SMART DESK  |  {status}  |  {fps:.1f} fps", (10, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)


# ====================================================================== əsas dövr
def load_config(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"{path.name} yoxdur. Əvvəlcə: cp config.example.yaml config.yaml")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def run(cfg: dict, preview: bool):
    owner = cfg["owner"]
    rec, pres, intr = cfg.get("recognition", {}), cfg.get("presence", {}), cfg.get("intruder", {})
    tg_cfg = cfg.get("telegram", {}) or {}

    db = FaceDB(threshold=rec.get("threshold", 0.40))
    if owner not in db.people:
        raise SystemExit(f"'{owner}' tanınmır. Əvvəlcə: python enroll.py --name {owner}")
    engine = FaceEngine()
    tg = Telegram(tg_cfg.get("bot_token"), tg_cfg.get("chat_id"))
    log = EventLog()
    brain = DeskBrain(
        owner=owner,
        arrive_frames=pres.get("arrive_frames", 3),
        lock_after=pres.get("lock_after_seconds", 12),
        relaunch_after=pres.get("relaunch_after_minutes", 30) * 60,
        stranger_frames=intr.get("confirm_frames", 4),
        stranger_cooldown=intr.get("cooldown_seconds", 60),
        alert_when_owner_present=intr.get("alert_when_owner_present", False),
    )
    min_px = rec.get("min_face_px", 70)
    period = 1.0 / max(1, cfg.get("fps", 5))

    print(f"👀 Smart Desk işləyir. Tanınan şəxslər: {', '.join(db.people)}  |  sahib: {owner}")
    print(f"   Telegram: {'aktiv' if tg.enabled else 'söndürülüb'}   (Ctrl+C / q = çıxış)")
    log.log("start")
    cap = open_camera(cfg.get("camera", 0), wait_seconds=cfg.get("camera_wait_seconds", 120))
    fps, t_prev = 0.0, time.monotonic()
    try:
        while True:
            t0 = time.monotonic()
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.5)
                continue
            frame = cv2.flip(frame, 1)

            faces = [f for f in engine.detect(frame) if min(f.box[2], f.box[3]) >= min_px]
            for f in faces:
                f.name, f.similarity = db.identify(engine.embed(frame, f))

            for cmd in brain.step(t0, [f.name for f in faces]):
                if cmd == "arrived":
                    log.log("arrived", owner)
                elif cmd == "launch":
                    log.log("launched")
                    launch_workspace(cfg.get("on_arrival", {}) or {})
                elif cmd == "left":
                    log.log("left", owner)
                elif cmd == "lock":
                    lock_screen()
                    log.log("locked", "sahib getdi")
                    if tg_cfg.get("notify_on_lock"):
                        tg.send_text(f"🔒 Ekran kilidləndi ({datetime.now():%H:%M})")
                elif cmd == "stranger":
                    handle_stranger(frame, faces, intr, brain, tg, log)

            if preview:
                now = time.monotonic()
                fps = 0.9 * fps + 0.1 * (1.0 / max(1e-3, now - t_prev))
                t_prev = now
                view = frame.copy()
                draw(view, faces, owner, brain, fps)
                cv2.imshow("Smart Desk", view)
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    break
            time.sleep(max(0.0, period - (time.monotonic() - t0)))
    except KeyboardInterrupt:
        pass
    finally:
        log.log("stop")
        cap.release()
        if preview:
            cv2.destroyAllWindows()


def handle_stranger(frame, faces, intr, brain, tg, log):
    shot = frame.copy()
    for f in faces:
        if f.name is None:
            x, y, w, h = f.box
            cv2.rectangle(shot, (x, y), (x + w, y + h), COLORS["stranger"], 3)
    stamp = datetime.now()
    cv2.putText(shot, stamp.strftime("%d.%m.%Y %H:%M:%S"), (10, shot.shape[0] - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
    jpg = cv2.imencode(".jpg", shot, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()

    if intr.get("save_snapshots", True):
        SNAP_DIR.mkdir(exist_ok=True)
        (SNAP_DIR / f"intruder_{stamp:%Y%m%d_%H%M%S}.jpg").write_bytes(jpg)
    if intr.get("lock_screen", True) and not brain.present:
        lock_screen()
    where = "arxanda kimsə var 👀" if brain.present else "masana kimsə oturub 🚨"
    tg.send_photo(jpg, f"Smart Desk: {where}\n{stamp:%d.%m.%Y %H:%M:%S}")
    log.log("stranger", f"{sum(f.name is None for f in faces)} yad üz")


def telegram_setup(cfg: dict):
    t = cfg.get("telegram", {}) or {}
    tg = Telegram(t.get("bot_token"), t.get("chat_id"))
    if not tg.token:
        raise SystemExit("Bot token yoxdur: config.yaml -> telegram.bot_token və ya TELEGRAM_BOT_TOKEN")
    if not tg.chat_id:
        chats = tg.find_chat_ids()
        if not chats:
            raise SystemExit("Heç bir mesaj tapılmadı. Telegram-da botuna /start yaz və yenidən işə sal.")
        print("Tapılan chat-lar (birini config.yaml -> telegram.chat_id-yə yaz):")
        for cid, name in chats:
            print(f"  {cid}   {name}")
        return
    print("✅ Test mesajı göndərildi" if tg.send_text("👋 Smart Desk qoşuldu!") else "❌ Göndərilmədi")


def main():
    ap = argparse.ArgumentParser(description="Smart Desk — üz tanıma ilə ağıllı iş masası")
    ap.add_argument("--config", type=Path, default=BASE_DIR / "config.yaml")
    ap.add_argument("--preview", action="store_true", help="kamera pəncərəsini göstər")
    ap.add_argument("--report", action="store_true", help="bugünkü hesabat")
    ap.add_argument("--telegram-setup", action="store_true")
    ap.add_argument("--check-apps", action="store_true", help="açılacaq proqramlar tapılırmı?")
    args = ap.parse_args()

    # pythonw.exe (autostart) ilə işləyəndə konsol yoxdur → hər şeyi desk.log-a yaz
    if sys.stdout is None or sys.stderr is None:
        logf = open(BASE_DIR / "desk.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
        sys.stdout = sys.stderr = logf

    if args.report:
        print(EventLog().report())
        return
    cfg = load_config(args.config)
    if args.check_apps:
        check_apps(cfg.get("on_arrival", {}) or {})
    elif args.telegram_setup:
        telegram_setup(cfg)
    else:
        run(cfg, args.preview)


if __name__ == "__main__":
    main()
