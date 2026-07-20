"""Performance scaling tests for claims processing (AAP-79732).

Background
----------
AAP-79732 fixed a critical bug where SAML/OIDC login took 60-120+ seconds
with 300+ authenticator maps. The root cause was _process_user_value()
evaluating every user attribute value against every map trigger in a nested
loop, producing O(n×m) iterations — each with a DEBUG log line costing ~5ms
of I/O in production.

The fix has two parts:
  1. "in" operator: replaced the per-value loop with a set intersection.
     Complexity went from O(n×m) to O(n+m), and logging from O(n) per map
     to O(1) per map (one summary line).
  2. Scalar operators (equals, contains, ends_with, matches): added early
     exit on first match (or join) / first mismatch (and join), so the loop
     stops as soon as the result is determined.

What these tests catch
----------------------
- A regression that reintroduces per-value iteration in the "in" operator.
- A regression that removes early exit from scalar operators.
- Any future change that adds hidden O(n) or O(n²) work (e.g. expensive
  per-value computation that doesn't emit log lines).

Why two metrics
---------------
Each test class uses two complementary metrics:

  Log line count (deterministic):
    Proves structural O(1) logging — the number of log lines emitted must
    not grow with input size. This is the primary signal: fully deterministic,
    never flaky, and directly tests the optimization's core invariant.

  Elapsed time ratio (empirical):
    Catches performance regressions that don't manifest as extra log lines —
    for example, an expensive computation added inside the loop that doesn't
    log. TESTING.md (§274-295) discourages absolute wall-clock thresholds
    because they are hardware-dependent and flaky on loaded CI runners.
    These tests use RELATIVE time ratios instead: run the same function at
    two scales and compare the ratio. A slow CI runner is slow for both
    measurements, so the ratio stays stable. This technique is consistent
    with the ratio approach described in TESTING.md and used in
    test_role_assignments_perf.py.
"""

import hashlib
import logging
import time

from ansible_base.authentication.utils import claims

_CLAIMS_LOGGER = 'ansible_base.authentication.utils.claims'

# Deterministic group names at two scales.
# 33 groups matches the scale observed in the production SAML responses that
# triggered AAP-79732. 330 groups is the 10x scale used for ratio comparison.
_GROUPS_33 = [f"group-{hashlib.sha256(f'seed-{i}'.encode()).hexdigest()[:16]}" for i in range(33)]
_GROUPS_330 = [f"group-{hashlib.sha256(f'seed-{i}'.encode()).hexdigest()[:16]}" for i in range(330)]

# Number of iterations per timing measurement to smooth out noise.
_TIMING_ITERATIONS = 500


def _count_log_records(caplog, func, *args, **kwargs):
    """Run func and return (result, log_record_count) for the claims logger."""
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=_CLAIMS_LOGGER):
        result = func(*args, **kwargs)
    count = len([r for r in caplog.records if r.name == _CLAIMS_LOGGER])
    return result, count


def _measure_time(func, *args, iterations=_TIMING_ITERATIONS, **kwargs):
    """Run func `iterations` times and return total elapsed seconds."""
    start = time.perf_counter()
    for _ in range(iterations):
        func(*args, **kwargs)
    return time.perf_counter() - start


class TestInOperatorScaling:
    """Verify the "in" operator evaluates in O(n+m) time with O(1) logging.

    The set-based implementation builds two sets (user values and trigger values)
    and intersects them. This is O(n+m) in the number of values — some linear
    scaling with input size is expected and acceptable. What we are guarding
    against is a regression to the OLD O(n×m) behavior where each user value
    was checked individually against the trigger list in a nested loop, with a
    per-iteration log line.

    Concretely, for 33 vs 330 user groups (10x increase):
      - O(n+m) (current): time scales ~7-8x, log count stays at 1
      - O(n×m) (regression): time scales ~100x, log count scales 10x
    """

    def _run_in(self, user_groups):
        tc = {'groups': {'in': ['nonexistent_trigger']}}
        return claims._process_user_value(None, tc, user_groups, 'or', 'groups', 1, 'perf')

    def test_log_count_constant_as_user_values_grow(self, caplog):
        """The "in" operator must emit exactly 1 summary log line per map
        evaluation, regardless of how many user values are checked.

        Before the fix, 33 groups produced 33 log lines per map, and 330
        groups produced 330 log lines — each costing ~5ms of I/O in
        production. The fix replaces this with a single summary line.
        """
        _, logs_33 = _count_log_records(caplog, self._run_in, _GROUPS_33)
        _, logs_330 = _count_log_records(caplog, self._run_in, _GROUPS_330)

        assert logs_33 == 1, f"Expected 1 log line for 33 groups, got {logs_33}"
        assert logs_330 == 1, f"Expected 1 log line for 330 groups, got {logs_330}"

    def test_elapsed_time_linear_as_user_values_grow(self):
        """Elapsed time must scale at most linearly (O(n+m)), not quadratically.

        The set-based "in" operator constructs two sets and intersects them,
        which is O(n+m). For a 10x increase in user values (33 → 330), we
        expect roughly linear time growth (~7-8x observed in practice due to
        set construction overhead, which is acceptable).

        What would FAIL this test: a regression to the old per-value loop
        where each of n user values was compared individually against m
        trigger values, producing O(n×m) iterations. With 10x more user
        values, the old code would scale 10x in iterations PLUS 10x in log
        I/O, easily exceeding the 10x threshold.

        The threshold of < 10.0x is deliberately generous to avoid CI flakiness
        while still catching quadratic regressions. Observed ratios are ~7-8x.
        """
        time_33 = _measure_time(self._run_in, _GROUPS_33)
        time_330 = _measure_time(self._run_in, _GROUPS_330)

        ratio = time_330 / max(time_33, 1e-9)
        assert ratio < 10.0, (
            f"Time scaled {ratio:.1f}x for 10x user values — expected <10.0x (at most linear). "
            f"Super-linear scaling suggests a regression to per-value iteration. "
            f"33 groups: {time_33:.4f}s, 330 groups: {time_330:.4f}s "
            f"({_TIMING_ITERATIONS} iterations each)"
        )


class TestScalarOperatorEarlyExitScaling:
    """Verify scalar operators exit early and don't scan values past the match.

    For operators like equals, contains, ends_with, and matches with an "or"
    join condition, the loop should break on the first matching value. This
    means the number of values AFTER the match point is irrelevant — a list
    of 10 values and a list of 100 values with the match at the same position
    should produce identical work.

    Concretely, with a match at position 3:
      - With early exit (current): evaluates exactly 4 values (0, 1, 2, 3)
      - Without early exit (regression): evaluates all 10 or all 100 values
    """

    def _make_values_with_match_at(self, match_position, total):
        """Build a value list where 'target' appears at match_position (0-indexed), rest are misses."""
        values = [f"miss-{i}" for i in range(total)]
        values[match_position] = "target"
        return values

    def _run_equals(self, values):
        tc = {'attr': {'equals': 'target'}}
        return claims._process_user_value(None, tc, values, 'or', 'attr', 1, 'perf')

    def test_log_count_constant_with_early_exit(self, caplog):
        """Log count must depend on match position, not total list length.

        With the match at position 3, exactly 4 values are evaluated (indices
        0, 1, 2, 3) producing 4 log lines — regardless of whether the list
        has 10 or 100 elements. The remaining elements are never touched.

        A regression that removes the early exit break would produce 10 log
        lines for the short list and 100 for the long list.
        """
        values_10 = self._make_values_with_match_at(3, 10)
        values_100 = self._make_values_with_match_at(3, 100)

        _, logs_10 = _count_log_records(caplog, self._run_equals, values_10)
        _, logs_100 = _count_log_records(caplog, self._run_equals, values_100)

        assert logs_10 == 4, f"Expected 4 log lines (match at pos 3) for 10 values, got {logs_10}"
        assert logs_100 == 4, f"Expected 4 log lines (match at pos 3) for 100 values, got {logs_100}"
        assert logs_10 == logs_100, f"Early exit should make log count independent of list size: 10 values={logs_10}, 100 values={logs_100}"

    def test_elapsed_time_constant_with_early_exit(self):
        """Elapsed time must not grow when values are added after the match point.

        With the match at position 3, the loop breaks after evaluating 4 values.
        Adding 90 more values after the match point (10 → 100 total) should
        have zero effect on execution time because those values are never reached.

        The threshold of < 2.0x is tight because this truly IS O(1) — the work
        done is identical regardless of list length. Any ratio above 2.0x would
        indicate the loop is not actually breaking on match.
        """
        values_10 = self._make_values_with_match_at(3, 10)
        values_100 = self._make_values_with_match_at(3, 100)

        time_10 = _measure_time(self._run_equals, values_10)
        time_100 = _measure_time(self._run_equals, values_100)

        ratio = time_100 / max(time_10, 1e-9)
        assert ratio < 2.0, (
            f"Time scaled {ratio:.1f}x for 10x list size — expected <2.0x with early exit at position 3. "
            f"The extra 90 values after the match should never be evaluated. "
            f"10 values: {time_10:.4f}s, 100 values: {time_100:.4f}s "
            f"({_TIMING_ITERATIONS} iterations each)"
        )
