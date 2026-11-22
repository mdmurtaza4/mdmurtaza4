import pytest

from elixir_studio.captions import build_ass, group_cues
from elixir_studio.edl import EDL, CaptionSettings, Segment, Word, map_time, remap_words
from elixir_studio.hardware import plan_whisper
from elixir_studio.render import build_filtergraph
from elixir_studio.silence import keep_segments


def W(t, s, e, p=0.9):
    return Word(text=t, start=s, end=e, probability=p)


def test_segment_must_be_ordered():
    with pytest.raises(ValueError):
        Segment(start=2, end=1)


def test_edl_rejects_overlaps():
    with pytest.raises(ValueError):
        EDL(source="x.mp4", source_duration=10, segments=[Segment(start=0, end=5), Segment(start=4, end=6)])


def test_edl_round_trip(tmp_path):
    edl = EDL(source="x.mp4", source_duration=10, segments=[Segment(start=1, end=3)], words=[W("hi", 1.1, 1.4)])
    edl.save(tmp_path / "p.json")
    assert EDL.load(tmp_path / "p.json") == edl
    assert not list(tmp_path.glob(".edl-*"))  # atomic save leaves no temp files


def test_time_mapping_through_cuts():
    segs = [Segment(start=1, end=3), Segment(start=5, end=6)]
    assert map_time(2, segs) == 1
    assert map_time(5.5, segs) == 2.5
    assert map_time(4, segs) is None
    words = remap_words([W("a", 1.0, 1.5), W("b", 5.2, 5.6), W("gone", 3.5, 4.5)], segs)
    assert [w.text for w in words] == ["a", "b"]
    assert words[1].start == pytest.approx(2.2)


def test_keep_segments_trims_pauses_with_padding():
    segs = keep_segments(10, [(0, 2), (4, 7)], padding=0.15)
    assert [(s.start, s.end) for s in segs] == [(1.85, 4.15), (6.85, 10)]


def test_keep_segments_never_cuts_through_words():
    # A "silence" (quiet word) overlapping a transcribed word must not be removed over the word.
    segs = keep_segments(10, [(3, 6)], words=[W("soft", 4.0, 4.4)], padding=0.1)
    kept = [(s.start, s.end) for s in segs]
    assert any(s <= 4.0 and e >= 4.4 for s, e in kept)


def test_keep_segments_ignores_tiny_gaps():
    segs = keep_segments(5, [(2, 2.4)], padding=0.15)
    assert [(s.start, s.end) for s in segs] == [(0, 5)]


def test_cue_grouping_limits():
    words = [W(f"word{i}", i * 0.3, i * 0.3 + 0.25) for i in range(12)]
    cues = group_cues(words, CaptionSettings(max_words=4, max_chars=100))
    assert all(len(c.words) <= 4 for c in cues)
    assert all(a.end <= b.start for a, b in zip(cues, cues[1:], strict=False))


def test_ass_highlights_active_word_and_escapes():
    ass = build_ass([W("Hello", 0, 0.4), W("{world}", 0.5, 0.9)], "vertical", CaptionSettings())
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    assert ass.count("Dialogue:") == 2
    assert "{world}" not in ass and "(world)" in ass


@pytest.mark.parametrize(
    "vram,cuda,expect",
    [(None, False, ("small", "cpu")), (3500, True, ("small", "cuda")), (5000, True, ("medium", "cuda")),
     (7800, True, ("large-v3-turbo", "cuda")), (1200, True, ("small", "cpu"))],
)
def test_whisper_plan(vram, cuda, expect):
    p = plan_whisper(vram, cuda, 8)
    assert (p.model, p.device) == expect


def test_filtergraph_structure():
    edl = EDL(source="x.mp4", source_duration=10, segments=[Segment(start=0, end=2), Segment(start=4, end=6)])
    g = build_filtergraph(edl, has_captions=True, has_logo=True)
    assert "concat=n=2:v=1:a=1" in g
    assert "ass=captions.ass" in g and "loudnorm" in g and "[1:v]" in g
    assert "fps=30" in g
