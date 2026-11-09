"""Üzünü sistemə tanıt.

  python enroll.py --name ruslan                 # kamera ilə (~25 nümunə)
  python enroll.py --name ruslan --images ./pics # hazır şəkillərdən
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import cv2
import numpy as np

from face_engine import FaceDB, FaceEngine, open_camera

# OpenCV şrifti ə/ş/ç/ğ/ı/ö/ü göstərmir, ona görə ekrandakı yazılar ASCII-dir
TIPS = ["Duz kameraya bax", "Basini bir az sola cevir", "Bir az saga cevir",
        "Yuxari bax", "Asagi bax", "Gulumse :)", "Eynek varsa tax / cixar"]


def largest(faces):
    return max(faces, key=lambda f: f.box[2] * f.box[3]) if faces else None


def from_images(engine: FaceEngine, folder: Path) -> list[np.ndarray]:
    embs = []
    for p in sorted(folder.iterdir()):
        img = cv2.imread(str(p))
        if img is None:
            continue
        face = largest(engine.detect(img))
        if face is None:
            print(f"  ✗ {p.name}: üz tapılmadı")
            continue
        embs.append(engine.embed(img, face))
        print(f"  ✓ {p.name}")
    return embs


def from_camera(engine: FaceEngine, cam: int, samples: int) -> list[np.ndarray]:
    cap = open_camera(cam)
    embs, last = [], 0.0
    try:
        while len(embs) < samples:
            ok, frame = cap.read()
            if not ok:
                continue
            frame = cv2.flip(frame, 1)
            faces = engine.detect(frame)
            view = frame.copy()
            tip = TIPS[(len(embs) * len(TIPS)) // samples]
            if len(faces) == 1 and time.time() - last > 0.35:
                embs.append(engine.embed(frame, faces[0]))
                last = time.time()
            for f in faces:
                x, y, w, h = f.box
                color = (0, 255, 0) if len(faces) == 1 else (0, 0, 255)
                cv2.rectangle(view, (x, y), (x + w, y + h), color, 2)
            msg = tip if len(faces) == 1 else ("Kadrda yalniz sen olmalisan" if faces else "Uz gorunmur")
            bar = int(view.shape[1] * len(embs) / samples)
            cv2.rectangle(view, (0, view.shape[0] - 8), (bar, view.shape[0]), (0, 255, 0), -1)
            cv2.putText(view, f"{msg}  [{len(embs)}/{samples}]", (12, 32),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
            cv2.imshow("Smart Desk - enroll (q = cixis)", view)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
    return embs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="şəxsin adı (məs. ruslan)")
    ap.add_argument("--images", type=Path, help="kamera əvəzinə şəkil qovluğu")
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--samples", type=int, default=25)
    ap.add_argument("--append", action="store_true", help="mövcud nümunələrə əlavə et")
    args = ap.parse_args()

    engine = FaceEngine()
    embs = from_images(engine, args.images) if args.images else from_camera(engine, args.camera, args.samples)
    if len(embs) < 3:
        raise SystemExit("Kifayət qədər nümunə yığılmadı (ən azı 3 lazımdır).")

    arr = np.stack(embs)
    db = FaceDB()
    if args.append and args.name in db.people:
        arr = np.vstack([db.people[args.name], arr])
    path = FaceDB.save(args.name, arr)
    print(f"✅ '{args.name}' yadda saxlandı: {len(arr)} nümunə → {path}")


if __name__ == "__main__":
    main()
