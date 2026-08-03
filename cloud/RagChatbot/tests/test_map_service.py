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
    assert "these washrooms" in result["answer"]


def test_gendered_washroom_query_selects_one_washroom(monkeypatch):
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
    result = map_service.calculate_navigation("men's washroom", db=object(), context=_context())

    assert result["navigation_target"]["label"] == "Men's Washroom"


def test_corridor_nodes_are_not_navigation_destinations(monkeypatch):
    nodes = (SimpleNamespace(node_id=26, label="Corridor", floorplan_id=5, node_type="CORRIDOR"),)

    class FakeRepository:
        def __init__(self, db):
            pass

        def snapshot(self):
            return SimpleNamespace(nodes=nodes)

    monkeypatch.setattr(map_service, "MapRepository", FakeRepository)

    result = map_service.calculate_navigation("Where is the corridor?", db=object(), context=_context())

    assert result["navigation_target"]["candidates"] == []
    assert "couldn't find a mapped campus destination" in result["answer"]


def test_single_compound_destination_auto_resolves(monkeypatch):
    nodes = (SimpleNamespace(node_id=11, label="Boardroom 1", floorplan_id=5, node_type="HALL"),)

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
                "route_summary": {"start_node_id": 1, "start_label": "Kiosk", "destination_label": "Boardroom 1"},
                "instructions": [{"instruction": "Walk to the Boardroom 1."}],
                "visualisation": {},
            }

    monkeypatch.setattr(map_service, "MapRepository", FakeRepository)
    monkeypatch.setattr(map_service, "NavigationService", FakeNavigationService)

    result = map_service.calculate_navigation("Where is the board room?", db=object(), context=_context())

    assert result["navigation_target"]["label"] == "Boardroom 1"
    assert result["route_summary"]["start_label"] == "Kiosk"
    assert "Walk to the Boardroom 1." in result["answer"]


def test_new_catalog_destination_auto_resolves_without_place_alias(monkeypatch):
    nodes = (SimpleNamespace(node_id=91, label="Delta Innovation Lab", floorplan_id=8, node_type="LAB"),)

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
                "route_summary": {"start_node_id": 1, "start_label": "Kiosk", "destination_label": "Delta Innovation Lab"},
                "instructions": [{"instruction": "Walk to the Delta Innovation Lab."}],
                "visualisation": {},
            }

    monkeypatch.setattr(map_service, "MapRepository", FakeRepository)
    monkeypatch.setattr(map_service, "NavigationService", FakeNavigationService)

    result = map_service.calculate_navigation("Where is the delta innovation lab?", db=object(), context=_context())

    assert result["navigation_target"]["label"] == "Delta Innovation Lab"


def test_food_query_returns_food_and_cafeteria_candidates(monkeypatch):
    nodes = (
        SimpleNamespace(node_id=31, label="Food Court", floorplan_id=5, node_type="FOOD"),
        SimpleNamespace(node_id=32, label="Cafeteria", floorplan_id=5, node_type="CAFETERIA"),
        SimpleNamespace(node_id=33, label="Private Dining", floorplan_id=5, node_type="FOOD", allowed_roles=frozenset({"ADMIN"})),
    )

    class FakeRepository:
        def __init__(self, db):
            pass

        def snapshot(self):
            return SimpleNamespace(nodes=nodes)

    monkeypatch.setattr(map_service, "MapRepository", FakeRepository)
    result = map_service.calculate_navigation("Where can I get food?", db=object(), context=_context())

    assert [item["label"] for item in result["navigation_target"]["candidates"]] == ["Cafeteria", "Food Court"]
    assert "food destinations" in result["answer"]


def test_stt_filler_and_typo_variations_match_destination(monkeypatch):
    nodes = (SimpleNamespace(node_id=41, label="Cafeteria", floorplan_id=5, node_type="CAFETERIA"),)

    class FakeRepository:
        def __init__(self, db):
            pass

        def snapshot(self):
            return SimpleNamespace(nodes=nodes)

    class FakeNavigationService:
        def __init__(self, db):
            pass

        def calculate(self, **kwargs):
            return {"route_summary": {"start_node_id": 1, "start_label": "Kiosk"}, "instructions": [], "visualisation": {}}

    monkeypatch.setattr(map_service, "MapRepository", FakeRepository)
    monkeypatch.setattr(map_service, "NavigationService", FakeNavigationService)
    result = map_service.calculate_navigation("Can you tell me where is the cafateria please?", db=object(), context=_context())

    assert result["navigation_target"]["label"] == "Cafeteria"


def test_nearest_lift_compares_routes(monkeypatch):
    nodes = (
        SimpleNamespace(node_id=19, label="Elevator", floorplan_id=5, node_type="ELEVATOR"),
        SimpleNamespace(node_id=20, label="Elevator", floorplan_id=6, node_type="ELEVATOR"),
    )

    class FakeRepository:
        def __init__(self, db):
            pass

        def snapshot(self):
            return SimpleNamespace(nodes=nodes)

    class FakeNavigationService:
        def __init__(self, db):
            pass

        def calculate(self, **kwargs):
            node_id = kwargs["destination_node_id"]
            return {
                "route_summary": {"start_node_id": 1, "start_label": "Kiosk", "total_distance_m": 10 if node_id == 19 else 25},
                "instructions": [{"instruction": f"Walk to Elevator {node_id}."}],
                "visualisation": {},
            }

    monkeypatch.setattr(map_service, "MapRepository", FakeRepository)
    monkeypatch.setattr(map_service, "NavigationService", FakeNavigationService)
    result = map_service.calculate_navigation("where is the nearest lift", db=object(), context=_context())

    assert result["navigation_target"]["node_id"] == 19
    assert result["route_summary"]["total_distance_m"] == 10


def test_unknown_navigation_destination_has_explicit_feedback(monkeypatch):
    class FakeRepository:
        def __init__(self, db):
            pass

        def snapshot(self):
            return SimpleNamespace(nodes=())

    monkeypatch.setattr(map_service, "MapRepository", FakeRepository)
    result = map_service.calculate_navigation("where is delta lab", db=object(), context=_context())

    assert result["navigation_target"]["candidates"] == []
    assert "couldn't find a mapped campus destination" in result["answer"]
