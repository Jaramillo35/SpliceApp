"""Splice Generation: the grammar, the generator, and what it writes.

The package exports ten functions and, before this file, nine of them had
never been called by a test. That is the honest reason two correctness bugs
lived in it for so long — a second sales-code grammar that read ``&`` and
``/`` in the opposite order to the rest of the app, and a display path that
emitted expressions which did not parse.

The fixture is ``fixtures_splice_gen``: an invented five-part-number harness
whose circuits cover a direct pair, a splice, a conditioned splice, the
operator-precedence case and the universal-code case.
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent))

import fixtures_splice_gen as fx  # noqa: E402

from splice.dtxcircuits import conventions  # noqa: E402
from splice.inline import salescode  # noqa: E402
from splice.splice_gen import (  # noqa: E402
    evaluate_expression_against_all_pns,
    generate_expression_for_selected_pns,
    generate_sales_code_expression,
    get_candidate_codes_from_option_df,
    run_analysis,
    run_analysis_from_option_df,
    simplify_expression_for_display,
    validate_generated_expression,
)
from splice.splice_gen.processor import (  # noqa: E402
    ExpressionSyntaxError,
    evaluate_expression,
    parse_or_false,
    parse_sales_code_expression,
)


def gen_evaluate(expression: str, present: set[str]) -> bool:
    """Evaluate through splice_gen's own parser and stack machine."""
    return evaluate_expression(parse_sales_code_expression(expression), present)


@pytest.fixture(scope="module")
def workbook(tmp_path_factory) -> Path:
    return fx.write_input(tmp_path_factory.mktemp("splice_gen") / "input.xlsx")


@pytest.fixture(scope="module")
def analysis(workbook) -> dict:
    return run_analysis(workbook)


class TestOneGrammar:
    """The app must not hold two opinions about what an expression means.

    ``splice.inline.salescode`` is the documented one: ``/`` binds tightest,
    so ``A/B&C`` is ``(A/B)&C``. This module used to give ``&`` the tighter
    bind — the precedence it has in most programming languages — which the
    other module's docstring warns against by name.
    """

    #: every shape that matters, with the unparenthesised mixed ones — the
    #: only ones that ever disagreed — deliberately over-represented
    CORPUS = ["A", "-A", "A&B", "A/B", "A/B&C", "A&B/C", "-A&B/C", "A/-B&C",
              "A/B/C&A", "A&B&C", "(A/B)&C", "A/(B&C)", "-A/-B&C", "A&-B/C",
              "A/B&-C", "(A&B)/C", "-A&-B/-C"]

    def test_the_two_evaluators_agree_on_every_expression(self):
        codes = ["A", "B", "C"]
        disagreements = []
        for expression in self.CORPUS:
            for bits in itertools.product([0, 1], repeat=len(codes)):
                present = {c for c, b in zip(codes, bits) if b}
                if salescode.evaluate(expression, present) != gen_evaluate(expression, present):
                    disagreements.append((expression, sorted(present)))
                    break
        assert not disagreements, f"grammars diverge on: {disagreements}"

    def test_slash_binds_tighter_than_ampersand(self):
        """The one case that used to invert. Only A present: A/B&C is
        (A/B)&C, which needs C, so it is false."""
        assert gen_evaluate("A/B&C", {"A"}) is False
        assert gen_evaluate("A/B&C", {"A", "C"}) is True

    def test_the_real_expression_from_the_export(self):
        """``ERC&CYC/CYF`` appears in 2028RU X1. Read correctly it needs ERC;
        the old reading matched a part number carrying CYF alone."""
        assert gen_evaluate("ERC&CYC/CYF", {"CYF"}) is False
        assert gen_evaluate("ERC&CYC/CYF", {"ERC", "CYF"}) is True
        assert gen_evaluate("ERC&CYC/CYF", {"ERC", "CYC"}) is True

    def test_parentheses_still_win(self):
        assert gen_evaluate("(A&B)/C", {"C"}) is True
        assert gen_evaluate("A&(B/C)", {"C"}) is False


class TestUniversalCode:
    """One 501 rule for the whole app, held in dtxcircuits.conventions."""

    def test_a_bare_universal_code_is_always_true(self):
        assert gen_evaluate("501", set()) is True
        assert parse_sales_code_expression("501").postfix_tokens == ["TRUE"]

    def test_inside_a_larger_expression_it_is_an_ordinary_code(self):
        """The SE's ruling. This module used to strip 501 wherever it
        appeared, which quietly made 501/RHV true for every part number."""
        assert gen_evaluate("501/RHV", set()) is False
        assert gen_evaluate("501/RHV", {"RHV"}) is True

    def test_it_matches_the_shared_convention(self):
        for expression in ("501", "501/RHV", "501&HAH", "XC4/HAH/HBB/501"):
            universal = conventions.effective_condition(expression) is None
            assert gen_evaluate(expression, set()) == universal, expression

    def test_a_blank_expression_is_unconditional(self):
        assert gen_evaluate("", set()) is True


class TestDisplayExpression:
    """What the workbook's "Display Sales Code" column carries."""

    def _generated(self) -> list[str]:
        code_map = fx.harness_code_map()
        out = []
        for size in range(1, len(code_map) + 1):
            for target in itertools.combinations(sorted(code_map), size):
                expression = generate_expression_for_selected_pns(list(target), code_map)
                if expression:
                    out.append(expression)
        return out

    def test_everything_it_emits_parses(self):
        """The reported bug: the old simplifier split on '&' with no regard
        for parentheses, so '(-AAA&-CCC)/(AAA&CCC)' came back unbalanced."""
        bad = []
        for expression in self._generated():
            shown = simplify_expression_for_display(expression)
            try:
                parse_sales_code_expression(shown)
            except ExpressionSyntaxError as exc:
                bad.append((expression, shown, str(exc)))
        assert not bad, f"unparseable display forms: {bad[:3]}"

    def test_the_scrambling_case_specifically(self):
        shown = simplify_expression_for_display("(-AAA&-CCC)/(AAA&CCC)")
        parse_sales_code_expression(shown)          # must not raise
        assert shown.count("(") == shown.count(")")

    def test_it_never_changes_what_the_expression_means(self):
        codes = ["AAA", "BBB", "CCC"]
        for expression in self._generated():
            shown = simplify_expression_for_display(expression)
            for bits in itertools.product([0, 1], repeat=len(codes)):
                present = {c for c, b in zip(codes, bits) if b}
                assert salescode.evaluate(shown, present) == \
                    salescode.evaluate(expression, present), \
                    f"{expression!r} -> {shown!r} differs on {sorted(present)}"

    def test_it_works_on_a_vocabulary_it_has_never_seen(self):
        """The old one classified terms against one programme's literal code
        lists — BHG, BNZ, RFX, DK2, DK4 — and grouped anything starting DK."""
        shown = simplify_expression_for_display("QZ9&-QA1")
        assert salescode.evaluate(shown, {"QZ9"}) is True
        assert salescode.evaluate(shown, {"QZ9", "QA1"}) is False

    def test_constants_pass_through(self):
        assert simplify_expression_for_display("TRUE") == "TRUE"
        assert simplify_expression_for_display("") == ""


class TestGeneratingExpressions:
    """generate → validate → evaluate, the loop the engine exists for."""

    def test_a_generated_expression_targets_exactly_what_was_asked(self):
        code_map = fx.harness_code_map()
        checked = 0
        for size in range(1, len(code_map) + 1):
            for target in itertools.combinations(sorted(code_map), size):
                expression = generate_expression_for_selected_pns(list(target), code_map)
                if not expression:
                    continue
                checked += 1
                matched = set(evaluate_expression_against_all_pns(expression, code_map))
                assert matched == set(target), f"{expression!r} -> {sorted(matched)}"
        assert checked > 10, "the sweep must actually exercise the generator"

    def test_validation_agrees_with_evaluation(self):
        code_map = fx.harness_code_map()
        target = ["99000001AA", "99000002AA"]
        expression = generate_expression_for_selected_pns(target, code_map)
        assert validate_generated_expression(expression, target, code_map)
        assert not validate_generated_expression(expression, ["99000004AA"], code_map)

    def test_an_impossible_selection_is_refused_not_guessed(self):
        """99000001AA and 99000005AA differ by nothing the codes can express
        together with a third; whatever comes back must still be exact."""
        code_map = fx.harness_code_map()
        for size in range(1, len(code_map) + 1):
            for target in itertools.combinations(sorted(code_map), size):
                expression = generate_expression_for_selected_pns(list(target), code_map)
                if expression:
                    assert validate_generated_expression(expression, list(target), code_map)

    def test_no_selection_yields_no_expression(self):
        assert generate_expression_for_selected_pns([], fx.harness_code_map()) == ""

    def test_selecting_everything_is_unconditional(self):
        code_map = fx.harness_code_map()
        expression = generate_sales_code_expression(sorted(code_map), code_map)
        assert expression == "TRUE"

    def test_candidate_codes_come_from_the_option_sheet(self):
        options = fx.option_frame()
        every = get_candidate_codes_from_option_df(options)
        assert {"AAA", "BBB", "CCC"} <= every
        assert "501" not in every, "a universal code cannot discriminate"
        just_wide = get_candidate_codes_from_option_df(options, circuit_name="CKT_WIDE")
        assert "AAA" in just_wide and "BBB" in just_wide


class TestRunAnalysis:
    def test_it_produces_the_expected_frames(self, analysis):
        for key in ("harness_code_map_df", "option_df", "device_evaluation_df",
                    "configurations_df", "generated_connections_df",
                    "harness_print_matrix_df", "validation_report_df"):
            assert key in analysis, key
        assert not analysis["configurations_df"].empty

    def test_topology_follows_the_endpoint_count(self, analysis):
        """Two ends is a wire; three or more have to meet at a splice. This
        used to be overridden by configuration id for one hardcoded circuit."""
        cfg = analysis["configurations_df"]
        by_circuit = dict(zip(cfg["Circuit Name"], cfg["Topology Type"]))
        assert by_circuit["CKT_PAIR"] == "Direct"
        assert by_circuit["CKT_SPLICE"] == "Splice"

    def test_the_precedence_fix_reaches_the_output(self, analysis):
        """CKT_MIXED is 'AAA&BBB/CCC'. Under the canonical grammar only the
        part number carrying AAA and BBB qualifies; the old reading also
        pulled in the CCC-only part number."""
        cfg = analysis["configurations_df"]
        row = cfg[cfg["Circuit Name"] == "CKT_MIXED"].iloc[0]
        assert row["Target Harness PNs"] == "99000002AA"

    def test_rule_6_reports_the_scoped_candidate_limitation(self, analysis):
        """A separate, pre-existing defect — characterised, not fixed.

        A configuration may only use the sales codes named on its own
        endpoints. Where the part numbers it must separate differ by a code
        outside that set, no exact expression is reachable and a wider one is
        emitted: CKT_WIDE claims 99000001AA but 'AAA&-CCC' also matches
        99000002AA, which needs 'AAA&-BBB' to exclude. The engine notices —
        this rule is how — but only in a sheet.

        Present before this batch and unchanged by it. Widening the candidate
        set is a design decision with output consequences, so it is reported
        rather than quietly taken.
        """
        report = analysis["validation_report_df"]
        rule6 = report[report["Rule"].str.startswith("6.")].iloc[0]
        assert rule6["Status"] == "FAIL"
        assert "Matched 5 of 8" in rule6["Details"], (
            "if this changed, the limitation moved — re-read it before "
            "updating the number")

    def test_an_in_memory_option_frame_gives_the_same_answer(self, workbook, analysis):
        other = run_analysis_from_option_df(workbook, fx.option_frame())
        pd.testing.assert_frame_equal(
            other["configurations_df"].reset_index(drop=True),
            analysis["configurations_df"].reset_index(drop=True))


class TestMalformedExpressions:
    """A real export contains them; one used to abort the whole run."""

    def test_a_malformed_expression_is_false_everywhere(self):
        parsed = parse_or_false("QB1-QA1")
        assert parsed.postfix_tokens == ["FALSE"]
        assert evaluate_expression(parsed, {"QB1", "QA1"}) is False

    def test_the_strict_parser_still_raises_for_callers_that_check(self):
        with pytest.raises(ExpressionSyntaxError):
            parse_sales_code_expression("QB1-QA1")

    def test_the_run_completes_and_names_the_bad_expression(self, workbook, tmp_path):
        options = pd.concat([fx.option_frame(), pd.DataFrame([
            {"CNUM": "D900A", "Pin": "1", "Circuit": "CKT_BAD",
             "Sales Code": "QB1-QA1"}])], ignore_index=True)
        result = run_analysis_from_option_df(workbook, options)
        report = result["validation_report_df"]
        rule7 = report[report["Rule"].str.startswith("7.")].iloc[0]
        assert rule7["Status"] == "FAIL"
        assert "QB1-QA1" in rule7["Details"]
        assert not result["device_evaluation_df"].empty, "the run still completes"

    def test_a_clean_input_passes_the_parse_rule(self, analysis):
        report = analysis["validation_report_df"]
        rule7 = report[report["Rule"].str.startswith("7.")].iloc[0]
        assert rule7["Status"] == "PASS"


class TestNoHardcodedTopologies:
    """The engine used to build four fixed topologies for a circuit named
    D454 — six hardcoded connector names, five hardcoded sales codes and a
    literal table of connections — gated on nothing but that name."""

    def test_the_module_holds_no_programme_specific_names(self):
        import splice.splice_gen.processor as processor
        source = Path(processor.__file__).read_text()
        code = "\n".join(line for line in source.splitlines()
                         if not line.strip().startswith("#"))
        for token in ('"D454"', '"SD454', '"Y354A"', '"D2321A"', '"D2851A"',
                      '"BHG"', '"BNZ"', '"DK2"', '"DK4"'):
            assert token not in code, f"{token} is still hardcoded in the engine"

    def test_a_circuit_named_D454_is_treated_like_any_other(self, workbook):
        """The name must carry no meaning. Two endpoints, so: a direct
        connection, exactly as CKT_PAIR gets."""
        renamed = fx.option_frame()
        renamed.loc[renamed["Circuit"] == "CKT_PAIR", "Circuit"] = "D454"
        result = run_analysis_from_option_df(workbook, renamed)
        cfg = result["configurations_df"]
        rows = cfg[cfg["Circuit Name"] == "D454"]
        assert len(rows) == 1, "one configuration, not four fixed ones"
        assert rows.iloc[0]["Topology Type"] == "Direct"
        connections = result["generated_connections_df"]
        if not connections.empty and "Splice Name" in connections.columns:
            assert not any(str(v).upper().startswith("SD454")
                           for v in connections["Splice Name"])
