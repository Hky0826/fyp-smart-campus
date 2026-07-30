from types import SimpleNamespace

from RagChatbot.services import map_service


def _context():
    return SimpleNamespace(user_id=None, roles=())


def test_destination_text_removes_leading_article():
    assert map_service._destination_text("Where is the cashier?") == "cashier"


def test_cashier_query_matches_stored_label(monkeypatch):
    nodes = (SimpleNamespace(node_id=7, label="Cashier", floorplan_id=5, node_type="OFFICE"),)

    class FakeRepository:
        def __init__(self, db):
            pass

        def snapshot(self):
            return SimpleNamespace(nodes=nodes)

    class FakeNavigationService:
        def __init__(self, db):
            pass

        def calculate(self, **kwargs):
            return {
                "route_summary": {"destination_label": "Cashier"},
                "instructions": [{"instruction": "Walk to the Cashier."}],
                "visualisation": {},
            }

    monkeypatch.setattr(map_service, "MapRepository", FakeRepository)
    monkeypatch.setattr(map_service, "NavigationService", FakeNavigationService)

    result = map_service.calculate_navigation("Where is the cashier?", db=object(), context=_context())

    assert result["navigation_target"]["label"] == "Cashier"
    assert result["answer"] == "Walk to the Cashier."


def test_toilet_query_returns_washroom_candidates(monkeypatch):
    nodes = (
        SimpleNamespace(node_id=16, label="Men's Washroom", floorplan_id=5, node_type="WASHROOM"),
        SimpleNamespace(node_id=17, label="Women's Washroom", floorplan_id=5, node_type="WASHROOM"),
        SimpleNamespace(node_id=18, label="Unisex Washroom", floorplan_id=5, node_type="WASHROOM"),
    )

    class FakeRepository:
        def __init__(self, db):
            pass

        def snapshot(self):
            return SimpleNamespace(nodes=nodes)

    monkeypatch.setattr(map_service, "MapRepository", FakeRepository)

    result = map_service.calculate_navigation("Where is the toilet?", db=object(), context=_context())

    assert len(result["navigation_target"]["candidates"]) == 3
    assert "several washrooms" in result["answer"]


def test_corridor_nodes_are_not_navigation_destinations(monkeypatch):
    nodes = (SimpleNamespace(node_id=26, label="Corridor", floorplan_id=5, node_type="CORRIDOR"),)

    class FakeRepository:
        def __init__(self, db):
            pass

        def snapshot(self):
            return SimpleNamespace(nodes=nodes)

    monkeypatch.setattr(map_service, "MapRepository", FakeRepository)

    assert map_service.calculate_navigation("Where is the corridor?", db=object(), context=_context()) is None


def test_similar_destination_requires_confirmation(monkeypatch):
    nodes = (SimpleNamespace(node_id=11, label="Boardroom 1", floorplan_id=5, node_type="HALL"),)

    class FakeRepository:
        def __init__(self, db):
            pass

        def snapshot(self):
            return SimpleNamespace(nodes=nodes)

    monkeypatch.setattr(map_service, "MapRepository", FakeRepository)

    result = map_service.calculate_navigation("Where is the board room?", db=object(), context=_context())

    assert result["confirmation_required"] is True
    assert result["navigation_target"]["candidates"][0]["label"] == "Boardroom 1"
    assert "Did you mean Boardroom 1?" in result["answer"]
