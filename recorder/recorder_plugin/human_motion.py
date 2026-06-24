"""v0.3.11: humanized motion randomizers for cursor + typing.

This module holds the random-distribution helpers that make recorded
video motion look like a real person instead of a script. The math
comes from observing actual mouse trajectories and typing cadences:

  - Real mouse moves along a CURVE (not a straight line) because the
    hand's pivot isn't the screen. A bezier control point offset
    perpendicular to the start-end vector reproduces this. Distance
    determines how much curvature.
  - Real mouse motion DECELERATES into the target. The path's main
    mass is in the middle of the move; the last 15-20% is a
    "settle" phase with smaller steps and shorter delays. This is
    the "hand physics" of real cursor use — a constant-velocity
    glide reads as robotic.
  - Real cursors sometimes OVERSHOOT the target by 1-4 pixels then
    correct. Because the bezier curve doesn't reach the target
    until t=1.0, the overshoot is applied as a small sinusoidal
    bump in the t=0.85-0.98 range, then a recovery oscillation
    in t=0.98-1.0 lands the cursor ON the target.
  - Real typing has BURSTS and PAUSES. A character isn't typed at a
    fixed cadence; the user sometimes hits a key, glances at the
    result, then types the next one (300-400ms gap) vs other times
    types in a flow (50-80ms per char). We model this as 75% "flow"
    and 25% "burst" with 0-2 "hesitate" pauses.
  - Real people HOVER before clicking. 120-250ms is short, 300-700ms
    is a "double-checking" hover, and ~1.5% of clicks have a 1-2s
    "wait, I need to read this" pause before committing.

These are deliberately small, cheap functions — they just sample
from distributions. The actual glide execution lives in script.py
because it needs to call `rec.page.mouse.move`. This module
provides the SAMPLES.

API:
  glide_samples(sx, sy, cx, cy) -> Iterator[(x, y, delay_ms)]
      Generator yielding intermediate (x, y) positions and per-step
      delays for a mouse glide from (sx, sy) to (cx, cy). Iterating
      fully produces the whole trajectory.

  type_delay_ms() -> int
      Returns the per-character typing delay in ms, drawn from a
      mixture distribution (flow + burst + occasional hesitate).

  hover_pause_ms(min_ms, max_ms, *, hesitating=False) -> int
      Returns a hover dwell time in ms. When hesitating=True, draws
      from a much wider distribution (1-2s, ~1.5% chance).

  post_click_pause_ms() -> int
      Returns the "look at the result" pause after a click. Most are
      short (200-400ms) but ~5% are long (1-2s) — the user is
      reading a confirmation modal or similar.

Usage from script.py:
    from recorder_plugin.human_motion import (
        glide_samples, type_delay_ms, hover_pause_ms, post_click_pause_ms,
    )

    for x, y, delay in glide_samples(sx, sy, cx, cy):
        await page.mouse.move(x, y)
        await page.wait_for_timeout(delay)
    await page.wait_for_timeout(hover_pause_ms(120, 250))
    await page.mouse.click(cx, cy)
    await page.wait_for_timeout(post_click_pause_ms())
"""
from __future__ import annotations
import math
import random
from typing import Iterator, Tuple


# ---------------------------------------------------------------------------
# Mouse glide: bezier curve + overshoot + per-step delay jitter
# ---------------------------------------------------------------------------

def _bezier_point(
    t: float, p0: Tuple[float, float], p1: Tuple[float, float], p2: Tuple[float, float]
) -> Tuple[float, float]:
    """Quadratic bezier: p0 is start, p2 is end, p1 is the control point.

    Real mouse trajectories are not straight — the hand pivots at the
    wrist/elbow so the path curves. We model this with a single
    quadratic bezier where p1 is offset perpendicular to the start-end
    vector, scaled by distance.
    """
    x = (1 - t) * (1 - t) * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0]
    y = (1 - t) * (1 - t) * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]
    return x, y


def _perpendicular_offset(sx: float, sy: float, cx: float, cy: float) -> Tuple[float, float]:
    """Return a unit vector perpendicular to (start -> end).

    Used as the direction to offset the bezier control point so the
    curve bows to one side. The SIGN is randomized in glide_samples
    so successive glides bow left or right unpredictably.
    """
    dx = cx - sx
    dy = cy - sy
    length = math.hypot(dx, dy) or 1.0
    # 90° rotation: (dx, dy) -> (-dy, dx) for one side,
    # (dy, -dx) for the other. We return the first; caller picks sign.
    return -dy / length, dx / length


def _overshoot_factor(t: float) -> float:
    """Map glide progress 0..1 to a position offset that overshoots
    the target then settles.

    The bezier curve naturally reaches (cx, cy) at t=1.0. We add a
    small sinusoidal bump in the t=0.85-0.98 range so the cursor
    briefly goes past the target by 1-4px, then a recovery oscillation
    in t=0.98-1.0 brings it back. This is the "hand physics" of
    real cursor use — momentum carries the cursor slightly past
    where the user intended, then the hand corrects.

    The amplitude is small (max ~4px on a 1000px move) so it
    doesn't look like the cursor is glitching — it just looks like
    the user wasn't 100% precise.
    """
    if t < 0.85:
        return 0.0
    elif t < 0.98:
        # Sinusoidal bump: 0 -> 1 -> 0 across (0.85, 0.98)
        # Peak at t=0.915, in the middle of the bump range
        local = (t - 0.85) / 0.13  # 0..1
        return math.sin(local * math.pi)
    elif t < 1.0:
        # Recovery: cosine from 1 down to 0 across (0.98, 1.0)
        local = (t - 0.98) / 0.02  # 0..1
        return math.cos(local * math.pi / 2)
    else:
        return 0.0


def _step_count(distance: float, *, rng: random.Random | None = None) -> int:
    """Number of intermediate positions for a glide of `distance` px.

    Real mouse moves aren't 8 steps for a 50px move and 18 steps for
    a 500px move. The eye reads step count as "smoothness": too few
    steps looks teleporty, too many looks like a screensaver.

    Tuned by feel:
      - <60px (small move, e.g. between adjacent form fields): 6-10 steps
      - 60-200px (medium, e.g. sidebar nav): 10-16 steps
      - 200-500px (long, e.g. cross-page): 16-24 steps
      - 500+px (huge, e.g. across screen): 22-32 steps
    """
    rng = rng or random
    if distance < 60:
        return rng.randint(6, 10)
    elif distance < 200:
        return rng.randint(10, 16)
    elif distance < 500:
        return rng.randint(16, 24)
    else:
        return rng.randint(22, 32)


def _per_step_delay(distance: float, *, rng: random.Random | None = None) -> Tuple[int, int, int]:
    """Per-step delay in ms (initial, peak, final).

    Real mouse moves start fast (high initial velocity) and decelerate
    toward the target. The eye reads constant per-step delay as
    "robotic". A triangular distribution (more weight at the start
    and end, less in the middle) approximates this.

    Returns (initial_ms, peak_ms, final_ms) — applied across the
    glide as a trapezoid. See glide_samples() for usage.
    """
    rng = rng or random
    if distance < 60:
        initial = rng.randint(6, 10)
        peak = rng.randint(4, 7)
        final = rng.randint(8, 14)
    elif distance < 200:
        initial = rng.randint(8, 12)
        peak = rng.randint(5, 9)
        final = rng.randint(10, 18)
    elif distance < 500:
        initial = rng.randint(10, 16)
        peak = rng.randint(6, 10)
        final = rng.randint(14, 22)
    else:
        initial = rng.randint(12, 18)
        peak = rng.randint(7, 11)
        final = rng.randint(16, 26)
    return initial, peak, final


def glide_samples(
    sx: float, sy: float, cx: float, cy: float, *, rng: random.Random | None = None
) -> Iterator[Tuple[float, float, int]]:
    """Yield (x, y, delay_ms) for a humanized mouse glide from (sx,sy) to (cx,cy).

    The trajectory is a quadratic bezier curve (not a straight line),
    with a perpendicular bow whose direction is randomized left/right.
    Near the end the path overshoots by 1-4px and recovers — this is
    the "hand physics" of real cursor use.

    Per-step delays are NOT constant: they follow a trapezoid
    (start fast, slow down, pause at the end) which reads as
    "decelerating into the target" rather than "constant speed".

    Args:
        sx, sy: start position (previous mouse position).
        cx, cy: end position (target center).
        rng: optional random.Random instance for determinism in tests.

    Yields:
        Tuples of (x, y, delay_ms). The cursor should be moved to
        (x, y) and then wait for `delay_ms` before the next move.
        The trajectory is generated fully upfront (this is a
        generator, not a streaming computation).
    """
    rng = rng or random
    dx = cx - sx
    dy = cy - sy
    distance = math.hypot(dx, dy)

    # Trivial case: don't bother with a curve.
    if distance < 2:
        yield (cx, cy, 16)
        return

    n = _step_count(distance, rng=rng)
    initial_ms, peak_ms, final_ms = _per_step_delay(distance, rng=rng)

    # Bezier control point: perpendicular bow.
    # Magnitude scales with distance (real hand deflection is larger
    # for longer moves), capped so a 1000px move doesn't bow 200px.
    perp_x, perp_y = _perpendicular_offset(sx, sy, cx, cy)
    bow_magnitude = min(distance * 0.18, 60.0)
    bow_sign = 1 if rng.random() < 0.5 else -1
    ctrl_x = (sx + cx) / 2 + perp_x * bow_magnitude * bow_sign
    ctrl_y = (sy + cy) / 2 + perp_y * bow_magnitude * bow_sign

    # Add a small wobble in the bow direction (humans don't make
    # perfect parabolas).
    ctrl_x += rng.uniform(-bow_magnitude * 0.15, bow_magnitude * 0.15)
    ctrl_y += rng.uniform(-bow_magnitude * 0.15, bow_magnitude * 0.15)

    # Overshoot direction: along the start->end vector.
    overshoot_dx = dx / distance
    overshoot_dy = dy / distance
    # Magnitude: 0-3px scaled with distance. Cap at 4.5px so it's
    # a wobble, not a glitch.
    overshoot_px = min(distance * 0.012, 4.5) * (0.5 + rng.random())

    for i in range(1, n + 1):
        t = i / n
        # Base bezier point
        bx, by = _bezier_point(t, (sx, sy), (ctrl_x, ctrl_y), (cx, cy))
        # Add overshoot near the end of the trajectory
        ov = _overshoot_factor(t)
        if ov > 0:
            bx += overshoot_dx * overshoot_px * ov
            by += overshoot_dy * overshoot_px * ov
        # Per-step position jitter (sub-pixel wobble).
        bx += rng.uniform(-1.2, 1.2)
        by += rng.uniform(-1.2, 1.2)
        # Per-step delay: trapezoid. Phase 1 (start): initial_ms,
        # middle: peak_ms, phase 2 (last 20%): final_ms.
        if t < 0.2:
            delay = initial_ms
        elif t < 0.8:
            delay = peak_ms
        else:
            delay = final_ms
        # Sub-step jitter on delay
        delay += rng.randint(-2, 2)
        delay = max(3, delay)
        yield (bx, by, delay)


# ---------------------------------------------------------------------------
# Typing: flow + burst + occasional hesitate
# ---------------------------------------------------------------------------

# We model typing as a MIXTURE of three modes:
#   1. FLOW (75%): 50-95ms per char, jittered — the user is in a
#      typing groove.
#   2. BURST (20%): 30-55ms per char — the user is typing a familiar
#      word quickly.
#   3. HESITATE (5%): 180-350ms — the user paused, maybe to glance
#      at the result, then resumed.

_TYPE_MODES = [
    ("flow", 0.75, 50, 95),
    ("burst", 0.20, 30, 55),
    ("hesitate", 0.05, 180, 350),
]


def type_delay_ms(rng: random.Random | None = None) -> int:
    """Return a per-character typing delay in ms, drawn from a mixture.

    The caller should call this once per character typed; the
    distribution is independent across calls (no memory of the
    previous mode), so the cadence reads as "varied" rather than
    "alternating fast/slow in a fixed pattern".
    """
    rng = rng or random
    r = rng.random()
    cumulative = 0.0
    for mode_name, weight, lo, hi in _TYPE_MODES:
        cumulative += weight
        if r < cumulative:
            return rng.randint(lo, hi)
    # Fallback (shouldn't hit given the weights sum to 1.0).
    return rng.randint(60, 100)


# ---------------------------------------------------------------------------
# Hover + post-click pauses
# ---------------------------------------------------------------------------

def hover_pause_ms(
    min_ms: int, max_ms: int, *, hesitating: bool = False, rng: random.Random | None = None
) -> int:
    """Return a hover dwell time in ms.

    Args:
        min_ms, max_ms: the normal range. e.g. (120, 250) for a
            brief hover before clicking.
        hesitating: if True, draws from a much wider distribution
            (1.0-2.0s) — the "wait, I need to check this" pause
            that happens ~1.5% of the time on real cursors.
        rng: optional random instance.
    """
    rng = rng or random
    if hesitating:
        return rng.randint(1000, 2000)
    # Use a triangular distribution — middle values are more likely
    # than the extremes. This produces "the typical hover is right
    # in the middle of the range" rather than "uniformly distributed
    # which feels evenly random".
    lo, hi = min_ms, max_ms
    mid = (lo + hi) / 2
    span = (hi - lo) / 2
    # Triangular: pick 0..1 then bias toward 0.5.
    u = rng.random()
    # Beta-like: avg of two uniforms
    t = (u + rng.random()) / 2.0
    return int(mid + (t * 2 - 1) * span * 0.7)


def post_click_pause_ms(rng: random.Random | None = None) -> int:
    """Return the "look at the result" pause after a click.

    Most clicks are followed by a 200-400ms glance. But ~5% of the
    time the user looks longer (1-2s) — they're reading a modal,
    verifying a state change, or thinking about the next step.

    Args:
        rng: optional random instance.
    """
    rng = rng or random
    # 95% short glance, 5% long think.
    if rng.random() < 0.05:
        return rng.randint(1000, 2000)
    # Triangular in 200-400ms range.
    return hover_pause_ms(200, 400, rng=rng)


# ---------------------------------------------------------------------------
# Idle micro-movement: when the cursor sits still, give it subtle drift
# ---------------------------------------------------------------------------

def idle_jitter(seed: int = 0) -> Iterator[Tuple[float, float, int]]:
    """Yield small (dx, dy, delay_ms) jitter samples for an idle cursor.

    When the cursor is stationary (between actions, or during a long
    wait_for), real users' hands don't sit perfectly still — the cursor
    drifts by 0.3-1.5px in random directions every 200-600ms. This
    generator yields a stream of those micro-movements. The script
    can call this in a background task while wait_for is running.

    The samples are absolute DELTAS, not absolute positions. Callers
    add them to the current cursor position.
    """
    rng = random.Random(seed)
    while True:
        # Drift in a small radius
        angle = rng.uniform(0, 2 * math.pi)
        radius = rng.uniform(0.3, 1.5)
        dx = math.cos(angle) * radius
        dy = math.sin(angle) * radius
        delay = rng.randint(200, 600)
        yield dx, dy, delay
