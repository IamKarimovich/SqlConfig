"""Smart Desk — ayarlar tətbiqi (pəncərəli).

  python app.py
  (və ya masaüstündəki "Smart Desk" qısayolu: python autostart.py shortcut)

Bütün dəyişikliklər avtomatik config.yaml-a yazılır və arxa fonda işləyən
Smart Desk onları 2-3 saniyəyə, yenidən başlatmadan tətbiq edir.
"""
from __future__ import annotations

import io
import os
import platform
import queue
import re
import shutil
import subprocess
import threading
import tkinter as tk
from contextlib import redirect_stdout
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import numpy as np
import yaml

import actions
import autostart
import service

BASE_DIR = Path(__file__).resolve().parent
CONFIG = BASE_DIR / "config.yaml"
EXAMPLE = BASE_DIR / "config.example.yaml"
FACES_DIR = BASE_DIR / "faces"
SNAP_DIR = BASE_DIR / "snapshots"
IS_WIN = platform.system() == "Windows"

GREEN, RED, GREY = "#1e9e4a", "#c0392b", "#7f8c8d"


# ====================================================================== config
def load_cfg() -> dict:
    if not CONFIG.exists():
        shutil.copy(EXAMPLE, CONFIG)
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    raw = cfg.get("owners", cfg.get("owner")) or []
    cfg.pop("owners", None)
    cfg["owner"] = [raw] if isinstance(raw, str) else list(raw)
    for key in ("presence", "intruder", "recognition", "telegram", "on_arrival"):
        cfg[key] = cfg.get(key) or {}
    return cfg


def save_cfg(cfg: dict) -> None:
    # Əvvəlcə müvəqqəti fayla, sonra əvəz et — işləyən proses yarımçıq fayl oxumasın
    tmp = CONFIG.with_suffix(".tmp")
    header = "# Smart Desk ayarları — 'python app.py' tətbiqi ilə idarə olunur.\n" \
             "# Bütün seçimlərin izahı: config.example.yaml\n"
    tmp.write_text(header + yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    os.replace(tmp, CONFIG)


def people() -> list[tuple[str, int]]:
    out = []
    for p in sorted(FACES_DIR.glob("*.npy")):
        try:
            out.append((p.stem, int(np.load(p).shape[0])))
        except Exception:  # noqa: BLE001
            out.append((p.stem, 0))
    return out


def open_path(path: Path) -> None:
    path.mkdir(exist_ok=True) if not path.suffix else None
    if IS_WIN:
        os.startfile(path)  # noqa: S606
    else:
        subprocess.Popen(["open" if platform.system() == "Darwin" else "xdg-open", str(path)])


# ====================================================================== tətbiq
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Smart Desk")
        self.geometry("800x700")
        self.minsize(740, 660)
        self._set_icon()
        style = ttk.Style(self)
        if "vista" not in style.theme_names():
            style.theme_use("clam")
        style.configure("Status.TLabel", font=("Segoe UI", 12, "bold"))
        style.configure("Hint.TLabel", foreground=GREY)

        self.cfg = load_cfg()
        self._ui_queue: queue.Queue = queue.Queue()  # thread-lərdən UI-ya nəticələr
        self._save_job = None
        self._loading = True

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=(10, 4))
        self.tab_general = ttk.Frame(nb, padding=12)
        self.tab_people = ttk.Frame(nb, padding=12)
        self.tab_apps = ttk.Frame(nb, padding=12)
        self.tab_tg = ttk.Frame(nb, padding=12)
        self.tab_log = ttk.Frame(nb, padding=12)
        nb.add(self.tab_general, text="  Ümumi  ")
        nb.add(self.tab_people, text="  Şəxslər  ")
        nb.add(self.tab_apps, text="  Proqramlar  ")
        nb.add(self.tab_tg, text="  Telegram  ")
        nb.add(self.tab_log, text="  Jurnal  ")
        nb.bind("<<NotebookTabChanged>>", lambda e: nb.index("current") == 4 and self.refresh_log())

        bar = ttk.Frame(self, padding=(12, 2, 12, 8))
        bar.pack(fill="x")
        self.lbl_bar_status = ttk.Label(bar, text="")
        self.lbl_bar_status.pack(side="left")
        self.lbl_saved = ttk.Label(bar, text="", style="Hint.TLabel")
        self.lbl_saved.pack(side="right")

        self.build_general()
        self.build_people()
        self.build_apps()
        self.build_telegram()
        self.build_log()
        self._loading = False
        self._drain_queue()
        self.poll_service()

    def _drain_queue(self):
        """Tkinter yalnız əsas thread-dən idarə olunmalıdır — nəticələri buradan icra edirik."""
        try:
            while True:
                self._ui_queue.get_nowait()()
        except queue.Empty:
            pass
        self.after(100, self._drain_queue)

    def _set_icon(self):
        try:
            png = autostart.make_icon().with_suffix(".png")
            self._icon = tk.PhotoImage(file=str(png))
            self.iconphoto(True, self._icon)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------ köməkçilər
    def bg(self, fn, done=None, busy: str | None = None):
        """fn-i ayrı thread-də işlət, nəticəni done(result, error) ilə UI-ya qaytar."""
        if busy:
            self.lbl_saved.config(text=f"⏳ {busy}")
            self.config(cursor="watch")

        def worker():
            try:
                res, err = fn(), None
            except Exception as e:  # noqa: BLE001
                res, err = None, e

            def finish():
                if busy:
                    self.lbl_saved.config(text="")
                    self.config(cursor="")
                if done:
                    done(res, err)
                elif err:
                    messagebox.showerror("Smart Desk", str(err))
            self._ui_queue.put(finish)
        threading.Thread(target=worker, daemon=True).start()

    def schedule_save(self, *_):
        if self._loading:
            return
        if self._save_job:
            self.after_cancel(self._save_job)
        self.lbl_saved.config(text="… dəyişiklik")
        self._save_job = self.after(700, self.save_now)

    def save_now(self):
        self._save_job = None
        self.collect_general()
        self.collect_telegram()
        try:
            save_cfg(self.cfg)
            note = " — işləyən Smart Desk 2-3 san. ərzində tətbiq edəcək" if service.running_pid() else ""
            self.lbl_saved.config(text=f"✓ Saxlanıldı{note}")
        except OSError as e:
            messagebox.showerror("Saxlanmadı", str(e))

    def show_text(self, title: str, text: str, action: tuple[str, callable] | None = None):
        win = tk.Toplevel(self)
        win.title(title)
        win.geometry("640x420")
        win.transient(self)
        txt = tk.Text(win, wrap="word", font=("Consolas", 10), padx=8, pady=8)
        txt.insert("1.0", text.strip() or "(boş)")
        txt.config(state="disabled")
        txt.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        btns = ttk.Frame(win, padding=8)
        btns.pack(fill="x")
        if action:
            ttk.Button(btns, text=action[0], command=lambda: (win.destroy(), action[1]())).pack(side="left")
        ttk.Button(btns, text="Bağla", command=win.destroy).pack(side="right")

    # ============================================================ ÜMUMİ
    def build_general(self):
        t = self.tab_general
        pres, intr, rec = self.cfg["presence"], self.cfg["intruder"], self.cfg["recognition"]

        # --- xidmət
        f = ttk.LabelFrame(t, text=" Smart Desk ", padding=10)
        f.pack(fill="x")
        self.lbl_status = ttk.Label(f, text="…", style="Status.TLabel")
        self.lbl_status.pack(side="left")
        ttk.Button(f, text="🎥 Kamera testi", command=self.preview).pack(side="right", padx=(6, 0))
        ttk.Button(f, text="■ Dayandır", command=self.stop_service).pack(side="right", padx=(6, 0))
        ttk.Button(f, text="▶ Başlat", command=self.start_service).pack(side="right")

        # --- kilid
        f = ttk.LabelFrame(t, text=" Ekran kilidi ", padding=10)
        f.pack(fill="x", pady=(10, 0))
        self.v_lock_on = tk.BooleanVar(value=pres.get("lock_enabled", True))
        ttk.Checkbutton(f, text="Məni görməyəndə ekranı kilidlə", variable=self.v_lock_on,
                        command=self.schedule_save).grid(row=0, column=0, columnspan=8, sticky="w")
        secs = int(float(pres.get("lock_after_seconds", 300)))
        self.v_lock_min = tk.StringVar(value=str(secs // 60))
        self.v_lock_sec = tk.StringVar(value=str(secs % 60))
        ttk.Label(f, text="Nə qədər sonra:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Spinbox(f, from_=0, to=240, width=5, textvariable=self.v_lock_min,
                    command=self.schedule_save).grid(row=1, column=1, padx=(8, 2), pady=(8, 0))
        ttk.Label(f, text="dəq").grid(row=1, column=2, sticky="w", pady=(8, 0))
        ttk.Spinbox(f, from_=0, to=59, width=4, textvariable=self.v_lock_sec,
                    command=self.schedule_save).grid(row=1, column=3, padx=(8, 2), pady=(8, 0))
        ttk.Label(f, text="san").grid(row=1, column=4, sticky="w", pady=(8, 0))
        presets = ttk.Frame(f)
        presets.grid(row=1, column=5, columnspan=3, sticky="w", padx=(18, 0), pady=(8, 0))
        for label, s in (("30 san", 30), ("1 dəq", 60), ("5 dəq", 300), ("15 dəq", 900)):
            ttk.Button(presets, text=label, width=6,
                       command=lambda s=s: self.set_lock(s)).pack(side="left", padx=2)
        for v in (self.v_lock_min, self.v_lock_sec):
            v.trace_add("write", self.schedule_save)

        self.v_relaunch = tk.StringVar(value=str(pres.get("relaunch_after_minutes", 30)))
        r2 = ttk.Frame(f)
        r2.grid(row=2, column=0, columnspan=8, sticky="w", pady=(10, 0))
        ttk.Label(r2, text="Proqramları yenidən aç, əgər bundan uzun yox idinsə:").pack(side="left")
        ttk.Spinbox(r2, from_=0, to=1440, width=5, textvariable=self.v_relaunch,
                    command=self.schedule_save).pack(side="left", padx=(8, 2))
        ttk.Label(r2, text="dəq").pack(side="left")
        self.v_relaunch.trace_add("write", self.schedule_save)

        # --- yad şəxs
        f = ttk.LabelFrame(t, text=" Yad şəxs masaya oturanda ", padding=10)
        f.pack(fill="x", pady=(10, 0))
        self.v_intr_lock = tk.BooleanVar(value=intr.get("lock_screen", True))
        self.v_intr_surfer = tk.BooleanVar(value=intr.get("alert_when_owner_present", False))
        self.v_intr_snap = tk.BooleanVar(value=intr.get("save_snapshots", True))
        ttk.Checkbutton(f, text="Ekranı dərhal kilidlə", variable=self.v_intr_lock,
                        command=self.schedule_save).pack(anchor="w")
        ttk.Checkbutton(f, text="Mən masadayamsa da xəbər ver (arxamdan baxan olsa)",
                        variable=self.v_intr_surfer, command=self.schedule_save).pack(anchor="w")
        row = ttk.Frame(f)
        row.pack(fill="x")
        ttk.Checkbutton(row, text="Şəklini saxla", variable=self.v_intr_snap,
                        command=self.schedule_save).pack(side="left")
        ttk.Button(row, text="📁 Şəkillər", command=lambda: open_path(SNAP_DIR)).pack(side="right")

        # --- tanıma
        f = ttk.LabelFrame(t, text=" Tanıma dəqiqliyi ", padding=10)
        f.pack(fill="x", pady=(10, 0))
        self.v_thr = tk.DoubleVar(value=float(rec.get("threshold", 0.40)))
        self.lbl_thr = ttk.Label(f, width=34)
        ttk.Label(f, text="Yumşaq").pack(side="left")
        ttk.Scale(f, from_=0.30, to=0.60, variable=self.v_thr,
                  command=lambda *_: (self._thr_label(), self.schedule_save())).pack(
            side="left", fill="x", expand=True, padx=8)
        ttk.Label(f, text="Sərt").pack(side="left")
        self.lbl_thr.pack(side="left", padx=(12, 0))
        self._thr_label()

        # --- başlanğıc
        f = ttk.LabelFrame(t, text=" Başlanğıc ", padding=10)
        f.pack(fill="x", pady=(10, 0))
        self.v_autostart = tk.BooleanVar(value=autostart.is_installed())
        cb = ttk.Checkbutton(f, text="Kompüter açılanda avtomatik başlasın", variable=self.v_autostart,
                             command=self.toggle_autostart)
        cb.pack(side="left")
        if not IS_WIN:
            cb.state(["disabled"])
        ttk.Button(f, text="🖥 Masaüstünə qısayol", command=self.make_shortcut).pack(side="right")

    def _thr_label(self):
        v = self.v_thr.get()
        hint = "başqasını sənə oxşatmır" if v >= 0.47 else ("səni asan tanıyır" if v <= 0.36 else "balanslı")
        self.lbl_thr.config(text=f"{v:.2f}  ({hint})")

    def set_lock(self, secs: int):
        self.v_lock_on.set(True)
        self.v_lock_min.set(str(secs // 60))
        self.v_lock_sec.set(str(secs % 60))

    @staticmethod
    def _int(var: tk.StringVar, default: int) -> int:
        try:
            return max(0, int(float(var.get())))
        except ValueError:
            return default

    def collect_general(self):
        pres, intr = self.cfg["presence"], self.cfg["intruder"]
        pres["lock_enabled"] = bool(self.v_lock_on.get())
        pres["lock_after_seconds"] = max(5, self._int(self.v_lock_min, 5) * 60 + self._int(self.v_lock_sec, 0))
        pres["relaunch_after_minutes"] = self._int(self.v_relaunch, 30)
        intr["lock_screen"] = bool(self.v_intr_lock.get())
        intr["alert_when_owner_present"] = bool(self.v_intr_surfer.get())
        intr["save_snapshots"] = bool(self.v_intr_snap.get())
        self.cfg["recognition"]["threshold"] = round(float(self.v_thr.get()), 2)

    # --- xidmət
    def poll_service(self):
        def check():
            return service.running_pid()

        def show(pid, _err):
            if pid:
                self.lbl_status.config(text="● İşləyir", foreground=GREEN)
                self.lbl_bar_status.config(text=f"Smart Desk arxa fonda işləyir (PID {pid})")
            else:
                self.lbl_status.config(text="○ Dayanıb", foreground=RED)
                self.lbl_bar_status.config(text="Smart Desk işləmir")
            self.after(3000, self.poll_service)
        self.bg(check, show)

    def start_service(self):
        self.save_now()
        if not self.cfg["owner"]:
            messagebox.showwarning("Smart Desk", "Əvvəlcə 'Şəxslər' bölməsində ən azı bir sahib seç.")
            return
        self.bg(service.start, lambda started, err: messagebox.showerror("Başlamadı", str(err)) if err else
                self.lbl_saved.config(text="▶ Başladıldı" if started else "Artıq işləyir"), busy="Başladılır…")

    def stop_service(self):
        self.bg(service.stop, lambda stopped, err: self.lbl_saved.config(
            text="■ Dayandırıldı" if stopped else "Onsuz da işləmirdi"), busy="Dayandırılır…")

    def preview(self):
        self.save_now()
        messagebox.showinfo("Kamera testi", "Kamera pəncərəsi açılacaq.\n\n🟩 sahib, 🟦 etibarlı, 🟥 yad\n\n"
                            "Bağlamaq üçün pəncərədə 'q' bas.")
        self.bg(lambda: service.run_exclusive(["desk.py", "--preview"]), self._after_exclusive,
                busy="Kamera testi işləyir…")

    def _after_exclusive(self, res, err):
        if err:
            messagebox.showerror("Smart Desk", str(err))
            return
        code, out = res
        if code != 0:
            self.show_text("Xəta", out)

    def toggle_autostart(self):
        try:
            msg = autostart.install() if self.v_autostart.get() else autostart.uninstall()
            self.lbl_saved.config(text=msg.splitlines()[0])
        except Exception as e:  # noqa: BLE001
            self.v_autostart.set(autostart.is_installed())
            messagebox.showerror("Avtomatik başlatma", str(e))

    def make_shortcut(self):
        self.bg(autostart.create_shortcut, lambda msg, err: messagebox.showerror("Qısayol", str(err))
                if err else messagebox.showinfo("Qısayol", msg), busy="Qısayol yaradılır…")

    # ============================================================ ŞƏXSLƏR
    def build_people(self):
        t = self.tab_people
        ttk.Label(t, text="⭐ Sahib — oturanda proqramlar açılır, getdikdə kilidlənir.   "
                          "Etibarlı — xəbərdarlıq yoxdur, amma heç nə açılmır.",
                  style="Hint.TLabel", wraplength=700).pack(anchor="w", pady=(0, 8))
        body = ttk.Frame(t)
        body.pack(fill="both", expand=True)
        self.tv_people = ttk.Treeview(body, columns=("name", "samples", "role"), show="headings", height=10)
        for col, txt, w in (("name", "Ad", 220), ("samples", "Nümunə", 90), ("role", "Rol", 160)):
            self.tv_people.heading(col, text=txt)
            self.tv_people.column(col, width=w, anchor="w" if col != "samples" else "center")
        btns = ttk.Frame(body, padding=(10, 0, 0, 0))
        btns.pack(side="right", fill="y")
        self.tv_people.pack(side="left", fill="both", expand=True)
        self.tv_people.bind("<Double-1>", lambda e: self.toggle_owner())
        for txt, cmd in (("➕ Yeni şəxs tanıt", self.enroll_new),
                         ("📸 Nümunə əlavə et", self.enroll_more),
                         ("⭐ Sahib et / çıxar", self.toggle_owner),
                         ("🔍 Qarışığı yoxla", self.check_faces),
                         ("🗑 Sil", self.delete_person)):
            ttk.Button(btns, text=txt, command=cmd, width=22).pack(fill="x", pady=3)
        self.refresh_people()

    def owners_lower(self) -> set[str]:
        return {o.lower() for o in self.cfg["owner"]}

    def refresh_people(self):
        self.tv_people.delete(*self.tv_people.get_children())
        own = self.owners_lower()
        for name, n in people():
            role = "⭐ Sahib" if name.lower() in own else "Etibarlı"
            self.tv_people.insert("", "end", iid=name, values=(name, n, role))
        known = {n.lower() for n, _ in people()}
        missing = [o for o in self.cfg["owner"] if o.lower() not in known]
        if missing:
            self.lbl_saved.config(text=f"⚠️ Sahib siyahısında tanıdılmamış ad var: {', '.join(missing)}")

    def selected_person(self) -> str | None:
        sel = self.tv_people.selection()
        if not sel:
            messagebox.showinfo("Smart Desk", "Əvvəlcə siyahıdan bir şəxs seç.")
            return None
        return sel[0]

    def enroll_new(self):
        name = simpledialog.askstring("Yeni şəxs", "Adı (latın hərfləri, məs. elena):", parent=self)
        if not name:
            return
        name = name.strip()
        if not re.fullmatch(r"[A-Za-z0-9_\-]{1,32}", name):
            messagebox.showerror("Ad", "Yalnız latın hərfləri, rəqəm, _ və - istifadə et.")
            return
        if name.lower() in {n.lower() for n, _ in people()}:
            messagebox.showerror("Ad", f"'{name}' artıq var. 'Nümunə əlavə et' istifadə et.")
            return
        self._enroll(name, append=False)

    def enroll_more(self):
        name = self.selected_person()
        if name:
            self._enroll(name, append=True)

    def _enroll(self, name: str, append: bool):
        if not messagebox.askokcancel("Üz tanıtma", f"Kamera açılacaq — kadrda yalnız '{name}' olsun.\n"
                                      "Göstərişlərə əməl et (sola, sağa bax, gülümsə…).\n\n"
                                      "Arxa fondakı Smart Desk müvəqqəti dayandırılacaq."):
            return
        args = ["enroll.py", "--name", name] + (["--append"] if append else [])

        def done(res, err):
            if err:
                messagebox.showerror("Smart Desk", str(err))
                return
            code, out = res
            self.refresh_people()
            if code != 0:
                self.show_text("Tanıtma alınmadı", out)
                return
            if not append and messagebox.askyesno("Hazırdır", f"✅ '{name}' tanıdıldı.\n\nSahib olsun? "
                                                  "(oturanda proqramlar açılsın, getdikdə kilidlənsin)"):
                self.cfg["owner"].append(name)
                self.save_now()
                self.refresh_people()
        self.bg(lambda: service.run_exclusive(args), done, busy=f"'{name}' tanıdılır…")

    def toggle_owner(self):
        name = self.selected_person()
        if not name:
            return
        if name.lower() in self.owners_lower():
            if len(self.cfg["owner"]) == 1:
                messagebox.showwarning("Smart Desk", "Ən azı bir sahib olmalıdır.")
                return
            self.cfg["owner"] = [o for o in self.cfg["owner"] if o.lower() != name.lower()]
        else:
            self.cfg["owner"].append(name)
        self.save_now()
        self.refresh_people()

    def delete_person(self):
        name = self.selected_person()
        if not name:
            return
        if name.lower() in self.owners_lower() and len(self.cfg["owner"]) == 1:
            messagebox.showwarning("Smart Desk", "Bu yeganə sahibdir. Əvvəlcə başqasını sahib et.")
            return
        if not messagebox.askyesno("Sil", f"'{name}' silinsin? (ehtiyat nüsxə faces/backup_* -də qalacaq)"):
            return
        code, out = service.run_capture(["faces.py", "delete", name])
        if code != 0:
            self.show_text("Silinmədi", out)
        self.cfg["owner"] = [o for o in self.cfg["owner"] if o.lower() != name.lower()]
        self.save_now()
        self.refresh_people()

    def check_faces(self):
        def done(res, err):
            if err:
                messagebox.showerror("Smart Desk", str(err))
                return
            _, out = res
            action = ("🛠 Düzəlt", self.fix_faces) if "check --fix" in out else None
            self.show_text("Üz bazasının yoxlanışı", out, action)
        self.bg(lambda: service.run_capture(["faces.py", "check"]), done, busy="Yoxlanılır…")

    def fix_faces(self):
        def done(res, err):
            self.refresh_people()
            self.show_text("Düzəliş", str(err) if err else res[1])
        self.bg(lambda: service.run_capture(["faces.py", "check", "--fix"]), done, busy="Düzəldilir…")

    # ============================================================ PROQRAMLAR
    def entries(self) -> list:
        oa = self.cfg["on_arrival"]
        if not isinstance(oa.get(actions.OS_KEY), list):
            oa[actions.OS_KEY] = []
        return oa[actions.OS_KEY]

    def urls(self) -> list:
        oa = self.cfg["on_arrival"]
        if not isinstance(oa.get("urls"), list):
            oa["urls"] = []
        return oa["urls"]

    def build_apps(self):
        t = self.tab_apps
        ttk.Label(t, text="Sahib masaya oturanda bunlar açılır. Artıq açıq olan proqram təkrar açılmır.",
                  style="Hint.TLabel").pack(anchor="w", pady=(0, 8))
        body = ttk.Frame(t)
        body.pack(fill="both", expand=True)
        self.tv_apps = ttk.Treeview(body, columns=("name", "kind", "detail"), show="headings", height=10)
        for col, txt, w in (("name", "Ad", 120), ("kind", "Növ", 110), ("detail", "Haradan", 260)):
            self.tv_apps.heading(col, text=txt)
            self.tv_apps.column(col, width=w, anchor="w")
        btns = ttk.Frame(body, padding=(10, 0, 0, 0))
        btns.pack(side="right", fill="y")
        self.tv_apps.pack(side="left", fill="both", expand=True)
        items = [("📁 Proqram (.exe) seç", self.add_exe)]
        if IS_WIN:
            items.append(("🔎 Start menyusundan", self.add_start_menu))
        items += [("🌐 Sayt əlavə et", self.add_url),
                  ("⌨ Əmr əlavə et", self.add_cmd),
                  ("🗑 Sil", self.remove_app),
                  ("▶ İndi aç (test)", self.test_app),
                  ("✔ Hamısını yoxla", self.check_all_apps)]
        for txt, cmd in items:
            ttk.Button(btns, text=txt, command=cmd, width=22).pack(fill="x", pady=3)
        self.refresh_apps()

    def refresh_apps(self):
        self.tv_apps.delete(*self.tv_apps.get_children())
        for i, e in enumerate(self.entries()):
            if isinstance(e, str):
                vals = (e.split()[0], "Əmr", e)
            else:
                exe = actions.find_app(e)
                if exe:
                    vals = (e.get("name", "?"), "Proqram", exe)
                elif e.get("start_menu"):
                    vals = (e.get("name", "?"), "Start menyusu", e["start_menu"])
                else:
                    vals = (e.get("name", "?"), "⚠ tapılmadı",
                            e.get("fallback") and f"əvəzinə {e['fallback']}" or ", ".join(e.get("paths") or []))
            self.tv_apps.insert("", "end", iid=f"e{i}", values=vals)
        for i, u in enumerate(self.urls()):
            self.tv_apps.insert("", "end", iid=f"u{i}", values=(u.split("//")[-1].split("/")[0], "Sayt", u))

    def _added(self):
        self.save_now()
        self.refresh_apps()

    def add_exe(self):
        types = [("Proqramlar", "*.exe"), ("Hamısı", "*.*")] if IS_WIN else [("Hamısı", "*")]
        path = filedialog.askopenfilename(title="Proqram seç", filetypes=types, parent=self)
        if not path:
            return
        path = os.path.normpath(path)
        stem = Path(path).stem
        self.entries().append({"name": stem[:1].upper() + stem[1:], "paths": [path],
                               "process": os.path.basename(path)})
        self._added()

    def add_start_menu(self):
        def done(apps, err):
            if err or not apps:
                messagebox.showerror("Start menyusu", str(err) if err else "Siyahı oxunmadı.")
                return
            self._pick_app(apps)
        self.bg(actions.list_start_menu_apps, done, busy="Start menyusu oxunur…")

    def _pick_app(self, apps: list[tuple[str, str]]):
        win = tk.Toplevel(self)
        win.title("Start menyusundan seç")
        win.geometry("420x460")
        win.transient(self)
        q = tk.StringVar()
        ent = ttk.Entry(win, textvariable=q)
        ent.pack(fill="x", padx=10, pady=(10, 4))
        ent.focus_set()
        lb = tk.Listbox(win, activestyle="dotbox")
        lb.pack(fill="both", expand=True, padx=10)
        shown: list[str] = []

        def refill(*_):
            lb.delete(0, "end")
            shown.clear()
            for name, _id in apps:
                if q.get().lower() in name.lower():
                    shown.append(name)
                    lb.insert("end", name)
        q.trace_add("write", refill)
        refill()

        def choose(*_):
            sel = lb.curselection()
            if not sel:
                return
            name = shown[sel[0]]
            self.entries().append({"name": name, "start_menu": name})
            win.destroy()
            self._added()
        lb.bind("<Double-1>", choose)
        ent.bind("<Return>", lambda e: (lb.selection_set(0), choose()) if shown else None)
        ttk.Button(win, text="Əlavə et", command=choose).pack(pady=10)

    def add_url(self):
        url = simpledialog.askstring("Sayt", "Link (məs. https://github.com):", parent=self)
        if url:
            url = url.strip()
            if not re.match(r"^[a-z][a-z0-9+.-]*:", url):
                url = "https://" + url
            self.urls().append(url)
            self._added()

    def add_cmd(self):
        cmd = simpledialog.askstring("Əmr", "Terminal əmri (məs. code):", parent=self)
        if cmd and cmd.strip():
            self.entries().append(cmd.strip())
            self._added()

    def _selected_app(self):
        sel = self.tv_apps.selection()
        if not sel:
            messagebox.showinfo("Smart Desk", "Əvvəlcə siyahıdan bir element seç.")
            return None
        return sel[0]

    def remove_app(self):
        iid = self._selected_app()
        if not iid:
            return
        kind, idx = iid[0], int(iid[1:])
        (self.entries() if kind == "e" else self.urls()).pop(idx)
        self._added()

    def test_app(self):
        iid = self._selected_app()
        if not iid:
            return
        kind, idx = iid[0], int(iid[1:])
        if kind == "u":
            import webbrowser
            webbrowser.open(self.urls()[idx])
            return
        entry = self.entries()[idx]
        self.bg(lambda: actions.launch_entry(entry),
                lambda msg, err: self.lbl_saved.config(text=f"▶ {msg}" if not err else f"✗ {err}"))

    def check_all_apps(self):
        def run():
            buf = io.StringIO()
            with redirect_stdout(buf):
                actions.check_apps(self.cfg["on_arrival"])
            return buf.getvalue()
        self.bg(run, lambda out, err: self.show_text("Proqramların yoxlanışı", str(err) if err else out),
                busy="Yoxlanılır…")

    # ============================================================ TELEGRAM
    def build_telegram(self):
        t = self.tab_tg
        tg = self.cfg["telegram"]
        ttk.Label(t, text="Yad şəxs masana oturanda şəklini Telegram-a göndərir.\n"
                          "1) Telegram-da @BotFather → /newbot → token-i bura yapışdır\n"
                          "2) Öz botuna /start yaz → 'chat_id-ni tap' bas",
                  style="Hint.TLabel", justify="left").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        self.v_token = tk.StringVar(value=tg.get("bot_token") or "")
        self.v_chat = tk.StringVar(value=str(tg.get("chat_id") or ""))
        self.v_notify = tk.BooleanVar(value=bool(tg.get("notify_on_lock", False)))
        ttk.Label(t, text="Bot token:").grid(row=1, column=0, sticky="w")
        self.ent_token = ttk.Entry(t, textvariable=self.v_token, width=52, show="•")
        self.ent_token.grid(row=1, column=1, sticky="we", padx=8, pady=4)
        ttk.Button(t, text="👁", width=3, command=lambda: self.ent_token.config(
            show="" if self.ent_token.cget("show") else "•")).grid(row=1, column=2)
        ttk.Label(t, text="Chat ID:").grid(row=2, column=0, sticky="w")
        ttk.Entry(t, textvariable=self.v_chat, width=52).grid(row=2, column=1, sticky="we", padx=8, pady=4)
        ttk.Checkbutton(t, text="Hər ekran kilidlənəndə qısa mesaj göndər", variable=self.v_notify,
                        command=self.schedule_save).grid(row=3, column=1, sticky="w", pady=(6, 0))
        row = ttk.Frame(t)
        row.grid(row=4, column=1, sticky="w", pady=14)
        ttk.Button(row, text="🔎 chat_id-ni tap", command=self.find_chat).pack(side="left")
        ttk.Button(row, text="✉ Test mesajı", command=self.test_tg).pack(side="left", padx=8)
        t.columnconfigure(1, weight=1)
        for v in (self.v_token, self.v_chat):
            v.trace_add("write", self.schedule_save)

    def collect_telegram(self):
        tg = self.cfg["telegram"]
        tg["bot_token"] = self.v_token.get().strip()
        tg["chat_id"] = self.v_chat.get().strip()
        tg["notify_on_lock"] = bool(self.v_notify.get())

    def find_chat(self):
        tg = actions.Telegram(self.v_token.get().strip(), None)
        if not tg.token:
            messagebox.showwarning("Telegram", "Əvvəlcə bot token-i yaz.")
            return

        def done(chats, err):
            if err:
                messagebox.showerror("Telegram", f"Alınmadı: {err}")
            elif not chats:
                messagebox.showinfo("Telegram", "Mesaj tapılmadı. Telegram-da öz botuna /start yaz və yenidən bas.")
            else:
                self.v_chat.set(chats[0][0])
                messagebox.showinfo("Telegram", "Tapıldı: " + ", ".join(f"{c} ({n})" for c, n in chats))
        self.bg(tg.find_chat_ids, done, busy="Telegram yoxlanılır…")

    def test_tg(self):
        tg = actions.Telegram(self.v_token.get().strip(), self.v_chat.get().strip())
        self.bg(lambda: tg.send_text("👋 Smart Desk qoşuldu!"),
                lambda ok, err: messagebox.showinfo("Telegram", "✅ Göndərildi" if ok else f"❌ Göndərilmədi {err or ''}"),
                busy="Göndərilir…")

    # ============================================================ JURNAL
    def build_log(self):
        t = self.tab_log
        row = ttk.Frame(t)
        row.pack(fill="x", pady=(0, 8))
        ttk.Button(row, text="⟳ Yenilə", command=self.refresh_log).pack(side="left")
        ttk.Button(row, text="📁 Proqram qovluğu", command=lambda: open_path(BASE_DIR)).pack(side="right")
        self.txt_log = tk.Text(t, wrap="none", font=("Consolas", 10), padx=8, pady=8, height=20)
        self.txt_log.pack(fill="both", expand=True)

    def refresh_log(self):
        def read():
            from events import EventLog
            report = EventLog().report()
            try:
                lines = service.LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-150:]
            except OSError:
                lines = ["(desk.log hələ yoxdur)"]
            return report + "\n\n──── desk.log (son sətirlər) ────\n" + "\n".join(lines)

        def show(text, err):
            self.txt_log.config(state="normal")
            self.txt_log.delete("1.0", "end")
            self.txt_log.insert("1.0", str(err) if err else text)
            self.txt_log.see("end")
            self.txt_log.config(state="disabled")
        self.bg(read, show)


def main():
    if IS_WIN:
        try:  # yüksək DPI ekranlarda bulanıq olmasın
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
    app = App()

    def report(exc, val, tb):
        import traceback
        text = "".join(traceback.format_exception(exc, val, tb))
        try:
            with open(BASE_DIR / "app.log", "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except OSError:
            pass
        messagebox.showerror("Smart Desk — xəta", str(val))
    app.report_callback_exception = report
    app.mainloop()


if __name__ == "__main__":
    main()
