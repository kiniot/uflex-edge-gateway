"""Unit tests for the incremental repetition detector."""
from monitoring.domain.services import IncrementalRepetitionDetector


def _detect(angles, target_rom=None, max_safe_angle=None):
    detector = IncrementalRepetitionDetector(target_rom, max_safe_angle)
    reps = [detector.add_sample(a) for a in angles]
    reps = [r for r in reps if r]
    tail = detector.flush()
    if tail:
        reps.append(tail)
    return reps


def test_two_clean_reps_are_good():
    reps = _detect([0, 90, 0, 90, 0], target_rom=80, max_safe_angle=95)
    assert len(reps) == 2
    assert all(r["classification"] == "good" for r in reps)
    assert all(r["achieved_rom"] == 90 and r["peak_angle"] == 90 for r in reps)


def test_short_rep_is_incomplete():
    reps = _detect([0, 50, 0], target_rom=80)
    assert len(reps) == 1
    assert reps[0]["classification"] == "incomplete"
    assert reps[0]["met_target"] is False


def test_rep_crossing_ceiling_is_unsafe():
    reps = _detect([0, 100, 0], target_rom=80, max_safe_angle=95)
    assert len(reps) == 1
    assert reps[0]["classification"] == "unsafe"
    assert reps[0]["unsafe"] is True


def test_jitter_below_threshold_yields_no_reps():
    reps = _detect([0, 5, 0, 4, 0])  # no target -> threshold = MIN_ROM_FOR_REP (10)
    assert reps == []


def test_open_flexion_flushes_as_rep():
    # Rises and stays up (return cut off); flush should still count it.
    reps = _detect([0, 90], target_rom=80, max_safe_angle=95)
    assert len(reps) == 1
    assert reps[0]["classification"] == "good"
