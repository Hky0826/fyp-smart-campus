from types import SimpleNamespace

from cloud.mapping_and_notification.mapping.navigation_service import NavigationService, StartLocationRequired


class _Query:
    def __init__(self, result):
        self.result = result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.result


class _Db:
    def __init__(self, *results):
        self.results = list(results)

    def query(self, model):
        return _Query(self.results.pop(0) if self.results else None)


def test_bound_device_origin_wins_over_stale_user_location():
    device_node = SimpleNamespace(node_id=10, room_label="Registered kiosk")
    stale_user_node = SimpleNamespace(node_id=20, room_label="Stale user location")
    db = _Db(device_node)

    result = NavigationService(db)._start(
        start_node_id=None,
        user=SimpleNamespace(last_known_location=20, last_seen=__import__("datetime").datetime.utcnow()),
        device=SimpleNamespace(node_id=10),
        allow_explicit=False,
    )

    assert result is device_node
    assert result is not stale_user_node


def test_invalid_device_origin_falls_back_to_fresh_user_location():
    user_node = SimpleNamespace(node_id=20, room_label="Fresh user location")
    db = _Db(None, user_node)

    result = NavigationService(db)._start(
        start_node_id=None,
        user=SimpleNamespace(last_known_location=20, last_seen=__import__("datetime").datetime.utcnow()),
        device=SimpleNamespace(node_id=999),
        allow_explicit=False,
    )

    assert result is user_node


def test_missing_origins_fail_safely():
    db = _Db(None)

    try:
        NavigationService(db)._start(start_node_id=None, user=None, device=None, allow_explicit=False)
    except StartLocationRequired as exc:
        assert "starting location" in str(exc).lower()
    else:
        raise AssertionError("missing navigation origins should require a current location")
