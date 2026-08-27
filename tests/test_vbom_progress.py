"""The VBOM workflow's progress contract.

A real run is minutes long, so both UIs drive a progress bar from the engine's
callback. These pin the contract the UIs rely on: monotonic fractions inside
0..1, a message with every step, and a callback that can never break the run.
"""

from __future__ import annotations

import inspect
import re

from splice.vbom.workflow import _Progress, run_vbom_workflow


class TestProgressHelper:
    def test_forwards_fraction_and_message(self):
        seen: list[tuple[float, str]] = []
        _Progress(lambda f, m: seen.append((f, m)))(0.5, "halfway")
        assert seen == [(0.5, "halfway")]

    def test_clamps_out_of_range_fractions(self):
        seen: list[tuple[float, str]] = []
        report = _Progress(lambda f, m: seen.append((f, m)))
        report(-2.0, "under")
        report(7.0, "over")
        assert [f for f, _ in seen] == [0.0, 1.0]

    def test_no_callback_is_a_no_op(self):
        assert _Progress(None)(0.5, "ignored") is None

    def test_callback_errors_never_break_the_workflow(self):
        # A dead browser session must not take the engine down with it.
        def explode(fraction, message):
            raise RuntimeError("client gone")

        _Progress(explode)(0.5, "still fine")

    def test_message_is_coerced_to_text(self):
        seen: list[tuple[float, str]] = []
        _Progress(lambda f, m: seen.append((f, m)))(0.1, 42)
        assert seen == [(0.1, "42")]


class TestWorkflowSignature:
    def test_progress_is_optional_and_keyword_only(self):
        sig = inspect.signature(run_vbom_workflow)
        param = sig.parameters["progress"]
        assert param.default is None
        assert param.kind is inspect.Parameter.KEYWORD_ONLY

    def test_reported_fractions_are_ordered_and_bounded(self):
        # Read the calibrated stage fractions straight from the source so a
        # future edit that reorders or overshoots them fails here.
        source = inspect.getsource(run_vbom_workflow)
        # Literal stage fractions only; the per-file loop computes its own
        # fraction, and is bounded by the literals on either side of it.
        fractions = [float(m) for m in
                     re.findall(r"^\s*report\((\d*\.?\d+),", source, re.M)]
        assert fractions, "the workflow reports no progress at all"
        assert fractions == sorted(fractions), f"stages go backwards: {fractions}"
        assert fractions[0] == 0.0 and fractions[-1] == 1.0
        assert all(0.0 <= f <= 1.0 for f in fractions)
