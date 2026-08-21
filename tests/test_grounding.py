"""Tests for the grounding check.

This is the safety-critical piece: it is what stands between an engineer and a
confidently invented SECR number. It has to fail closed on fabrications and
stay quiet on ordinary prose — a checker that fired on every answer would be
switched off within a day.
"""

from __future__ import annotations

from secrdb.assistant import grounding
from secrdb.assistant.grounding import check, extract_identifiers, summarise_evidence

EVIDENCE = [
    {
        "secr_number": "D50319A",
        "version": "1",
        "program": "RU",
        "model_year": "2028",
        "phase": "X1",
        "harness_family": "IP",
        "object_type": "circuit",
        "object_id": "A111",
        "action": "COMP CHG",
        "field": "Sales_Code",
        "old_value": "JRC/XZ4",
        "new_value": "XZ4",
        "dtcr_number": "50319",
        "bulletin_numbers": "320767, 318725_02",
    }
]


# ---------------------------------------------------------------------------
# What counts as an identifier
# ---------------------------------------------------------------------------

def test_identifiers_are_extracted() -> None:
    found = extract_identifiers(
        "SECR D50319A changed circuit A111 under DTCR 50319, "
        "see SECR_IP_D28X1RU_1000_V1_05072026.xlsx"
    )
    assert "D50319A" in found
    assert "A111" in found
    assert "50319" in found
    assert any(token.endswith(".XLSX") for token in found)


def test_ordinary_prose_is_not_flagged() -> None:
    """A checker that fires on normal writing gets ignored."""
    assert extract_identifiers(
        "Found 5 change records across 3 SECRs. The connector was replaced and "
        "the circuit gauge changed from thin to thick."
    ) == []


def test_vocabulary_words_are_not_identifiers() -> None:
    assert extract_identifiers("COMP CHG and PN CHANGE on the IP harness") == []


def test_version_and_model_year_shorthand_are_prose() -> None:
    assert extract_identifiers("version V2 in MY28 and MY2028") == []


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------

def test_an_answer_built_from_the_evidence_passes() -> None:
    report = check(
        "SECR D50319A (RU, MY2028, IP) changed circuit A111 from JRC/XZ4 to "
        "XZ4 under DTCR 50319.",
        EVIDENCE,
    )
    assert report.grounded
    assert report.ungrounded == []


def test_an_invented_secr_number_is_caught() -> None:
    report = check("This was changed in SECR D99999Z.", EVIDENCE)

    assert not report.grounded
    assert "D99999Z" in report.ungrounded
    assert "D99999Z" in report.reason


def test_an_invented_dtcr_is_caught() -> None:
    report = check("Circuit A111 changed under DTCR 12345.", EVIDENCE)
    assert not report.grounded
    assert "12345" in report.ungrounded


def test_an_invented_connector_is_caught() -> None:
    report = check("Connector D9999X was replaced.", EVIDENCE)
    assert not report.grounded
    assert "D9999X" in report.ungrounded


def test_a_token_from_the_question_is_allowed() -> None:
    """'There is no record of ZZ999' must be sayable — that is the honest answer."""
    report = check(
        "The database has no record of circuit ZZ999.",
        [],
        question="when did circuit ZZ999 change?",
    )
    assert report.grounded


def test_a_model_year_may_be_written_either_way() -> None:
    report = check("Changed in MY28 on program RU.", EVIDENCE)
    assert report.grounded


def test_part_number_pieces_are_matched() -> None:
    evidence = [{"new_value": "6098-7966_6911-8049"}]
    assert check("The new part number is 6098-7966_6911-8049.", evidence).grounded
    assert check("Part 6098-7966 was used.", evidence).grounded


def test_an_empty_answer_is_trivially_grounded() -> None:
    assert check("", EVIDENCE).grounded


def test_evidence_may_be_any_shape() -> None:
    """Tool results are nested dicts and lists; all of it counts as evidence."""
    nested = {"totals": {"secrs": 2}, "rows": [{"secr_number": "D50319A"}]}
    assert check("See D50319A.", nested).grounded


def test_the_report_names_what_failed() -> None:
    report = check("SECRs D11111A and D22222B refer.", EVIDENCE)
    assert not report.grounded
    assert len(report.ungrounded) == 2
    assert "D11111A" in report.reason


# ---------------------------------------------------------------------------
# Fallback summary
# ---------------------------------------------------------------------------

def test_the_summary_counts_only_what_it_was_given() -> None:
    text = summarise_evidence(EVIDENCE)
    assert "1 change record" in text
    assert "D50319A" in text
    assert "IP" in text
    assert "COMP CHG (1)" in text
    assert "50319" in text


def test_the_summary_is_itself_grounded() -> None:
    """The fallback must pass the same check the model's prose had to."""
    assert check(summarise_evidence(EVIDENCE), EVIDENCE).grounded


def test_an_empty_result_summarises_honestly() -> None:
    assert "No matching records" in summarise_evidence([])


def test_the_summary_caps_long_lists() -> None:
    rows = [
        {"secr_number": f"D{index:05d}A", "action": "CHG"} for index in range(30)
    ]
    text = summarise_evidence(rows)
    assert "30 change record(s)" in text
    assert "and others" in text


# ---------------------------------------------------------------------------
# Role checking
#
# From a field report: asked "which DTCRs are related to circuit A111?", the
# model answered with SECR numbers under a "DTCRs" heading. Every one of those
# identifiers WAS in the evidence, so an existence check passed it. Existence
# is not enough — a value has to be used in the role it actually holds.
# ---------------------------------------------------------------------------

#: Mirrors what get_changes_by_circuit("A111") actually returns.
ROLE_EVIDENCE = [
    {
        "secr_number": "D50319A", "dtcr_number": "50319",
        "harness_family": "IP", "phase": "X1", "model_year": "2028",
        "object_id": "A111",
    },
    {
        "secr_number": "D50277A", "dtcr_number": "50092",
        "harness_family": "DASH", "phase": "X1", "model_year": "2028",
        "object_id": "A111",
    },
    {
        "secr_number": "D49957B", "dtcr_number": "50092",
        "harness_family": "BODY_RIGHT", "phase": "X1", "model_year": "2028",
        "object_id": "A111",
    },
]


def test_a_secr_number_presented_as_a_dtcr_is_caught() -> None:
    """The exact answer that was reported as wrong."""
    answer = (
        "The circuit A111 is related to the following DTCRs:\n\n"
        "D50319A (Phase X1, Model Year 2028, Harness Family IP)\n"
        "D50277A (Phase X1, Model Year 2028, Harness Family DASH)\n"
        "D49957B (Phase X1, Model Year 2028, Harness Family BODY_RIGHT)"
    )

    report = check(
        answer, ROLE_EVIDENCE, question="which DTCRs are related to circuit A111?"
    )

    assert not report.grounded
    assert report.ungrounded == []          # they all exist...
    assert report.misattributed             # ...but not as DTCRs
    assert "D50319A" in str(report.misattributed[0])
    assert "DTCR" in report.reason


def test_the_correct_dtcr_answer_passes() -> None:
    report = check(
        "Circuit A111 is covered by DTCRs 50319 and 50092.",
        ROLE_EVIDENCE,
        question="which DTCRs are related to circuit A111?",
    )
    assert report.grounded, report.reason


def test_a_secr_presented_as_a_secr_passes() -> None:
    report = check("SECR D50319A changed it under DTCR 50319.", ROLE_EVIDENCE)
    assert report.grounded


def test_a_dtcr_number_presented_as_a_secr_is_caught() -> None:
    report = check("This was changed in SECR 50319.", ROLE_EVIDENCE)
    assert not report.grounded
    assert report.misattributed


def test_role_checking_stops_at_ordinary_prose() -> None:
    """'DTCR 50319 changed circuit A111' must not demand A111 be a DTCR."""
    report = check(
        "DTCR 50319 changed circuit A111 from JRC/XZ4 to XZ4.",
        ROLE_EVIDENCE + [{"object_id": "A111", "old_value": "JRC/XZ4", "new_value": "XZ4"}],
    )
    assert report.grounded, report.reason


def test_a_list_of_dtcrs_is_checked_through(monkeypatch) -> None:
    report = check("DTCRs: 50319, 50092 and 99999.", ROLE_EVIDENCE)
    assert not report.grounded
    assert [item.token for item in report.misattributed] == ["99999"]


def test_roles_are_not_checked_when_the_evidence_lacks_the_field() -> None:
    """With no dtcr_number anywhere, there is nothing to check against."""
    report = check("See DTCR 50319.", [{"secr_number": "D50319A"}], question="DTCR 50319?")
    assert report.grounded


def test_the_fallback_summary_reports_missing_dtcrs() -> None:
    rows = ROLE_EVIDENCE + [{"secr_number": "M27001", "dtcr_number": None}]
    text = summarise_evidence(rows)
    assert "50319" in text and "50092" in text
    assert "no DTCR recorded" in text
