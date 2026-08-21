"""Meeting-transcript anonymization and document logic.

The Windows capture loop itself cannot run here; everything that decides what
lands on disk — speaker aliasing, label detection, partial-caption folding,
rendering — is platform-neutral and covered below.
"""

from __future__ import annotations

from splice.transcripts.recorder import (
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
