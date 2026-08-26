"""Meeting-transcript anonymization and document logic.

The Windows capture loop itself cannot run here; everything that decides what
lands on disk — speaker aliasing, label detection, partial-caption folding,
rendering — is platform-neutral and covered below.
"""

from __future__ import annotations

import pytest

from splice.common.errors import SpliceError
from splice.transcripts.recorder import (
    ATTESTATIONS,
    PARTICIPANT_NOTICE,
    Consent,
    Recorder,
    SpeakerAnonymizer,
    Transcript,
    looks_like_name,
)


class TestLooksLikeName:
    def test_typical_display_names(self):
        assert looks_like_name("Maria Lopez")
        assert looks_like_name("Jean-Claude Van Damme")
        assert looks_like_name("O'Brien")

    def test_sentences_are_not_names(self):
        assert not looks_like_name("We should ship it on Friday.")
        assert not looks_like_name("what do you think")
        assert not looks_like_name("Let me share my screen with everyone right now")

    def test_edge_cases(self):
        assert not looks_like_name("")
        assert not looks_like_name("Room 41B")  # digits
        assert not looks_like_name("Yes?")      # punctuation


class TestSpeakerAnonymizer:
    def test_aliases_are_stable_and_sequential(self):
        anon = SpeakerAnonymizer()
        assert anon.alias("Maria Lopez") == "Speaker 1"
        assert anon.alias("John Smith") == "Speaker 2"
        assert anon.alias("Maria Lopez") == "Speaker 1"
        assert anon.count == 2

    def test_normalization_folds_case_and_spacing(self):
        anon = SpeakerAnonymizer()
        assert anon.alias("Maria  Lopez") == anon.alias("maria lopez")


class TestTranscript:
    def test_standalone_label_then_text(self):
        t = Transcript()
        t.add_caption("Maria Lopez")
        t.add_caption("we can start now")
        assert len(t.entries) == 1
        assert t.entries[0].speaker == "Speaker 1"
        assert t.entries[0].text == "we can start now"

    def test_inline_name_colon_text(self):
        t = Transcript()
        t.add_caption("John Smith: the budget is approved")
        assert t.entries[0].speaker == "Speaker 1"
        assert t.entries[0].text == "the budget is approved"

    def test_partial_captions_fold_into_final_sentence(self):
        t = Transcript()
        t.add_caption("Maria Lopez")
        t.add_caption("we should")
        t.add_caption("we should ship it")
        t.add_caption("we should ship it on Friday")
        assert len(t.entries) == 1
        assert t.entries[0].text == "we should ship it on Friday"

    def test_speaker_change_starts_new_entry(self):
        t = Transcript()
        t.add_caption("Maria Lopez")
        t.add_caption("first point")
        t.add_caption("John Smith")
        t.add_caption("second point")
        assert [e.speaker for e in t.entries] == ["Speaker 1", "Speaker 2"]

    def test_known_label_wins_even_if_heuristic_would_reject(self):
        t = Transcript()
        t.add_caption("Maria Lopez: hello")
        # exact repeat of a known name is always a label, regardless of shape
        t.add_caption("maria lopez")
        t.add_caption("closing remarks")
        assert t.entries[-1].speaker == "Speaker 1"

    def test_no_real_names_in_rendered_output(self):
        t = Transcript()
        t.add_caption("Maria Lopez")
        t.add_caption("agenda item one")
        t.add_caption("John Smith: agreed, moving on")
        rendered = t.render()
        assert "Maria" not in rendered
        assert "Lopez" not in rendered
        assert "John" not in rendered
        assert "Smith" not in rendered
        assert "Speaker 1" in rendered and "Speaker 2" in rendered

    def test_render_structure(self):
        t = Transcript()
        t.add_caption("Maria Lopez")
        t.add_caption("hello everyone")
        rendered = t.render()
        assert rendered.startswith("# Meeting Transcript")
        assert "anonymized" in rendered
        assert "**Speaker 1** hello everyone" in rendered

    def test_render_embeds_llm_instructions(self):
        # the file itself tells the assistant what to produce, so pasting a
        # transcript into an LLM yields minutes with no extra prompt
        rendered = Transcript().render()
        assert "How to use this file" in rendered
        assert "Instructions for the assistant" in rendered
        assert "action" in rendered and "pending" in rendered
        # instructions come before the transcript body
        assert rendered.index("Instructions for the assistant") < rendered.index("---")

    def test_duplicate_items_ignored(self):
        t = Transcript()
        t.add_caption("Maria Lopez")
        assert t.add_caption("same line") is True
        assert t.add_caption("same line") is False
        assert len(t.entries) == 1


class TestRecorderPause:
    def test_pause_and_resume_transitions(self):
        from splice.transcripts.recorder import Recorder
        r = Recorder()
        r.state = "recording"          # as set by a live capture loop
        r.pause()
        assert r.state == "paused" and r._paused.is_set()
        r.resume()
        assert r.state == "recording" and not r._paused.is_set()

    def test_pause_only_applies_while_recording(self):
        from splice.transcripts.recorder import Recorder
        r = Recorder()
        r.pause()                      # idle: no-op
        assert r.state == "idle" and not r._paused.is_set()

    def test_stop_clears_pause(self):
        from splice.transcripts.recorder import Recorder
        r = Recorder()
        r.state = "recording"
        r.pause()
        r.stop()
        assert not r._paused.is_set()


def _signed_consent(**kw) -> Consent:
    c = Consent(announced=True, permission_granted=True, **kw)
    return c.sign("Martin Jaramillo")


class TestConsent:
    def test_incomplete_until_every_attestation_and_a_signature(self):
        assert not Consent().complete
        assert not Consent(announced=True).complete
        assert not Consent(announced=True, permission_granted=True).complete
        assert _signed_consent().complete

    def test_missing_names_each_gap(self):
        gaps = Consent().missing
        assert len(gaps) == 3
        assert any("told" in g for g in gaps)
        assert any("permission" in g for g in gaps)
        assert any("unsigned" in g for g in gaps)

    def test_signature_is_normalized_and_timestamped(self):
        c = Consent().sign("  Martin   Jaramillo ")
        assert c.attested_by == "Martin Jaramillo"
        assert c.attested_at is not None

    def test_blank_signature_does_not_satisfy_the_gate(self):
        c = Consent(announced=True, permission_granted=True).sign("   ")
        assert not c.complete

    def test_notice_defaults_to_the_participant_message(self):
        assert Consent().notice_text == PARTICIPANT_NOTICE
        assert "minutes" in PARTICIPANT_NOTICE
        assert "anonymized" in PARTICIPANT_NOTICE


class TestNamedRecording:
    def test_names_are_written_only_in_named_mode(self):
        anon = Transcript()
        anon.add_caption("Maria Lopez")
        anon.add_caption("we ship on friday")
        assert "Maria" not in anon.render()
        assert anon.entries[0].speaker == "Speaker 1"

        named = Transcript(record_names=True, consent=_signed_consent())
        named.add_caption("Maria Lopez")
        named.add_caption("we ship on friday")
        assert named.entries[0].speaker == "Maria Lopez"
        assert "Maria Lopez" in named.render()

    def test_inline_name_colon_text_also_respects_the_mode(self):
        named = Transcript(record_names=True, consent=_signed_consent())
        named.add_caption("Maria Lopez: we ship on friday")
        assert named.entries[0].speaker == "Maria Lopez"
        assert named.entries[0].text == "we ship on friday"

    def test_speaker_count_still_tracked_in_named_mode(self):
        named = Transcript(record_names=True, consent=_signed_consent())
        for cap in ("Maria Lopez", "hello", "Bob Chen", "hi there"):
            named.add_caption(cap)
        assert named.anonymizer.count == 2

    def test_partial_caption_folding_survives_named_mode(self):
        named = Transcript(record_names=True, consent=_signed_consent())
        named.add_caption("Maria Lopez")
        named.add_caption("we ship")
        named.add_caption("we ship on friday")
        assert len(named.entries) == 1
        assert named.entries[0].text == "we ship on friday"


class TestPrivacyRecord:
    def test_anonymized_transcript_states_no_consent_needed(self):
        out = Transcript().render()
        assert "anonymized recording" in out
        assert "never written to disk" in out
        assert "Privacy record" not in out

    def test_named_transcript_carries_the_full_attestation(self):
        c = _signed_consent(notes="Ana asked to be left out")
        out = Transcript(record_names=True, consent=c).render()
        assert "Privacy record — participant names recorded" in out
        # both attestations rendered as ticked boxes
        assert out.count("- [x]") == 2
        for _key, text in ATTESTATIONS:
            assert text in out
        assert "Martin Jaramillo" in out
        assert "Ana asked to be left out" in out
        # the exact notice sent is quoted as evidence
        assert "> Hi all" in out

    def test_edited_notice_is_what_gets_recorded(self):
        c = _signed_consent(notice_text="I told them verbally at 10:03.")
        out = Transcript(record_names=True, consent=c).render()
        assert "I told them verbally at 10:03." in out

    def test_named_mode_instructions_drop_the_speaker_n_wording(self):
        out = Transcript(record_names=True, consent=_signed_consent()).render()
        assert "Speaker N" not in out
        assert "participant names exactly as written" in out


class TestRecorderConsentGate:
    def test_named_start_without_consent_is_refused(self):
        with pytest.raises(SpliceError, match="Cannot record participant names"):
            Recorder().start(record_names=True)

    def test_named_start_with_incomplete_consent_is_refused(self):
        with pytest.raises(SpliceError, match="unsigned"):
            Recorder().start(record_names=True,
                             consent=Consent(announced=True, permission_granted=True))

    def test_refusal_names_the_specific_gaps(self):
        with pytest.raises(SpliceError) as exc:
            Recorder().start(record_names=True, consent=Consent().sign("Martin"))
        message = str(exc.value)
        assert "told" in message and "permission" in message

    def test_anonymized_start_needs_no_consent(self):
        r = Recorder()
        r.start()          # no capture backend off-Windows: returns without raising
        assert r.record_names is False
        assert r.consent is None

    def test_status_reports_the_privacy_mode(self):
        assert Recorder().status()["record_names"] is False
