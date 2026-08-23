from app.core.confidence import ConfidenceEntry, aggregate_confidence, confirm, score_placeholder


def test_score_placeholder_returns_fixed_unconfirmed_score():
    entry = score_placeholder("some_node")
    assert entry.confirmed is False
    assert entry.score == 0.75


def test_confirm_marks_confirmed_and_sets_timestamp():
    entry = score_placeholder("some_node")
    confirmed = confirm(entry)
    assert confirmed.confirmed is True
    assert confirmed.confirmed_at is not None


def test_aggregate_excludes_unconfirmed_entries():
    entries = [
        ConfidenceEntry(node_name="a", score=0.9, confirmed=False),
        ConfidenceEntry(node_name="b", score=0.5, confirmed=True),
        ConfidenceEntry(node_name="c", score=0.7, confirmed=True),
    ]
    assert aggregate_confidence(entries) == (0.5 + 0.7) / 2


def test_aggregate_returns_none_not_zero_when_nothing_confirmed():
    entries = [ConfidenceEntry(node_name="a", score=0.9, confirmed=False)]
    assert aggregate_confidence(entries) is None


def test_aggregate_of_empty_list_is_none():
    assert aggregate_confidence([]) is None
