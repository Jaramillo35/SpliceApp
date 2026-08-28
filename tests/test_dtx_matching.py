"""Suggesting which complexity file belongs to which DTx harness family.

Names never agree exactly across the two sources, so the workbench offers
candidates. A suggestion is only ever a hint — the wrong one connected by
hand produces confident findings, so scoring must rank the plausible ones
above the merely similar, and stay quiet when nothing fits.
"""

from __future__ import annotations

from splice.dtxcircuits import matching
from splice.dtxcircuits.matching import EXACT, auto_map, normalize, score, suggest, tokens


class TestNormalize:
    def test_punctuation_and_case_are_ignored(self):
        assert normalize("SEAT_2ND_ROW_LEFT") == normalize("Seat 2nd Row Left")

    def test_empty_stays_empty(self):
        assert normalize("") == "" and normalize(None) == ""


class TestTokens:
    def test_splits_on_punctuation_and_upper_cases(self):
        assert tokens("Battery_Positive ESS-1") == ["BATTERY", "POSITIVE", "ESS", "1"]

    def test_noise_words_are_dropped(self):
        # every file is a "harness complexity", so those words identify nothing
        assert tokens("Harness Complexity Body Left") == ["BODY", "LEFT"]


class TestScore:
    def test_exact_after_normalisation(self):
        value, reason = score("SEAT_2ND_ROW_LEFT", "SEAT 2ND ROW LEFT")
        assert value == EXACT and "exactly" in reason

    def test_containment_scores_by_overlap(self):
        # POWERTRAIN inside POWERTRAIN GAS is a strong hint
        value, reason = score("POWERTRAIN", "POWERTRAIN GAS")
        assert 0.5 <= value < EXACT
        assert "contained in" in reason

    def test_a_longer_suffix_lowers_the_score(self):
        close, _ = score("Seat_Pass", "Seat_Pass_PWR")
        far, _ = score("IP", "JUMPER_IP")
        assert close > far, "a short stem inside a long name must score lower"

    def test_shared_tokens_score_below_containment(self):
        value, reason = score("BODY_LEFT", "Body_Right")
        assert 0 < value < 0.5 and "shares BODY" in reason

    def test_left_and_right_are_not_suggested_for_each_other(self):
        # the dangerous false friend: it must fall under the threshold
        value, _ = score("BODY_LEFT", "Body_Right")
        assert value < matching.THRESHOLD

    def test_unrelated_names_score_zero(self):
        assert score("IP", "SOMETHING_ELSE")[0] == 0.0

    def test_blank_names_never_match(self):
        assert score("", "IP")[0] == 0.0
        assert score("IP", "")[0] == 0.0


class TestSuggest:
    CANDIDATES = {
        "a.xlsm": "POWERTRAIN GAS",
        "b.xlsm": "Body_Left",
        "c.xlsm": "SOMETHING_ELSE",
        "d.xlsm": "Powertrain_PHEV",
    }

    def test_ranks_the_strongest_first(self):
        out = suggest(["POWERTRAIN"], self.CANDIDATES)["POWERTRAIN"]
        assert out[0].key == "a.xlsm"
        assert out[0].score >= out[-1].score

    def test_suggests_both_powertrain_variants(self):
        keys = {s.key for s in suggest(["POWERTRAIN"], self.CANDIDATES)["POWERTRAIN"]}
        assert {"a.xlsm", "d.xlsm"} <= keys

    def test_a_family_with_no_candidate_gets_an_empty_list(self):
        assert suggest(["HEADLINER"], self.CANDIDATES)["HEADLINER"] == []

    def test_exact_match_is_flagged(self):
        out = suggest(["BODY_LEFT"], self.CANDIDATES)["BODY_LEFT"]
        assert out[0].is_exact and out[0].key == "b.xlsm"

    def test_limit_caps_the_number_shown(self):
        out = suggest(["POWERTRAIN"], self.CANDIDATES, limit=1)["POWERTRAIN"]
        assert len(out) == 1

    def test_every_family_gets_a_key(self):
        out = suggest(["IP", "DASH"], self.CANDIDATES)
        assert set(out) == {"IP", "DASH"}

    def test_one_candidate_may_be_offered_to_several_families(self):
        # only the SE can decide; the tool must not silently pick
        out = suggest(["POWERTRAIN", "Powertrain_PHEV"], self.CANDIDATES)
        assert any(s.key == "d.xlsm" for s in out["POWERTRAIN"])
        assert any(s.key == "d.xlsm" for s in out["Powertrain_PHEV"])


class TestAutoMap:
    def test_only_exact_names_are_connected_automatically(self):
        mapping = auto_map(["BODY_LEFT", "POWERTRAIN"],
                           {"b.xlsm": "Body_Left", "a.xlsm": "POWERTRAIN GAS"})
        assert mapping == {"BODY_LEFT": "b.xlsm"}, \
            "a near-miss must be left for the SE"

    def test_a_file_is_used_once(self):
        mapping = auto_map(["IP", "I_P"], {"x.xlsm": "IP"})
        assert list(mapping.values()) == ["x.xlsm"]
        assert len(mapping) == 1

    def test_nothing_to_map_is_empty(self):
        assert auto_map([], {"x.xlsm": "IP"}) == {}
        assert auto_map(["IP"], {}) == {}


class TestOrphans:
    CANDS = {"a.xlsm": "POWERTRAIN GAS", "b.xlsm": "Body_Left",
             "c.xlsm": "MYSTERY_ONE", "d.xlsm": "ZZ_UNKNOWN"}

    def test_orphans_are_the_files_nothing_suggests(self):
        sug = suggest(["BODY_LEFT", "POWERTRAIN"], self.CANDS)
        assert matching.orphans(self.CANDS, sug) == {"c.xlsm", "d.xlsm"}

    def test_no_suggestions_makes_everything_an_orphan(self):
        assert matching.orphans(self.CANDS, {}) == set(self.CANDS)


class TestRankOptions:
    CANDS = {"a.xlsm": "POWERTRAIN GAS", "b.xlsm": "Body_Left",
             "c.xlsm": "MYSTERY_ONE", "d.xlsm": "ZZ_UNKNOWN"}

    def _ranked(self, family):
        sug = suggest(["BODY_LEFT", "POWERTRAIN"], self.CANDS)
        return matching.rank_options(family, self.CANDS, sug)

    def test_no_likely_family_options_come_first(self):
        keys = [k for k, _l in self._ranked("BODY_LEFT")]
        assert keys[:2] == ["c.xlsm", "d.xlsm"], "orphans must lead"

    def test_orphans_are_labelled_as_such(self):
        labels = dict(self._ranked("BODY_LEFT"))
        assert matching.NO_LIKELY_FAMILY in labels["c.xlsm"]
        assert matching.NO_LIKELY_FAMILY not in labels["b.xlsm"]

    def test_the_rest_rank_by_match_for_that_family(self):
        keys = [k for k, _l in self._ranked("BODY_LEFT")]
        assert keys[2] == "b.xlsm", "the 100% match leads the remainder"
        keys = [k for k, _l in self._ranked("POWERTRAIN")]
        assert keys[2] == "a.xlsm", "ranking is per family, not global"

    def test_every_candidate_is_always_offered(self):
        # a family may legitimately take a harness nothing suggested
        keys = {k for k, _l in self._ranked("BODY_LEFT")}
        assert keys == set(self.CANDS)

    def test_match_percentage_is_shown_for_scored_options(self):
        labels = dict(self._ranked("BODY_LEFT"))
        assert "100% match" in labels["b.xlsm"]

    def test_ordering_is_stable_for_equal_scores(self):
        cands = {"x.xlsm": "BETA", "y.xlsm": "ALPHA"}
        keys = [k for k, _l in matching.rank_options("NOTHING", cands, {})]
        assert keys == ["y.xlsm", "x.xlsm"], "ties fall back to name order"


class TestMappingMutation:
    def test_add_appends_and_never_duplicates(self):
        mapping = {}
        matching.add_mapping(mapping, "IP", "a")
        matching.add_mapping(mapping, "IP", "a")
        matching.add_mapping(mapping, "IP", "b")
        assert mapping == {"IP": ["a", "b"]}

    def test_one_family_holds_several_harnesses(self):
        mapping = {}
        for key in ("a", "b", "c"):
            matching.add_mapping(mapping, "SEAT_2ND_ROW", key)
        assert len(mapping["SEAT_2ND_ROW"]) == 3

    def test_a_file_may_serve_more_than_one_family(self):
        # a shared harness is real; only within-row duplicates are prevented
        mapping = {}
        matching.add_mapping(mapping, "Seat_Back_Driver", "shared.xlsm")
        matching.add_mapping(mapping, "Seat_Back_Driver_2", "shared.xlsm")
        assert mapping["Seat_Back_Driver"] == ["shared.xlsm"]
        assert mapping["Seat_Back_Driver_2"] == ["shared.xlsm"]

    def test_remove_takes_one_out_and_leaves_the_rest(self):
        mapping = {"IP": ["a", "b"]}
        matching.remove_mapping(mapping, "IP", "a")
        assert mapping == {"IP": ["b"]}

    def test_removing_something_absent_is_harmless(self):
        mapping = {"IP": ["a"]}
        matching.remove_mapping(mapping, "IP", "zzz")
        matching.remove_mapping(mapping, "NOPE", "a")
        assert mapping == {"IP": ["a"]}
