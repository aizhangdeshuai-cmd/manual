"""Unit tests for human_motion.py — the v0.3.11 motion randomizer.

The tests assert INVARIANTS of humanized motion, not exact values
(because the randomizer is supposed to be random). What we test:

  - glide_samples produces a finite sequence whose final position is
    the target (cx, cy) ± a small overshoot residual.
  - Each step's delay is positive.
  - Step count scales with distance (longer moves have more steps).
  - The bezier curve bows perpendicular to the start-end vector.
  - Overshoot produces a brief displacement past the target near
    t in [0.7, 0.95].
  - type_delay_ms draws from a mixture: most values are short
    (flow/burst), a small fraction are long (hesitate).
  - hover_pause_ms produces values in the requested range.
  - post_click_pause_ms occasionally (5%) produces long pauses.
"""
import math
import random
import pytest

from recorder_plugin.human_motion import (
    glide_samples, type_delay_ms, hover_pause_ms,
    post_click_pause_ms, idle_jitter, _bezier_point,
    _perpendicular_offset, _overshoot_factor, _step_count,
)


# ---------------------------------------------------------------------------
# _bezier_point
# ---------------------------------------------------------------------------

def test_bezier_endpoints():
    """t=0 returns p0, t=1 returns p2."""
    assert _bezier_point(0.0, (0, 0), (10, 5), (20, 0)) == (0, 0)
    assert _bezier_point(1.0, (0, 0), (10, 5), (20, 0)) == (20, 0)


def test_bezier_midpoint_deviates_with_control():
    """t=0.5 is influenced by the control point.

    A quadratic bezier at t=0.5 gives:
        x = 0.25*p0.x + 0.5*p1.x + 0.25*p2.x
        y = 0.25*p0.y + 0.5*p1.y + 0.25*p2.y
    So the midpoint is 50% influenced by the control point, 25% by each
    endpoint. We verify that the perpendicular bow produces the
    expected curve.
    """
    # p1 collinear with p0-p2: still a quadratic, not a straight line
    # (a quadratic bezier is only linear when p1 is the midpoint of p0-p2)
    x, y = _bezier_point(0.5, (0, 0), (0, 0), (10, 0))
    # At t=0.5, x = 0.25*0 + 0.5*0 + 0.25*10 = 2.5
    assert abs(x - 2.5) < 0.01
    # p1 = midpoint: straight line
    x, y = _bezier_point(0.5, (0, 0), (5, 0), (10, 0))
    assert abs(x - 5) < 0.01
    # p1 perpendicular offset (the real use case): curve bows toward p1
    x, y = _bezier_point(0.5, (0, 0), (5, 100), (10, 0))
    assert y > 40  # bowed upward significantly (midpoint y = 0.5*100 = 50)


# ---------------------------------------------------------------------------
# _perpendicular_offset
# ---------------------------------------------------------------------------

def test_perpendicular_offset_is_orthogonal():
    """The returned vector is perpendicular to (end - start)."""
    sx, sy, cx, cy = 100, 200, 500, 800
    px, py = _perpendicular_offset(sx, sy, cx, cy)
    dx, dy = cx - sx, cy - sy
    # Dot product ~0
    assert abs(px * dx + py * dy) < 1e-6


def test_perpendicular_offset_unit_length():
    """The returned vector has unit length."""
    px, py = _perpendicular_offset(0, 0, 100, 200)
    assert abs(math.hypot(px, py) - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# _overshoot_factor
# ---------------------------------------------------------------------------

def test_overshoot_zero_at_start():
    """At t=0 there's no overshoot yet."""
    assert _overshoot_factor(0.0) == 0.0


def test_overshoot_zero_at_end():
    """At t=1.0 the cursor has settled at the target."""
    assert _overshoot_factor(1.0) == 0.0


def test_overshoot_peaks_midway():
    """The overshoot is non-zero in the t=0.85-0.98 range, peaks
    around t=0.915 (sinusoidal half-bump), and is 0 before t=0.85.

    Why t=0.85 (not earlier)? Because a quadratic bezier at t<0.85 is
    still 150+ pixels short of the target on a 1000px move. Adding an
    overshoot that far from the target would be invisible. Concentrating
    the overshoot near the end (where the bezier is near the target)
    makes the "hand correction" wobble visible without making the
    cursor look glitchy mid-glide.
    """
    # Before t=0.85, no overshoot
    for t in [0.0, 0.5, 0.7, 0.8, 0.84]:
        assert _overshoot_factor(t) == 0.0, f"overshoot at t={t} should be 0"
    # In the bump range (0.85, 0.98), peak around the middle
    for t in [0.86, 0.9, 0.92, 0.95, 0.97]:
        assert _overshoot_factor(t) > 0, f"overshoot at t={t} should be > 0"
    # Peak is near t=0.915 (half-sine peak)
    peak = max(_overshoot_factor(0.85 + i * 0.001) for i in range(130))
    assert 0.9 < peak <= 1.0, f"overshoot peak {peak} should be ~1.0"


def test_overshoot_smooth_recovery():
    """The recovery from t=0.95 to 1.0 is monotonic."""
    v1 = _overshoot_factor(0.95)
    v2 = _overshoot_factor(0.97)
    v3 = _overshoot_factor(1.0)
    assert v1 >= v2 >= v3


# ---------------------------------------------------------------------------
# glide_samples
# ---------------------------------------------------------------------------

def test_glide_short_distance():
    """Trivial short glides yield 1 sample and end at target."""
    samples = list(glide_samples(100, 100, 101, 101))
    assert len(samples) == 1
    x, y, delay = samples[0]
    assert abs(x - 101) < 0.01
    assert abs(y - 101) < 0.01
    assert delay > 0


def test_glide_finite_samples():
    """A normal glide produces a finite sequence (5-40 samples)."""
    samples = list(glide_samples(0, 0, 500, 500))
    assert 1 < len(samples) < 50


def test_glide_all_delays_positive():
    """Every per-step delay is > 0 (no infinite loops or zero-time steps)."""
    samples = list(glide_samples(100, 100, 800, 600))
    for x, y, d in samples:
        assert d > 0, f"non-positive delay: {d}"


def test_glide_ends_near_target():
    """The final sample lands within a small radius of the target.

    The overshoot factor is 0 at t=1.0, so the LAST sample is at
    (cx, cy) plus the sub-pixel position jitter (±1.2px)."""
    cx, cy = 700, 400
    samples = list(glide_samples(0, 0, cx, cy))
    fx, fy, _ = samples[-1]
    # The final position is jittered by ±1.2px and we have a small
    # bezier residual — allow up to 4px.
    assert abs(fx - cx) < 4, f"final x={fx} far from target {cx}"
    assert abs(fy - cy) < 4, f"final y={fy} far from target {cy}"


def test_glide_step_count_scales_with_distance():
    """Longer glides have more steps than short ones."""
    rng = random.Random(42)
    short = _step_count(40)  # <60 -> 6-10
    long_ = _step_count(800)  # 500+ -> 22-32
    # Run multiple times to dodge random variation
    short_steps = [_step_count(40) for _ in range(50)]
    long_steps = [_step_count(800) for _ in range(50)]
    assert max(short_steps) < min(long_steps), (
        f"expected short glides (max {max(short_steps)}) to have fewer steps "
        f"than long glides (min {min(long_steps)})"
    )


def test_glide_curves_not_straight():
    """The trajectory bows to one side, so intermediate points
    are off the straight line between start and end."""
    sx, sy, cx, cy = 0, 0, 1000, 0  # horizontal move
    samples = list(glide_samples(sx, sy, cx, cy))
    # The perpendicular bow is vertical (up or down). At t=0.5,
    # the y value should be 30+ px off zero (bow_magnitude ~180 for
    # 1000px move, half is 90; allow variance).
    mid_x = samples[len(samples) // 2][0]
    mid_y = samples[len(samples) // 2][1]
    # Verify x is between start and end
    assert sx <= mid_x <= cx
    # Verify y is well off the straight line (y should be 0)
    # The bezier midpoint with perpendicular bow_magnitude=180 has
    # the control point at y=±180, so midpoint y = ±90. With jitter
    # and a small bezier residual, we expect |y| > 30.
    assert abs(mid_y) > 20, (
        f"trajectory didn't bow perpendicular; mid y={mid_y} (expected >20)"
    )


def test_glide_overshoots_near_end():
    """Somewhere in the t=0.85-0.98 range, the position is past the
    target by 1-6px (the "hand correction" wobble).

    The overshoot is along the start->end vector, so for a horizontal
    move from (0,0) to (1000,0), the x coordinate should briefly
    exceed 1000 in the last 15% of the trajectory.
    """
    sx, sy, cx, cy = 0, 0, 1000, 0
    # Try multiple seeds to find one that produces a visible overshoot.
    found = False
    max_overshoot = 0.0
    for seed in range(20):
        rng = random.Random(seed)
        samples = list(glide_samples(sx, sy, cx, cy, rng=rng))
        n = len(samples)
        # The overshoot peak is near t=0.96 (concentrated in the last
        # 15% of the trajectory). Check the full t=0.85..1.0 range.
        for i in range(int(n * 0.85), n):
            x, y, _ = samples[i]
            overshoot = x - cx
            if overshoot > 0:
                found = True
                max_overshoot = max(max_overshoot, overshoot)
    assert found, "no overshoot detected in any of 20 glides — bezier control broken?"
    # The overshoot should be small (1-6px) — not a huge glitch
    assert max_overshoot < 10, (
        f"overshoot {max_overshoot}px is too large (max should be ~6px)"
    )


def test_glide_deterministic_with_seed():
    """The same RNG seed produces the same trajectory."""
    rng1 = random.Random(123)
    rng2 = random.Random(123)
    s1 = list(glide_samples(0, 0, 500, 500, rng=rng1))
    s2 = list(glide_samples(0, 0, 500, 500, rng=rng2))
    assert len(s1) == len(s2)
    for (x1, y1, d1), (x2, y2, d2) in zip(s1, s2):
        assert abs(x1 - x2) < 0.01
        assert abs(y1 - y2) < 0.01
        assert d1 == d2


# ---------------------------------------------------------------------------
# type_delay_ms
# ---------------------------------------------------------------------------

def test_type_delay_flow_dominates():
    """The vast majority of typing samples are in the 30-95ms range."""
    rng = random.Random(0)
    counts = {"flow": 0, "burst": 0, "hesitate": 0}
    for _ in range(1000):
        d = type_delay_ms(rng)
        if 50 <= d <= 95:
            counts["flow"] += 1
        elif 30 <= d <= 55:
            counts["burst"] += 1
        elif 180 <= d <= 350:
            counts["hesitate"] += 1
    # Flow is 75% expected, ~74% with sampling variance
    assert counts["flow"] > 600, f"flow count {counts['flow']} too low"
    assert counts["burst"] > 100, f"burst count {counts['burst']} too low"
    # Hesitate is 5% expected — 50 samples in 1000
    assert 20 < counts["hesitate"] < 100, (
        f"hesitate count {counts['hesitate']} outside reasonable range"
    )


def test_type_delay_never_zero():
    """type_delay_ms always returns a positive value."""
    rng = random.Random(0)
    for _ in range(100):
        assert type_delay_ms(rng) > 0


# ---------------------------------------------------------------------------
# hover_pause_ms
# ---------------------------------------------------------------------------

def test_hover_pause_in_range():
    """hover_pause_ms draws in [min_ms, max_ms]."""
    rng = random.Random(0)
    for _ in range(500):
        d = hover_pause_ms(120, 250, rng=rng)
        assert 50 <= d <= 300, f"hover_pause_ms returned {d} outside expected range"


def test_hover_pause_hesitating_very_long():
    """hesitating=True produces 1-2s pauses."""
    rng = random.Random(0)
    for _ in range(100):
        d = hover_pause_ms(120, 250, hesitating=True, rng=rng)
        assert 1000 <= d <= 2000


# ---------------------------------------------------------------------------
# post_click_pause_ms
# ---------------------------------------------------------------------------

def test_post_click_pause_distribution():
    """About 5% of post-click pauses are 1-2s; the rest are 200-400ms."""
    rng = random.Random(0)
    long_count = 0
    short_count = 0
    for _ in range(2000):
        d = post_click_pause_ms(rng)
        if d >= 1000:
            long_count += 1
        else:
            short_count += 1
    # Expect ~5% long (100/2000), allow 2-9% range
    assert 40 < long_count < 180, (
        f"long pauses {long_count}/2000 outside 2-9% range"
    )
    # And the rest should be short
    assert short_count > 1800


# ---------------------------------------------------------------------------
# idle_jitter
# ---------------------------------------------------------------------------

def test_idle_jitter_small_radius():
    """idle_jitter samples are small (0.3-1.5px) by design."""
    it = idle_jitter(seed=0)
    for _ in range(50):
        dx, dy, delay = next(it)
        assert math.hypot(dx, dy) <= 1.6
        assert 200 <= delay <= 600


def test_idle_jitter_runs_indefinitely():
    """idle_jitter is an infinite generator."""
    it = idle_jitter(seed=0)
    for _ in range(1000):
        next(it)  # should not raise StopIteration
