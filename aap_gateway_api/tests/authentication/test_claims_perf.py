"""Performance scaling tests for claims processing (AAP-79732).

Background
----------
AAP-79732 fixed a critical bug where SAML/OIDC login took 60-120+ seconds
with 300+ authenticator maps. The root cause was _process_user_value()
evaluating every user attribute value against every map trigger in a nested
loop, producing O(n×m) iterations — each with a DEBUG log line that added
significant I/O overhead in production.

The fix has two parts:
  1. "in" operator: replaced the per-value loop with a set intersection.
     Complexity went from O(n×m) to O(n+m), and logging from O(n) per map
     to O(1) per map (one summary line).
  2. Scalar operators (equals, contains, ends_with, matches): added early
     exit on first match (or join) / first mismatch (and join), so the loop
     stops as soon as the result is determined.

What these tests catch
----------------------
- A regression that reintroduces per-value logging in the "in" operator.
- A regression that removes early exit from scalar operators (both or/and
  join conditions).
- Any future change that adds hidden expensive work (e.g. per-value
  computation that doesn't emit log lines).

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
    log. TESTING.md's "Performance Tests (Perf)" section recommends relative
    comparison at two scales for query counts and memory; these tests extend
    that same ratio technique to elapsed time. By comparing ratios rather
    than absolute thresholds, the measurements stay hardware-independent —
    a slow CI runner is slow for both scales, so the ratio is stable.
"""

import hashlib
import logging
import time

import pytest
from ansible_base.authentication.utils import claims

_CLAIMS_LOGGER = 'ansible_base.authentication.utils.claims'

# Deterministic group names at two scales.
# 33 groups matches the scale observed in the production SAML responses that
# triggered AAP-79732. 330 groups is the 10x scale used for ratio comparison.
# In production, each authenticator map typically has a single trigger value
# (one SAML group name), so the trigger list uses m=1 to mirror that scenario.
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
    """Verify the "in" operator evaluates with O(1) logging per map.

    The set-based implementation builds two sets and intersects them. The
    computation is O(n+m), so some linear time scaling with input size is
    expected. The critical invariant is that logging is O(1) per evaluation
    (one summary line), not O(n) per user value as in the old code.

    The trigger list uses m=1 to match the production scenario where each
    authenticator map checks membership in a single SAML/OIDC group. With
    m=1, the timing test catches regressions worse than O(n) (e.g. accidental
    O(n²) sorting or per-value overhead) but cannot distinguish O(n×m) from
    O(n+m) — the log-count test is the primary guard for that.
    """

    def _run_in(self, user_groups):
        tc = {'groups': {'in': ['nonexistent_trigger']}}
        return claims._process_user_value(None, tc, user_groups, 'or', 'groups', 1, 'perf')

    def test_log_count_constant_as_user_values_grow(self, caplog):
        """O(1) logging: exactly 1 summary log line regardless of user value count.

        See module docstring for background on the per-value logging regression
        this test guards against.
        """
        result_33, logs_33 = _count_log_records(caplog, self._run_in, _GROUPS_33)
        result_330, logs_330 = _count_log_records(caplog, self._run_in, _GROUPS_330)

        assert result_33 is False
        assert result_330 is False
        assert logs_33 == 1, f"Expected 1 log line for 33 groups, got {logs_33}"
        assert logs_330 == 1, f"Expected 1 log line for 330 groups, got {logs_330}"

    @pytest.mark.parametrize("user_groups", [_GROUPS_33, _GROUPS_330], ids=["33_groups", "330_groups"])
    def test_log_count_constant_with_matching_trigger(self, caplog, user_groups):
        """O(1) logging holds on the match path, not just the miss path.

        The base test uses a nonexistent trigger (no intersection). This test
        places a trigger that IS present in the user groups, exercising the
        set-intersection hit-path which may have different logging behavior.
        """
        tc = {'groups': {'in': [user_groups[0]]}}
        result, logs = _count_log_records(caplog, claims._process_user_value, None, tc, user_groups, 'or', 'groups', 1, 'perf')

        assert result is True, "Expected True when trigger matches a user group"
        assert logs == 1, f"Expected 1 log line on match path for {len(user_groups)} groups, got {logs}"

    def test_elapsed_time_linear_as_user_values_grow(self):
        """Time must scale at most linearly with user value count.

        The set construction is O(n), so linear growth is expected. The
        threshold of < 10.0x for a 10x input increase is deliberately generous
        to avoid CI flakiness while catching super-linear regressions (e.g.
        per-value overhead reintroduced inside the loop).
        """
        time_33 = _measure_time(self._run_in, _GROUPS_33)
        time_330 = _measure_time(self._run_in, _GROUPS_330)

        ratio = time_330 / max(time_33, 1e-9)
        assert ratio < 10.0, (
            f"Time scaled {ratio:.1f}x for 10x user values — expected <10.0x (at most linear). "
            f"Super-linear scaling suggests per-value overhead was reintroduced. "
            f"33 groups: {time_33:.4f}s, 330 groups: {time_330:.4f}s "
            f"({_TIMING_ITERATIONS} iterations each)"
        )


# Parametrized data for scalar operator early-exit tests.
# Each tuple: (operator_key, trigger_value, matching_user_value)
# The matching value is placed at position 3 in the value list; all other
# values are non-matching "miss-N" strings that don't satisfy any operator.
_SCALAR_OPERATOR_CASES = [
    ("equals", "target", "target"),
    ("contains", "target", "has-target-inside"),
    ("ends_with", "@target.com", "user@target.com"),
    ("matches", r"^admin-.*", "admin-group-1"),
]


class TestScalarOperatorEarlyExitScaling:
    """Verify scalar operators exit early and don't scan values past the decision point.

    With an "or" join, the loop should break on the first matching value.
    With an "and" join, the loop should break on the first mismatching value.
    In both cases, the number of values after the decision point is irrelevant.

    See module docstring for background on the early-exit optimization.
    """

    @pytest.mark.parametrize(
        "operator,trigger_value,matching_value",
        _SCALAR_OPERATOR_CASES,
        ids=[c[0] for c in _SCALAR_OPERATOR_CASES],
    )
    def test_log_count_constant_or_join(self, caplog, operator, trigger_value, matching_value):
        """With or join, log count depends on match position, not list length.

        The match is placed at position 3. With early exit, exactly 4 values
        are evaluated (indices 0, 1, 2, 3) regardless of total list size.
        """
        for total in (10, 100):
            values = [f"miss-{i}" for i in range(total)]
            values[3] = matching_value
            tc = {'attr': {operator: trigger_value}}

            result, logs = _count_log_records(caplog, claims._process_user_value, None, tc, values, 'or', 'attr', 1, 'perf')

            assert result is True, f"{operator}: expected True for {total} values"
            assert logs == 4, f"{operator}: expected 4 log lines (match at pos 3) for {total} values, got {logs}"

    def test_log_count_constant_and_join(self, caplog):
        """With and join, log count depends on mismatch position, not list length.

        All values are "target" except at position 3. With early exit on first
        mismatch, exactly 4 values are evaluated regardless of total list size.
        """
        for total in (10, 100):
            values = ["target"] * total
            values[3] = "miss"
            tc = {'attr': {'equals': 'target'}}

            result, logs = _count_log_records(caplog, claims._process_user_value, None, tc, values, 'and', 'attr', 1, 'perf')

            assert result is False, f"Expected False for {total} values"
            assert logs == 4, f"Expected 4 log lines (mismatch at pos 3) for {total} values, got {logs}"

    @pytest.mark.parametrize(
        "operator,trigger_value,matching_value",
        _SCALAR_OPERATOR_CASES,
        ids=[c[0] for c in _SCALAR_OPERATOR_CASES],
    )
    def test_log_count_full_scan_or_join_no_match(self, caplog, operator, trigger_value, matching_value):
        """With or join and NO match, all values are scanned — log count = total.

        Contrasts with test_log_count_constant_or_join: without this test,
        the assertion `logs == 4` could be right for the wrong reason (e.g.
        the function always logs exactly 4 lines). This test proves the
        early-exit test is actually testing early exit.
        """
        for total in (10, 100):
            values = [f"miss-{i}" for i in range(total)]
            tc = {'attr': {operator: trigger_value}}

            result, logs = _count_log_records(caplog, claims._process_user_value, None, tc, values, 'or', 'attr', 1, 'perf')

            assert result is False, f"{operator}: expected False with no matching values for {total} values"
            assert logs == total, f"{operator}: expected {total} log lines (full scan, no match), got {logs}"

    @pytest.mark.parametrize(
        "operator,trigger_value,matching_value",
        _SCALAR_OPERATOR_CASES,
        ids=[c[0] for c in _SCALAR_OPERATOR_CASES],
    )
    def test_log_count_early_exit_at_position_0(self, caplog, operator, trigger_value, matching_value):
        """With or join and match at position 0, exactly 1 log line.

        Verifies the break happens on the very first iteration — the earliest
        possible early exit.
        """
        values = [matching_value] + [f"miss-{i}" for i in range(99)]
        tc = {'attr': {operator: trigger_value}}

        result, logs = _count_log_records(caplog, claims._process_user_value, None, tc, values, 'or', 'attr', 1, 'perf')

        assert result is True, f"{operator}: expected True with match at position 0"
        assert logs == 1, f"{operator}: expected 1 log line (match at pos 0), got {logs}"

    def test_log_count_full_scan_and_join_all_match(self, caplog):
        """With and join where ALL values match, every value is scanned.

        Contrasts with test_log_count_constant_and_join: that test verifies
        early exit on mismatch. This test verifies the full-scan path when
        no early exit is possible (all values satisfy the condition).
        """
        for total in (10, 100):
            values = ["target"] * total
            tc = {'attr': {'equals': 'target'}}

            result, logs = _count_log_records(caplog, claims._process_user_value, None, tc, values, 'and', 'attr', 1, 'perf')

            assert result is True, f"Expected True when all {total} values match"
            assert logs == total, f"Expected {total} log lines (all match, full scan), got {logs}"

    def test_empty_user_values(self, caplog):
        """Empty user values list: no crash, no log lines, has_access unchanged."""
        tc = {'attr': {'equals': 'target'}}

        result, logs = _count_log_records(caplog, claims._process_user_value, None, tc, [], 'or', 'attr', 1, 'perf')

        assert result is None, "Expected None (has_access unchanged) for empty values"
        assert logs == 0, f"Expected 0 log lines for empty values, got {logs}"

    def test_elapsed_time_constant_or_join(self):
        """With or join and early exit, trailing values should not affect time.

        Uses the equals operator as a representative case. The threshold of
        < 2.0x is tight because with early exit the work is identical
        regardless of list length.
        """
        values_10 = [f"miss-{i}" for i in range(10)]
        values_10[3] = "target"
        values_100 = [f"miss-{i}" for i in range(100)]
        values_100[3] = "target"

        def run(values):
            tc = {'attr': {'equals': 'target'}}
            return claims._process_user_value(None, tc, values, 'or', 'attr', 1, 'perf')

        time_10 = _measure_time(run, values_10)
        time_100 = _measure_time(run, values_100)

        ratio = time_100 / max(time_10, 1e-9)
        assert ratio < 2.0, (
            f"Time scaled {ratio:.1f}x for 10x list size — expected <2.0x with early exit at position 3. "
            f"10 values: {time_10:.4f}s, 100 values: {time_100:.4f}s "
            f"({_TIMING_ITERATIONS} iterations each)"
        )

    def test_elapsed_time_constant_and_join(self):
        """With and join and early exit on mismatch, trailing values should not affect time.

        Complements test_elapsed_time_constant_or_join: the log count tests
        cover the and join structurally, but a timing test catches non-logging
        regressions (expensive computation that doesn't emit log lines).
        """
        values_10 = ["target"] * 10
        values_10[3] = "miss"
        values_100 = ["target"] * 100
        values_100[3] = "miss"

        def run(values):
            tc = {'attr': {'equals': 'target'}}
            return claims._process_user_value(None, tc, values, 'and', 'attr', 1, 'perf')

        time_10 = _measure_time(run, values_10)
        time_100 = _measure_time(run, values_100)

        ratio = time_100 / max(time_10, 1e-9)
        assert ratio < 2.0, (
            f"Time scaled {ratio:.1f}x for 10x list size — expected <2.0x with early exit at position 3. "
            f"10 values: {time_10:.4f}s, 100 values: {time_100:.4f}s "
            f"({_TIMING_ITERATIONS} iterations each)"
        )
