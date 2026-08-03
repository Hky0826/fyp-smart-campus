from types import SimpleNamespace

from RagChatbot.services.chat_service import _confirmed_navigation_label


class _FakeQuery:
    def __init__(self, record):
        self.record = record

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self.record


class _FakeDb:
    def __init__(self, record):
        self.record = record

    def query(self, model):
        return _FakeQuery(self.record)


def test_yes_confirms_latest_fuzzy_destination():
    db = _FakeDb(
        SimpleNamespace(
            response_text="Did you mean Boardroom 1? Is that the place you want to go?"
        )
    )

    assert _confirmed_navigation_label("yes", db, 42) == "Boardroom 1"


def test_non_confirmation_reply_does_not_trigger_navigation():
    db = _FakeDb(
        SimpleNamespace(
            response_text="Did you mean Boardroom 1? Is that the place you want to go?"
        )
    )

    assert _confirmed_navigation_label("what is the fee?", db, 42) is None


def test_washroom_category_reply_resolves_to_gendered_destination():
    db = _FakeDb(
        SimpleNamespace(
            response_text="I found these washrooms: Men's Washroom, Women's Washroom. Which one do you mean?"
        )
    )

    assert _confirmed_navigation_label("men", db, 42) == "Men's Washroom"
