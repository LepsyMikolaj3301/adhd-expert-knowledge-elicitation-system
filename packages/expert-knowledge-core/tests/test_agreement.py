from expert_knowledge_core.agreement import (
    Mark,
    expert_directions,
    group_marks,
    iou,
    render_agreement,
    summarise,
)


def mark(id, expert, a, b, direction="toward"):
    return Mark(id, expert, (a, b), direction)


def ids(groups):
    return [[m.id for m in g] for g in groups]


def test_iou():
    assert iou((0, 10), (0, 10)) == 1
    assert iou((0, 10), (5, 15)) == 5 / 15
    assert iou((0, 10), (10, 20)) == 0
    assert iou((3, 3), (3, 3)) == 0


def test_identical_and_mostly_overlapping_spans_group_but_a_graze_does_not():
    marks = [
        mark("a", "e1", 10, 30),
        mark("b", "e2", 10, 30),  # identical
        mark("c", "e3", 12, 32),  # 18/22 of a
        mark("d", "e4", 28, 50),  # grazes a and c
    ]
    assert ids(group_marks(marks)) == [["a", "b", "c"], ["d"]]


def test_links_chain_through_a_middle_highlight():
    marks = [mark("a", "e1", 0, 10), mark("b", "e2", 3, 13), mark("c", "e3", 6, 16)]
    assert iou(marks[0].span, marks[2].span) < 0.5
    assert ids(group_marks(marks)) == [["a", "b", "c"]]


def test_the_threshold_is_a_parameter():
    marks = [mark("a", "e1", 0, 10), mark("b", "e2", 5, 15)]
    assert ids(group_marks(marks, 0.5)) == [["a"], ["b"]]
    assert ids(group_marks(marks, 0.3)) == [["a", "b"]]


def test_groups_keep_the_order_of_first_appearance():
    marks = [mark("a", "e1", 50, 60), mark("b", "e1", 0, 10), mark("c", "e2", 50, 60)]
    assert ids(group_marks(marks)) == [["a", "c"], ["b"]]


def test_an_expert_with_two_highlights_in_a_group_counts_once():
    group = [mark("a", "e1", 0, 10), mark("b", "e1", 0, 9), mark("c", "e2", 0, 10)]
    summary = summarise(group, n_answered=4)
    assert (summary.k, summary.n) == (2, 4)
    assert summary.counts == {"toward": 2}


def test_an_expert_who_contradicts_themselves_is_mixed():
    group = [mark("a", "e1", 0, 10, "toward"), mark("b", "e1", 0, 10, "away")]
    assert expert_directions(group) == {"e1": "mixed"}
    summary = summarise(group, n_answered=1)
    assert summary.counts == {"mixed": 1} and summary.label == "single"


def test_three_of_four_agree_and_one_dissents_is_split():
    group = [
        mark("a", "e1", 0, 10, "toward"),
        mark("b", "e2", 0, 10, "toward"),
        mark("c", "e3", 0, 10, "away"),
    ]
    summary = summarise(group, n_answered=4)
    assert (summary.k, summary.n, summary.label) == (3, 4, "split")
    assert summary.counts == {"toward": 2, "away": 1}
    assert render_agreement(summary) == (
        "Agreement: 3 of 4 clinicians who answered this text cited it; "
        "2 toward, 1 away (split)."
    )


def test_labels():
    same = [mark(str(i), f"e{i}", 0, 10, "toward") for i in range(4)]
    assert summarise(same, 4).label == "agreed"
    assert summarise(same[:1], 4).label == "single"
    mild = [
        mark("a", "e1", 0, 10, "toward"),
        mark("b", "e2", 0, 10, "toward"),
        mark("c", "e3", 0, 10, "neutral"),
    ]
    assert summarise(mild, 3).label == "leaning"  # 2 of 3 is under three quarters


def test_a_highlight_without_a_direction_reads_as_unclear():
    summary = summarise([mark("a", "e1", 0, 10, None), mark("b", "e2", 0, 10, "unclear")], 2)
    assert summary.counts == {"unclear": 2} and summary.label == "agreed"


def test_n_never_falls_below_k():
    group = [mark("a", "e1", 0, 10), mark("b", "e2", 0, 10)]
    assert summarise(group, n_answered=0).n == 2


def test_the_span_is_the_union_and_a_lone_expert_reads_in_the_singular():
    group = [mark("a", "e1", 10, 20), mark("b", "e2", 12, 25)]
    assert summarise(group, 2).span == (10, 25)
    one = summarise([mark("a", "e1", 0, 5)], 1)
    assert render_agreement(one) == (
        "Agreement: 1 of 1 clinician who answered this text cited it; 1 toward (single)."
    )
