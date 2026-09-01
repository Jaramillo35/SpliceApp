"""Integrity of the DTx Sales Code column.

The reason this matters: a malformed expression does not fail loudly. The
evaluator reads "AAA-BBB" as one atom no vehicle carries, so the expression is
false for every configuration and its circuits read as *never built* —
indistinguishable from a real defect. These tests pin both the detection and
the fact that the suggested repair actually changes that outcome.
"""

from __future__ import annotations

import dataclasses

import pytest

from splice.dtxcircuits import integrity
from splice.dtxcircuits.models import CircuitRow
from splice.inline import salescode


class TestTheProblemItself:
    def test_a_missing_operator_is_false_for_every_configuration(self):
        # this is why the check exists
        assert all(not salescode.evaluate("AAA-BBB", set(c))
                   for c in ([], ["AAA"], ["BBB"], ["AAA", "BBB"]))

    def test_the_repair_restores_the_intended_meaning(self):
        assert salescode.evaluate("AAA&-BBB", {"AAA"}) is True
        assert salescode.evaluate("AAA&-BBB", {"AAA", "BBB"}) is False


class TestCheck:
    def test_sound_expressions_pass(self):
        for expression in ("AAA", "AAA/BBB", "AAA&-BBB", "AAA&(BBB/CCC)",
                           "501/JKP", ""):
            assert integrity.check(expression) is None, expression

    def test_dash_without_a_connector_is_caught(self):
        issue = integrity.check("AAA-BBB")
        assert issue.kind == integrity.MISSING_OPERATOR
        assert "never built" in issue.detail

    def test_dash_repair_is_suggested_first(self):
        issue = integrity.check("AAA-BBB")
        assert issue.suggestions[0].expression == "AAA&-BBB"

    def test_a_comma_suggests_or_first(self):
        issue = integrity.check("AAA,BBB")
        assert issue.suggestions[0].expression == "AAA/BBB"

    def test_a_plus_suggests_and_first(self):
        # '+' is AND in the complexity workbooks
        issue = integrity.check("AAA+BBB")
        assert issue.suggestions[0].expression == "AAA&BBB"

    def test_a_bare_space_offers_both_readings(self):
        issue = integrity.check("AAA BBB")
        assert [s.expression for s in issue.suggestions] == ["AAA&BBB", "AAA/BBB"]
        assert not issue.confident, "the SE must choose; only they know"

    def test_adjacent_groups_are_caught(self):
        issue = integrity.check("(AAA)(BBB)")
        assert issue.kind == integrity.MISSING_OPERATOR
        assert "(AAA)&(BBB)" in [s.expression for s in issue.suggestions]

    def test_every_suggestion_parses_and_is_satisfiable(self):
        for expression in ("AAA-BBB", "AAA BBB", "AAA+BBB", "AAA,BBB"):
            for suggestion in integrity.check(expression).suggestions:
                assert salescode.is_valid(suggestion.expression)
                assert integrity.satisfiable(suggestion.expression) is True

    def test_unbalanced_parentheses_are_reported_not_repaired(self):
        issue = integrity.check("((AAA)")
        assert issue.kind == integrity.UNBALANCED and not issue.suggestions

    def test_a_contradiction_is_reported(self):
        issue = integrity.check("AAA&-AAA")
        assert issue.kind == integrity.UNSATISFIABLE

    def test_grouping_punctuation_is_not_a_missing_operator(self):
        assert integrity.check("(AAA/BBB)&CCC") is None
        assert integrity.check("-(AAA/BBB)") is None


class TestSatisfiable:
    def test_a_normal_expression_is_satisfiable(self):
        assert integrity.satisfiable("AAA&-BBB") is True

    def test_a_contradiction_is_not(self):
        assert integrity.satisfiable("AAA&-AAA") is False

    def test_too_many_codes_is_declined_rather_than_guessed(self):
        many = "/".join(f"C{n:02d}" for n in range(integrity.MAX_CODES + 2))
        assert integrity.satisfiable(many) is None

    def test_no_codes_is_declined(self):
        assert integrity.satisfiable("") is None


class TestScan:
    def _rows(self):
        return [
            CircuitRow("IP", "CKT_1", "AAA-BBB", cnum="C1"),
            CircuitRow("IP", "CKT_2", "AAA-BBB", cnum="C1"),
            CircuitRow("DASH", "CKT_3", "AAA-BBB", cnum="C2"),
            CircuitRow("IP", "CKT_4", "AAA/BBB", cnum="C1"),
            CircuitRow("IP", "CKT_5", "", cnum="C1"),
            CircuitRow("IP", "CKT_6", "CCC,DDD", cnum="C3"),
        ]

    def test_one_bad_expression_is_one_decision_not_one_per_row(self):
        issues = {i.expression: i for i in integrity.scan(self._rows())}
        assert set(issues) == {"AAA-BBB", "CCC,DDD"}
        assert issues["AAA-BBB"].rows == 3

    def test_the_affected_circuits_and_families_are_listed(self):
        issue = {i.expression: i for i in integrity.scan(self._rows())}["AAA-BBB"]
        assert issue.circuits == ["CKT_1", "CKT_2", "CKT_3"]
        assert issue.families == ["DASH", "IP"]

    def test_sound_and_empty_expressions_are_not_reported(self):
        expressions = {i.expression for i in integrity.scan(self._rows())}
        assert "AAA/BBB" not in expressions and "" not in expressions

    def test_the_most_used_problem_comes_first(self):
        issues = integrity.scan(self._rows())
        assert issues[0].expression == "AAA-BBB"

    def test_a_clean_dtx_yields_nothing(self):
        assert integrity.scan([CircuitRow("IP", "C", "AAA/BBB")]) == []


class TestApplyFixes:
    def _rows(self):
        return [CircuitRow("IP", "CKT_1", "AAA-BBB"),
                CircuitRow("IP", "CKT_2", "AAA/BBB"),
                CircuitRow("IP", "CKT_3", "")]

    def test_only_the_fixed_expression_is_rewritten(self):
        out = integrity.apply_fixes(self._rows(), {"AAA-BBB": "AAA&-BBB"})
        assert [r.sales_code for r in out] == ["AAA&-BBB", "AAA/BBB", ""]

    def test_the_original_rows_are_never_mutated(self):
        rows = self._rows()
        integrity.apply_fixes(rows, {"AAA-BBB": "AAA&-BBB"})
        assert rows[0].sales_code == "AAA-BBB", "the DTx as received must stand"

    def test_no_fixes_returns_equivalent_rows(self):
        rows = self._rows()
        assert [r.sales_code for r in integrity.apply_fixes(rows, {})] == \
            [r.sales_code for r in rows]

    def test_a_fix_changes_the_verdict_downstream(self):
        # the whole point: before the repair the circuit can never be built
        from splice.dtxcircuits import analyze_harness
        from splice.inline.model import Build, Harness
        harness = Harness(name="IP", def_id="1",
                          builds=[Build("PN1", codes=frozenset({"AAA"}))],
                          complexity_codes={"AAA", "BBB"})
        rows = [CircuitRow("IP", "CKT_1", "AAA-BBB")]
        before = analyze_harness(rows, harness, harness_name="IP")
        after = analyze_harness(integrity.apply_fixes(rows, {"AAA-BBB": "AAA&-BBB"}),
                                harness, harness_name="IP")
        assert before.circuits[0].classification == "never built"
        assert after.circuits[0].classification == "unconditional" or \
            after.circuits[0].classification == "all builds"


class TestDanglingOperator:
    """An operator with no operand does not fail — it silently drops a term."""

    def test_a_trailing_and_is_caught(self):
        issue = integrity.check("QB1&")
        assert issue.kind == integrity.DANGLING_OPERATOR

    def test_a_trailing_not_is_caught(self):
        # "QB1&-" evaluates as plain QB1: the negated operand vanishes
        assert salescode.evaluate("QB1&-", {"QB1"}) is True
        assert integrity.check("QB1&-").kind == integrity.DANGLING_OPERATOR

    def test_doubled_operators_are_caught(self):
        assert integrity.check("QB1&&QA1").kind == integrity.DANGLING_OPERATOR
        assert integrity.check("QB1//QA1").kind == integrity.DANGLING_OPERATOR

    def test_a_leading_and_is_caught(self):
        assert integrity.check("&QB1").kind == integrity.DANGLING_OPERATOR

    def test_the_known_leading_slash_quirk_is_not_flagged(self):
        # "(/AAA/BBB)" appears in real exports and is harmless: an empty OR
        # operand is false, so it reads as AAA/BBB. Flagging it would be noise.
        assert integrity.check("(/AAA/BBB)") is None
        assert salescode.evaluate("(/AAA/BBB)", {"AAA"}) is True


class TestValidateReplacement:
    def test_a_good_repair_passes_clean(self):
        assert integrity.validate_replacement("AAA-BBB", "AAA&-BBB") == ([], [])

    def test_an_empty_replacement_is_blocked(self):
        blocking, _ = integrity.validate_replacement("AAA-BBB", "   ")
        assert blocking and "Type an expression" in blocking[0]

    def test_a_replacement_that_is_still_malformed_is_blocked(self):
        blocking, _ = integrity.validate_replacement("AAA-BBB", "AAA&(BBB")
        assert any("unbalanced" in b for b in blocking)

    def test_a_dangling_replacement_is_blocked(self):
        blocking, _ = integrity.validate_replacement("AAA-BBB", "AAA&-")
        assert any("dangling" in b for b in blocking)

    def test_a_never_true_replacement_is_blocked(self):
        blocking, _ = integrity.validate_replacement("AAA-BBB", "AAA&-AAA")
        assert blocking

    def test_a_mistyped_code_is_warned_about_not_blocked(self):
        # only the SE can know whether a different code is deliberate
        blocking, warnings = integrity.validate_replacement("AAA-BBB", "ZZZ&-BBB")
        assert blocking == []
        assert warnings and "adds ZZZ" in warnings[0] and "drops AAA" in warnings[0]

    def test_reordering_the_same_codes_raises_nothing(self):
        assert integrity.validate_replacement("AAA-BBB", "-BBB&AAA") == ([], [])


class TestRepairsCarryToTheNextPhase:
    """A repair is keyed by the expression text, so a later DTx repeating that
    exact text inherits the decision instead of asking again."""

    def _next_phase(self):
        return [CircuitRow("DASH", "QK777", "QB1-QA1"),   # same text, new circuit
                CircuitRow("IP", "QK888", "QA1,QA2"),     # a new problem
                CircuitRow("IP", "QK999", "QB1/QA1")]     # sound

    def test_a_known_repair_is_applied_without_asking_again(self):
        fixes = {"QB1-QA1": "QB1&-QA1"}
        rows = integrity.apply_fixes(self._next_phase(), fixes)
        assert rows[0].sales_code == "QB1&-QA1"

    def test_only_the_unseen_problem_still_needs_a_decision(self):
        fixes = {"QB1-QA1": "QB1&-QA1"}
        issues = integrity.scan(self._next_phase())
        assert {i.expression for i in issues} == {"QB1-QA1", "QA1,QA2"}
        still_open = [i for i in issues if i.expression not in fixes]
        assert [i.expression for i in still_open] == ["QA1,QA2"]

    def test_a_repair_for_text_absent_from_this_dtx_changes_nothing(self):
        fixes = {"NOT-INTHIS": "NOT&-INTHIS"}
        rows = self._next_phase()
        assert [r.sales_code for r in integrity.apply_fixes(rows, fixes)] == \
            [r.sales_code for r in rows]
