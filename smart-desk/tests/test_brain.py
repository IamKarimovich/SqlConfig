"""Kamerasız vəziyyət maşını testləri:  python -m pytest tests  (və ya python tests/test_brain.py)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desk import DeskBrain  # noqa: E402


def brain(**kw):
    return DeskBrain(owner="me", arrive_frames=3, lock_after=10, relaunch_after=600,
                     stranger_frames=2, stranger_cooldown=60, **kw)


def run(b, frames):
    out = []
    for t, names in frames:
        out += [(t, c) for c in b.step(t, names)]
    return out


def test_arrive_launch_then_lock():
    b = brain()
    ev = run(b, [(0, ["me"]), (1, ["me"]), (2, ["me"])])
    assert ev == [(2, "arrived"), (2, "launch")]
    ev = run(b, [(5, []), (12.5, []), (13, [])])   # son görülmə t=2, 10s sonra kilid
    assert ev == [(12.5, "left"), (12.5, "lock")]


def test_short_glance_away_does_not_lock():
    b = brain()
    run(b, [(0, ["me"]), (1, ["me"]), (2, ["me"])])
    assert run(b, [(5, []), (9, []), (10, ["me"]), (19, [])]) == []


def test_relaunch_only_after_long_break():
    b = brain()
    run(b, [(0, ["me"]), (1, ["me"]), (2, ["me"]), (20, [])])        # getdi t=20
    ev = run(b, [(100, ["me"]), (101, ["me"]), (102, ["me"])])       # qısa fasilə
    assert [c for _, c in ev] == ["arrived"]
    run(b, [(200, [])])                                              # getdi t=200
    ev = run(b, [(900, ["me"]), (901, ["me"]), (902, ["me"])])       # uzun fasilə
    assert [c for _, c in ev] == ["arrived", "launch"]


def test_stranger_alert_with_cooldown():
    b = brain()
    ev = run(b, [(0, [None]), (1, [None]), (2, [None]), (30, [None]), (61, [None])])
    assert ev == [(1, "stranger"), (61, "stranger")]


def test_single_false_negative_frame_is_ignored():
    b = brain()
    assert run(b, [(0, [None]), (1, ["me"]), (2, [None])]) == []


def test_shoulder_surfer_only_when_enabled():
    for flag, expected in ((False, []), (True, ["stranger"])):
        b = brain(alert_when_owner_present=flag)
        run(b, [(0, ["me"]), (1, ["me"]), (2, ["me"])])
        ev = run(b, [(3, ["me", None]), (4, ["me", None])])
        assert [c for _, c in ev] == expected


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("✓", name)
