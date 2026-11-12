from podcast_digest.sections import chinese_number, split_sections


def test_split_sections_by_markers():
    script = "开场。\n\n问题一：为什么？回答。\n\n问题十二：怎么办？回答。\n\n结语：总结。"
    sections = split_sections(script)
    assert [s.label for s in sections] == ["opening", "问题一", "问题十二", "结语"]
    assert sections[1].heading == "为什么？" and sections[1].is_question and not sections[3].is_question
    assert sections[2].text.startswith("问题十二：")


def test_script_without_markers_is_one_section():
    assert [s.label for s in split_sections("只有一段。")] == ["opening"]


def test_chinese_numbers():
    assert [chinese_number(n) for n in (1, 9, 10, 11, 13, 20, 21)] == ["一", "九", "十", "十一", "十三", "二十", "二十一"]


def test_slide_points_match_labels_loosely_or_by_order():
    from podcast_digest import summarize

    sections = split_sections("开场。\n\n问题一：为什么？答。\n\n结语：总结。")[1:]

    class LLM:
        name = "x"

        def __init__(self, labels):
            self.labels = labels

        def complete_json(self, system, user, name, schema):
            return {"slides": [{"label": l, "question": f"Q{i}", "insight": f"I{i}"} for i, l in enumerate(self.labels)]}

    loose = summarize.slide_points(LLM(["[问题一]", "结语："]), sections)
    assert [(p["label"], p["insight"]) for p in loose] == [("问题一", "I0"), ("结语", "I1")]
    by_order = summarize.slide_points(LLM(["Q1", "Wrap"]), sections)
    assert [p["insight"] for p in by_order] == ["I0", "I1"]
