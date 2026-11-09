"""Üz bazasını yoxla və düzəlt.

  python faces.py list                 # kimlər var, neçə nümunə, bir-birinə nə qədər oxşar
  python faces.py check                # qarışmış nümunələri tap (dəyişiklik etmir)
  python faces.py check --fix          # səhv yerdə olan nümunələri düzgün şəxsə köçür
  python faces.py swap ruslan elena    # iki şəxsin adlarını dəyiş (tam qarışıblarsa)
  python faces.py whoami               # kamera: indi kimi görür? (adlar düz düşübmü)
  python faces.py delete elena         # sil (sonra yenidən enroll et)
  python faces.py restore              # son ehtiyat nüsxəni geri qaytar

Hər dəyişiklikdən əvvəl faces/backup_<vaxt>/ qovluğuna ehtiyat nüsxə çıxarılır.
"""
from __future__ import annotations

import argparse
import itertools
import shutil
import time
from datetime import datetime

import numpy as np

from face_engine import FACES_DIR, FaceDB


# ---------------------------------------------------------------- köməkçilər
def load() -> dict[str, np.ndarray]:
    db = FaceDB()
    if not db.people:
        raise SystemExit(f"Heç kim tanıdılmayıb ({FACES_DIR}). Əvvəlcə: python enroll.py --name <ad>")
    return db.people


def backup() -> str:
    dst = FACES_DIR / f"backup_{datetime.now():%Y%m%d_%H%M%S_%f}"
    dst.mkdir(parents=True)
    for p in FACES_DIR.glob("*.npy"):
        shutil.copy2(p, dst / p.name)
    print(f"💾 Ehtiyat nüsxə: {dst}")
    return str(dst)


def pair_similarity(a: np.ndarray, b: np.ndarray, same: bool = False) -> float:
    sims = a @ b.T
    if same:
        if len(a) < 2:
            return float("nan")
        sims = sims[~np.eye(len(a), dtype=bool)]
    return float(np.mean(sims))


def spherical_kmeans(x: np.ndarray, k: int, restarts: int = 20, seed: int = 0) -> tuple[np.ndarray, float]:
    """Cosine k-means (vektorlar normallaşdırılıb). (etiketlər, keyfiyyət) qaytarır."""
    rng = np.random.default_rng(seed)
    best_labels, best_score = None, -np.inf
    for _ in range(restarts):
        # k-means++ başlanğıcı
        centers = [x[rng.integers(len(x))]]
        for _ in range(1, k):
            d = 1 - np.max(x @ np.stack(centers).T, axis=1)
            d = np.clip(d, 1e-9, None) ** 2
            centers.append(x[rng.choice(len(x), p=d / d.sum())])
        c = np.stack(centers)
        for _ in range(50):
            labels = np.argmax(x @ c.T, axis=1)
            new = np.stack([x[labels == j].mean(0) if np.any(labels == j) else c[j] for j in range(k)])
            new /= np.linalg.norm(new, axis=1, keepdims=True) + 1e-9
            if np.allclose(new, c):
                break
            c = new
        score = float(np.sum(np.max(x @ c.T, axis=1)))
        if score > best_score:
            best_labels, best_score = labels, score
    return best_labels, best_score


# ---------------------------------------------------------------- əmrlər
def cmd_list(_args) -> None:
    people = load()
    names = list(people)
    print("Şəxslər:")
    for n in names:
        print(f"  • {n:<14} {len(people[n]):>3} nümunə   daxili oxşarlıq: "
              f"{pair_similarity(people[n], people[n], same=True):.2f}")
    if len(names) > 1:
        print("\nOxşarlıq matrisi (diaqonal = özü ilə; başqası ilə < 0.30 olmalıdır):")
        print(" " * 16 + "".join(f"{n[:10]:>11}" for n in names))
        for a in names:
            row = "".join(f"{pair_similarity(people[a], people[b], same=a == b):>11.2f}" for b in names)
            print(f"  {a[:14]:<14}{row}")


def cmd_check(args) -> None:
    people = load()
    names = list(people)
    if len(names) < 2:
        print("Yalnız 1 şəxs var — qarışma mümkün deyil. Adın düz olduğunu yoxlamaq üçün: python faces.py whoami")
        return

    x = np.vstack([people[n] for n in names])
    owner_of = np.concatenate([[i] * len(people[n]) for i, n in enumerate(names)])
    labels, _ = spherical_kmeans(x, len(names))

    # Klasterləri adlara elə bağla ki, ən çox nümunə öz yerində qalsın
    best_perm, best_hits = None, -1
    for perm in itertools.permutations(range(len(names))):
        hits = int(np.sum(np.array(perm)[labels] == owner_of))
        if hits > best_hits:
            best_perm, best_hits = perm, hits
    predicted = np.array(best_perm)[labels]

    # Klasterlər həqiqətən fərqli insanlardırmı?
    centers = np.stack([x[predicted == i].mean(0) for i in range(len(names)) if np.any(predicted == i)])
    centers /= np.linalg.norm(centers, axis=1, keepdims=True)
    cross = centers @ centers.T
    max_cross = float(np.max(cross[~np.eye(len(centers), dtype=bool)])) if len(centers) > 1 else 0.0

    print("Nəticə:")
    moves: dict[tuple[str, str], int] = {}
    for i, n in enumerate(names):
        mine = owner_of == i
        wrong = mine & (predicted != i)
        print(f"  • {n:<14} {mine.sum():>3} nümunə  →  {mine.sum() - wrong.sum()} düzgün, {wrong.sum()} səhv yerdə")
        for j in set(predicted[wrong]):
            moves[(n, names[j])] = int(np.sum(wrong & (predicted == j)))

    if max_cross > 0.45:
        print(f"\n⚠️  Qruplar bir-birinə çox oxşardır ({max_cross:.2f}). Ola bilər ki, hər iki faylda eyni "
              "insan var və ya çox qarışıqdır.\n   Ən etibarlı yol: hər iki şəxsi silib yenidən tanıtmaq:\n"
              + "".join(f"     python faces.py delete {n}\n" for n in names)
              + "".join(f"     python enroll.py --name {n}\n" for n in names))
        return
    if not moves:
        print("\n✅ Qarışma tapılmadı — hər faylda bir insan var.")
        print("   Adlar dəyişik düşübsə (Ruslan ↔ Elena), yoxla:  python faces.py whoami")
        print("   Lazım olsa:  python faces.py swap " + " ".join(names[:2]))
        return

    print("\nSəhv yerdə olanlar:")
    for (src, dst), cnt in moves.items():
        print(f"  {cnt} nümunə: '{src}' faylındadır, amma '{dst}'-ə aiddir")
    if not args.fix:
        print("\nDüzəltmək üçün:  python faces.py check --fix")
        return

    backup()
    for i, n in enumerate(names):
        np.save(FACES_DIR / f"{n}.npy", x[predicted == i].astype(np.float32))
    print("✅ Düzəldildi. Yeni vəziyyət:\n")
    cmd_list(args)
    print("\nİndi adların düzgün olduğunu yoxla:  python faces.py whoami")


def cmd_swap(args) -> None:
    people = load()
    a, b = args.a, args.b
    for n in (a, b):
        if n not in people:
            raise SystemExit(f"'{n}' tapılmadı. Mövcud: {', '.join(people)}")
    backup()
    np.save(FACES_DIR / f"{a}.npy", people[b])
    np.save(FACES_DIR / f"{b}.npy", people[a])
    print(f"🔁 '{a}' ↔ '{b}' dəyişdirildi.")


def cmd_delete(args) -> None:
    p = FACES_DIR / f"{args.name}.npy"
    if not p.exists():
        raise SystemExit(f"'{args.name}' tapılmadı")
    backup()
    p.unlink()
    print(f"🗑️  '{args.name}' silindi. Yenidən tanıtmaq:  python enroll.py --name {args.name}")


def cmd_restore(_args) -> None:
    backups = sorted(FACES_DIR.glob("backup_*"))
    if not backups:
        raise SystemExit("Ehtiyat nüsxə yoxdur")
    src = backups[-1]
    for p in FACES_DIR.glob("*.npy"):
        p.unlink()
    for p in src.glob("*.npy"):
        shutil.copy2(p, FACES_DIR / p.name)
    print(f"↩️  Geri qaytarıldı: {src.name}")


def cmd_whoami(args) -> None:
    from face_engine import FaceEngine, open_camera

    db = FaceDB(threshold=args.threshold)
    if not db.people:
        raise SystemExit("Heç kim tanıdılmayıb")
    engine = FaceEngine()
    cap = open_camera(args.camera)
    print("Kameraya bax. Hər saniyə nəticə yazılacaq (Ctrl+C = çıxış).\n")
    try:
        last = 0.0
        while True:
            ok, frame = cap.read()
            if not ok or time.time() - last < 1.0:
                continue
            last = time.time()
            faces = engine.detect(frame)
            if not faces:
                print("  (üz görünmür)")
                continue
            for f in faces:
                emb = engine.embed(frame, f)
                scores = {n: float(np.sort(s @ emb)[::-1][:3].mean()) for n, s in db.people.items()}
                name, _ = db.identify(emb)
                detail = "  ".join(f"{n}={v:.2f}" for n, v in sorted(scores.items(), key=lambda t: -t[1]))
                print(f"  → {name or 'YAD':<12} | {detail}")
    except KeyboardInterrupt:
        pass
    finally:
        cap.release()


def main() -> None:
    ap = argparse.ArgumentParser(description="Üz bazasını yoxla və düzəlt")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    c = sub.add_parser("check")
    c.add_argument("--fix", action="store_true")
    c.set_defaults(fn=cmd_check)
    s = sub.add_parser("swap")
    s.add_argument("a")
    s.add_argument("b")
    s.set_defaults(fn=cmd_swap)
    d = sub.add_parser("delete")
    d.add_argument("name")
    d.set_defaults(fn=cmd_delete)
    sub.add_parser("restore").set_defaults(fn=cmd_restore)
    w = sub.add_parser("whoami")
    w.add_argument("--camera", type=int, default=0)
    w.add_argument("--threshold", type=float, default=0.40)
    w.set_defaults(fn=cmd_whoami)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
