"""Unit tests for the streaming compensation detector."""
from app.detection.domain.services import CompensationDetector


def _run(detector, pairs):
    return [r for r in (detector.add_sample(a, p) for a, p in pairs) if r]


def test_fires_when_proximal_sweeps_while_angle_stalls():
    detector = CompensationDetector()
    # angle stalls ~30, proximal oscillates 0<->20 (range 20 >= 15) for a full window
    pairs = [(30.0 + (i % 2), 0.0 if i % 2 == 0 else 20.0) for i in range(20)]
    fired = _run(detector, pairs)
    assert len(fired) == 1
    assert fired[0]["type"] == "ShoulderCompensation"


def test_no_fire_during_normal_rep():
    detector = CompensationDetector()
    # angle ramps 0->95 (the joint IS moving), proximal flat -> a rep, not compensation
    pairs = [(i * 5.0, 3.0) for i in range(20)]
    assert _run(detector, pairs) == []


def test_no_fire_when_proximal_is_none():
    detector = CompensationDetector()
    pairs = [(30.0, None) for _ in range(40)]
    assert _run(detector, pairs) == []


def test_no_fire_below_proximal_threshold():
    detector = CompensationDetector()
    # angle stalls, but proximal sweeps only 0<->10 (< 15)
    pairs = [(30.0, (i % 2) * 10.0) for i in range(20)]
    assert _run(detector, pairs) == []


def test_partial_window_does_not_fire():
    detector = CompensationDetector()  # window 20
    pairs = [(30.0, (i % 2) * 20.0) for i in range(10)]  # only 10 samples
    assert _run(detector, pairs) == []


def test_cooldown_collapses_one_episode_to_one_event():
    detector = CompensationDetector()
    # sustain the compensation condition across 2x the window -> still one event
    pairs = [(30.0, (i % 2) * 20.0) for i in range(40)]
    assert len(_run(detector, pairs)) == 1


def test_none_samples_do_not_corrupt_the_window():
    detector = CompensationDetector()
    # interleave None with real compensation pairs; only the real ones fill the window
    pairs = []
    for i in range(20):
        pairs.append((30.0, (i % 2) * 20.0))
        pairs.append((30.0, None))
    assert len(_run(detector, pairs)) == 1
