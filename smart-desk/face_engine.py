"""Üz aşkarlama (YuNet) və üz tanıma (SFace) — yalnız OpenCV ilə.

dlib / face_recognition qurmaq lazım deyil: iki kiçik ONNX model ilk
işə salınmada avtomatik yüklənir (~40 MB).
"""
from __future__ import annotations

import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "models"
FACES_DIR = BASE_DIR / "faces"

_ZOO = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models"
DETECTOR = ("face_detection_yunet_2023mar.onnx",
            f"{_ZOO}/face_detection_yunet/face_detection_yunet_2023mar.onnx")
RECOGNIZER = ("face_recognition_sface_2021dec.onnx",
              f"{_ZOO}/face_recognition_sface/face_recognition_sface_2021dec.onnx")


def _ensure_model(name: str, url: str) -> Path:
    MODELS_DIR.mkdir(exist_ok=True)
    path = MODELS_DIR / name
    if not path.exists() or path.stat().st_size < 100_000:
        print(f"[model] {name} yüklənir...")
        tmp = path.with_suffix(".part")
        urllib.request.urlretrieve(url, tmp)
        tmp.replace(path)
    return path


def open_camera(index: int, width: int = 640, height: int = 480) -> cv2.VideoCapture:
    # Windows-da DirectShow backend-i kameranı xeyli tez açır
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW) if os.name == "nt" else cv2.VideoCapture(index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    if not cap.isOpened():
        raise SystemExit(f"Kamera #{index} açılmadı (başqa proqram istifadə edir? icazə verilib?)")
    return cap


@dataclass
class Face:
    box: tuple[int, int, int, int]  # x, y, w, h
    score: float                    # aşkarlama inamı
    raw: np.ndarray                 # YuNet nəticəsi (alignCrop üçün)
    name: str | None = None         # tanınan şəxs (None = yad)
    similarity: float = 0.0


class FaceEngine:
    def __init__(self, detect_score: float = 0.8):
        det = _ensure_model(*DETECTOR)
        rec = _ensure_model(*RECOGNIZER)
        self.detector = cv2.FaceDetectorYN.create(str(det), "", (320, 320), detect_score, 0.3, 50)
        self.recognizer = cv2.FaceRecognizerSF.create(str(rec), "")

    def detect(self, frame: np.ndarray) -> list[Face]:
        h, w = frame.shape[:2]
        self.detector.setInputSize((w, h))
        _, faces = self.detector.detect(frame)
        if faces is None:
            return []
        out = []
        for f in faces:
            x, y, bw, bh = (int(v) for v in f[:4])
            out.append(Face(box=(x, y, bw, bh), score=float(f[-1]), raw=f))
        return out

    def embed(self, frame: np.ndarray, face: Face) -> np.ndarray:
        aligned = self.recognizer.alignCrop(frame, face.raw)
        feat = self.recognizer.feature(aligned).flatten().astype(np.float32)
        return feat / (np.linalg.norm(feat) + 1e-9)


class FaceDB:
    """faces/<ad>.npy faylları: hər şəxs üçün N x 128 normallaşdırılmış vektor."""

    def __init__(self, threshold: float = 0.40):
        self.threshold = threshold
        self.people: dict[str, np.ndarray] = {}
        self.reload()

    def reload(self) -> None:
        self.people.clear()
        if FACES_DIR.exists():
            for p in sorted(FACES_DIR.glob("*.npy")):
                self.people[p.stem] = np.load(p)

    @staticmethod
    def save(name: str, embeddings: np.ndarray) -> Path:
        FACES_DIR.mkdir(exist_ok=True)
        path = FACES_DIR / f"{name}.npy"
        np.save(path, embeddings.astype(np.float32))
        return path

    def identify(self, emb: np.ndarray) -> tuple[str | None, float]:
        best_name, best = None, -1.0
        for name, samples in self.people.items():
            # Ən yaxın 3 nümunənin ortası — tək təsadüfi uyğunluğa qarşı dayanıqlı
            sims = np.sort(samples @ emb)[::-1][:3]
            score = float(sims.mean())
            if score > best:
                best_name, best = name, score
        if best < self.threshold:
            return None, best
        return best_name, best
