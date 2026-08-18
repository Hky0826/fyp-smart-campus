"""Shared, catalog-driven navigation resolution for every chatbot entrypoint."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from types import SimpleNamespace
from typing import Any
import httpx
from sqlalchemy.orm import joinedload

_CONVERSATIONAL_PREFIX = re.compile(
    r"^(?:please\s+)?(?:can\s+you\s+(?:tell\s+me\s+)?|could\s+you\s+(?:tell\s+me\s+)?|would\s+you\s+(?:tell\s+me\s+)?|show\s+me\s+)?"
    r"(?:where(?:\s+is|\s+are|\s+can\s+i\s+(?:find|get))?|take\s+me\s+to|navigate\s+to|directions?\s+to|how\s+(?:do\s+i|can\s+i)\s+get\s+to)\s*",
    re.IGNORECASE,
)
_LEADING_FILLERS = re.compile(r"^(?:is|are|located|at|the|a|an|please)\s+", re.IGNORECASE)
_TRAILING_FILLERS = re.compile(r"\s+(?:please|for\s+me)$", re.IGNORECASE)
_WASHROOM_WORDS = {"bathroom", "restroom", "toilet", "washroom", "washrooms"}
_WASHROOM_TYPES = {"WASHROOM", "RESTROOM"}
_FOOD_WORDS = {"food", "eat", "eating", "meal", "meals", "canteen", "cafeteria", "cafe", "coffee"}
_FOOD_TYPES = {"FOOD", "CAFETERIA"}
_LIFT_WORDS = {"lift", "lifts", "elevator", "elevators"}
_LIFT_TYPES = {"ELEVATOR"}
_STAIR_WORDS = {"stair", "stairs", "stairwell", "stairwells"}
_STAIR_TYPES = {"STAIRWELL"}
_GENDER_WORDS = {"men", "mens", "male", "women", "womens", "female", "unisex", "accessible", "s"}
_COMPOUND_ALIASES = {
    "board room": "boardroom",
    "board rooms": "boardrooms",
    "class room": "classroom",
    "class rooms": "classrooms",
    "wash room": "washroom",
    "wash rooms": "washrooms",
    "caffeteria": "cafeteria",
    "cafateria": "cafeteria",
    "cafiteria": "cafeteria",
}

from RagChatbot.config import rag_settings

MAPPING_MICROSERVICE_URL = getattr(rag_settings, "MAPPING_MICROSERVICE_URL", "http://127.0.0.1:5000")
NAVIGATION_API_KEY = getattr(rag_settings, "NAVIGATION_API_KEY", "campus_navigation_api_key_2026")


class NavigationError(Exception):
    pass


class NoRouteError(NavigationError):
    pass


class StartLocationRequired(NavigationError):
    pass


class DestinationAmbiguous(NavigationError):
    def __init__(self, candidates):
        self.candidates = candidates
        super().__init__("Destination label matches more than one node")


@dataclass(frozen=True)
class GraphNodeSnapshot:
    node_id: int
    floorplan_id: int
    x: float
    y: float
    label: str = ""
    node_type: str = "OTHER"
    accessible: bool = True
    allowed_roles: frozenset[str] = frozenset()
    scale_ratio: float = 1.0
    building: str | None = None
    floor: int | None = None


@dataclass(frozen=True)
class MapSnapshot:
    nodes: tuple[GraphNodeSnapshot, ...]


def get_map_snapshot(db) -> MapSnapshot:
    """Load lightweight node snapshot with RBAC permissions from database."""
    if db is None:
        return MapSnapshot(())
    from app.models.models import Node, NodeRBAC

    db_nodes = (
        db.query(Node)
        .options(joinedload(Node.floorplan))
        .order_by(Node.node_id)
        .all()
    )
    if not db_nodes:
        return MapSnapshot(())

    ids = [n.node_id for n in db_nodes]
    node_roles: dict[int, set[str]] = {}
    for row in db.query(NodeRBAC).filter(NodeRBAC.node_id.in_(ids)).all():
        node_roles.setdefault(row.node_id, set()).add(str(getattr(row.role, "role_name", "")).upper())

    nodes = tuple(
        GraphNodeSnapshot(
            node_id=n.node_id,
            floorplan_id=n.floorplan_id,
            x=n.coord_x,
            y=n.coord_y,
            label=n.room_label or "",
            node_type=str(n.node_type or "OTHER"),
            accessible=str(n.is_accessible).upper() != "DENY",
            allowed_roles=frozenset(node_roles.get(n.node_id, set())),
            scale_ratio=float(getattr(n.floorplan, "scale_ratio", None) or 1.0),
            building=getattr(getattr(n.floorplan, "building", None), "building_name", None),
            floor=getattr(n.floorplan, "floor_level", None),
        )
        for n in db_nodes
    )
    return MapSnapshot(nodes)


def _normalise_label(value: str) -> str:
    value = re.sub(r"[^\w]+", " ", str(value or "").casefold(), flags=re.UNICODE)
    value = re.sub(r"\s+", " ", value).strip()
    for source, target in _COMPOUND_ALIASES.items():
        value = value.replace(source, target)
    words = [word[:-1] if len(word) > 3 and word.endswith("s") else word for word in value.split()]
    return " ".join(words)


def _compact(value: str) -> str:
    return _normalise_label(value).replace(" ", "")


def _destination_text(query: str) -> str:
    value = re.sub(r"\s+", " ", str(query or "").strip())
    value = value.rstrip("?.!,;:").strip()
    previous = None
    while value and value != previous:
        previous = value
        value = _CONVERSATIONAL_PREFIX.sub("", value, count=1).strip()
        value = _LEADING_FILLERS.sub("", value, count=1).strip()
    value = _TRAILING_FILLERS.sub("", value).strip()
    return value.rstrip("?.!,;:").strip()


def _node_type(node) -> str:
    return str(getattr(node, "node_type", "") or "").strip().upper()


def _node_allowed(node, roles) -> bool:
    if str(getattr(node, "accessible", True)).upper() in {"DENY", "FALSE", "0"}:
        return False
    allowed_roles = {str(role).upper() for role in (getattr(node, "allowed_roles", ()) or ())}
    role_set = {str(role).upper() for role in (roles or ())}
    return not allowed_roles or bool(allowed_roles & role_set) or "SUPER_ADMIN" in role_set


def _candidate_nodes(nodes, roles):
    return [
        node for node in nodes
        if _node_type(node) not in {"CORRIDOR", "ENTRANCE"} and _node_allowed(node, roles)
    ]


def _gender_from_washroom_query(value: str) -> str | None:
    text = str(value or "").casefold()
    compact = _compact(value)
    if re.search(r"\b(?:men'?s?|mens?|male)\b", text) or compact.startswith(("menwashroom", "menswashroom")):
        return "men"
    if re.search(r"\b(?:women'?s?|womens?|female)\b", text) or compact.startswith(("womenwashroom", "womenswashroom")):
        return "women"
    if re.search(r"\b(?:unisex|accessible)\b", text) or compact.startswith("unisex"):
        return "unisex"
    return None


def _category_matches(nodes, query: str, query_words: set[str]):
    if query_words & _WASHROOM_WORDS:
        washrooms = [node for node in nodes if _node_type(node) in _WASHROOM_TYPES]
        gender = _gender_from_washroom_query(query)
        if gender:
            washrooms = [node for node in washrooms if _gender_from_washroom_query(getattr(node, "label", "")) == gender]
        return sorted(washrooms, key=lambda node: (str(getattr(node, "label", "")).casefold(), getattr(node, "node_id", 0)))
    if query_words & _FOOD_WORDS:
        return sorted([node for node in nodes if _node_type(node) in _FOOD_TYPES], key=lambda node: (str(getattr(node, "label", "")).casefold(), getattr(node, "node_id", 0)))
    if query_words & _LIFT_WORDS:
        return sorted([node for node in nodes if _node_type(node) in _LIFT_TYPES], key=lambda node: (str(getattr(node, "label", "")).casefold(), getattr(node, "node_id", 0)))
    if query_words & _STAIR_WORDS:
        return sorted([node for node in nodes if _node_type(node) in _STAIR_TYPES], key=lambda node: (str(getattr(node, "label", "")).casefold(), getattr(node, "node_id", 0)))
    return None


def _is_category_only_query(query_words: set[str]) -> bool:
    category_words = _WASHROOM_WORDS | _FOOD_WORDS | _LIFT_WORDS | _STAIR_WORDS
    return bool(query_words & category_words) and query_words <= (category_words | _GENDER_WORDS | {"nearby", "nearest", "closest"})


def _score_destination(query: str, label: str) -> float:
    query_normalised = _normalise_label(query)
    label_normalised = _normalise_label(label)
    if not query_normalised or not label_normalised:
        return 0.0
    if query_normalised == label_normalised or _compact(query) == _compact(label):
        return 1.0
    query_words = set(query_normalised.split())
    label_words = set(label_normalised.split())
    if query_words and query_words <= label_words:
        return 0.94
    left, right = _compact(query), _compact(label)
    if left in right or right in left:
        extra_characters = max(0, len(right) - len(left)) if left in right else max(0, len(left) - len(right))
        return max(0.80, 0.94 - min(extra_characters, 14) * 0.01)
    return SequenceMatcher(None, left, right).ratio()


def _destination_matches(nodes, label: str, roles=()):
    candidates = _candidate_nodes(nodes, roles)
    query = _normalise_label(label)
    query_words = set(query.split())

    if _is_category_only_query(query_words):
        category_matches = _category_matches(candidates, label, query_words)
        if category_matches is not None:
            return category_matches

    scored = [(node, _score_destination(label, getattr(node, "label", ""))) for node in candidates]
    exact = [node for node, score in scored if score >= 0.999]
    if exact:
        return exact
    strong = [(node, score) for node, score in scored if score >= 0.80]
    if strong:
        non_entrances = [item for item in strong if _node_type(item[0]) != "ENTRANCE"]
        if non_entrances:
            strong = non_entrances
        best = max(score for _, score in strong)
        return [node for node, score in strong if score >= max(0.80, best - 0.08)]

    category_matches = _category_matches(candidates, label, query_words)
    if category_matches is not None:
        return category_matches
    return []


def _similar_destination_matches(nodes, label: str, roles=()):
    candidates = [
        (node, _score_destination(label, getattr(node, "label", "")))
        for node in _candidate_nodes(nodes, roles)
    ]
    strong = [(node, score) for node, score in candidates if score >= 0.78]
    if not strong:
        return []
    best = max(score for _, score in strong)
    return [node for node, score in strong if score >= max(0.72, best - 0.08)]


def is_navigation_query(query: str, *, db=None) -> bool:
    """Cheap deterministic route gate shared by text, audio, and Live."""
    text = " ".join(str(query or "").split())
    if re.search(r"\b(?:where\s+(?:is|are|can\s+i\s+(?:find|get))|can\s+you\s+tell\s+me\s+where|take\s+me\s+to|navigate\s+to|directions?\s+to|how\s+(?:do\s+i|can\s+i)\s+get\s+to|location\s+of|find\s+the)\b", text, re.IGNORECASE):
        return True
    if db is None:
        return False
    try:
        snapshot = get_map_snapshot(db)
        return bool(_destination_matches(snapshot.nodes, _destination_text(text)))
    except Exception:
        return False


def _is_nearest_query(value: str) -> bool:
    return bool(re.search(r"\b(?:nearest|closest|nearby)\b", value, re.IGNORECASE))


def _candidate_data(node) -> dict:
    return {
        "node_id": node.node_id,
        "label": node.label,
        "floorplan_id": node.floorplan_id,
        "node_type": node.node_type,
    }


def _call_route_microservice(*, destination_node_id: int, start_node_id: int | None, roles: list[str] | tuple[str, ...]) -> dict:
    """Call Node.js Mapping Microservice route calculation."""
    if start_node_id is None:
        raise StartLocationRequired("Start location required")

    primary_role = roles[0] if roles else "VISITOR"
    payload = {
        "current_location": start_node_id,
        "destination_node": destination_node_id,
        "rbac_role": primary_role,
        "start_node_id": start_node_id,
        "destination_node_id": destination_node_id,
        "roles": list(roles),
    }
    headers = {
        "x-api-key": NAVIGATION_API_KEY,
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                f"{MAPPING_MICROSERVICE_URL.rstrip('/')}/navigate",
                json=payload,
                headers=headers,
            )
            if resp.status_code == 200:
                return resp.json()

            try:
                err_data = resp.json()
                err_msg = err_data.get("error") or err_data.get("message") or err_data.get("detail") or "Navigation error"
            except Exception:
                err_msg = f"HTTP {resp.status_code}"

            if resp.status_code == 422:
                raise StartLocationRequired(err_msg)
            if resp.status_code == 404:
                raise NoRouteError(err_msg)
            raise NavigationError(f"Route calculation failed ({resp.status_code}): {err_msg}")
    except (httpx.ConnectError, httpx.TimeoutException):
        raise NavigationError("Mapping microservice is unreachable")


def calculate_navigation(query: str, *, db, context):
    """Resolve and calculate one trusted, RBAC-filtered campus route via Mapping Microservice."""
    label = _destination_text(query)
    snapshot = get_map_snapshot(db)
    roles = getattr(context, "roles", ())
    matches = _destination_matches(snapshot.nodes, label, roles)
    
    # Resolve start node id from device or user
    start_node_id = None
    if getattr(context, "device_node_id", None) is not None:
        start_node_id = context.device_node_id
    elif getattr(context, "user_id", None) is not None:
        from app.models.models import User
        user = db.query(User).filter(User.user_id == context.user_id, User.is_active.is_(True)).first()
        if user and getattr(user, "last_known_location", None):
            start_node_id = user.last_known_location

    route = None
    if len(matches) > 1 and _is_nearest_query(label):
        route_candidates = []
        start_required = False
        for node in matches:
            try:
                candidate_route = _call_route_microservice(
                    destination_node_id=node.node_id,
                    start_node_id=start_node_id,
                    roles=list(roles),
                )
                route_candidates.append((candidate_route, node))
            except StartLocationRequired:
                start_required = True
            except (NoRouteError, NavigationError):
                continue
        if route_candidates:
            route, selected = min(route_candidates, key=lambda item: item[0].get("route_summary", {}).get("total_distance_m", float("inf")))
            matches = [selected]
        elif start_required:
            category_words = set(_normalise_label(label).split())
            category = "lift" if category_words & _LIFT_WORDS else "stairwell" if category_words & _STAIR_WORDS else "facility"
            return {
                "intent": "NAVIGATIONAL",
                "navigation_target": {"candidates": [_candidate_data(node) for node in matches]},
                "answer": f"I found several {category} locations, but I need your current campus location to determine which is nearest.",
            }

    if len(matches) != 1:
        if not matches:
            suggestions = _similar_destination_matches(snapshot.nodes, label, roles)
            if suggestions:
                suggestion_data = [_candidate_data(node) for node in suggestions]
                if len(suggestion_data) == 1:
                    answer = f"Did you mean {suggestion_data[0]['label']}? Is that the place you want to go?"
                else:
                    labels = ", ".join(item["label"] for item in suggestion_data)
                    answer = f"Which place did you mean: {labels}?"
                return {
                    "intent": "NAVIGATIONAL",
                    "confirmation_required": True,
                    "navigation_target": {"confirmation_required": True, "candidates": suggestion_data},
                    "answer": answer,
                }
        if len(matches) > 1:
            query_words = set(_normalise_label(label).split())
            labels = ", ".join(node.label for node in matches)
            answer = (
                f"I found these food destinations: {labels}. Which one do you mean?"
                if query_words & _FOOD_WORDS
                else f"I found these washrooms: {labels}. Which one do you mean?"
                if query_words & _WASHROOM_WORDS
                else f"I found these destinations: {labels}. Which one do you mean?"
            )
            return {
                "intent": "NAVIGATIONAL",
                "navigation_target": {"candidates": [_candidate_data(node) for node in matches]},
                "answer": answer,
            }
        return {
            "intent": "NAVIGATIONAL",
            "navigation_target": {"candidates": []},
            "answer": f"I couldn't find a mapped campus destination matching '{label}'. Please check the name or ask for a nearby facility such as a lift, stairwell, washroom, or cafeteria.",
        }

    try:
        if route is None:
            route = _call_route_microservice(
                destination_node_id=matches[0].node_id,
                start_node_id=start_node_id,
                roles=list(roles),
            )
    except StartLocationRequired:
        return {"intent": "NAVIGATIONAL", "navigation_target": {"node_id": matches[0].node_id, "label": matches[0].label}, "answer": "I found the destination, but I need your current campus location to give directions."}
    except NoRouteError:
        return {"intent": "NAVIGATIONAL", "navigation_target": {"node_id": matches[0].node_id, "label": matches[0].label}, "answer": "I could not find an accessible route to that destination."}
    except NavigationError as exc:
        return {"intent": "NAVIGATIONAL", "navigation_target": {"node_id": matches[0].node_id, "label": matches[0].label}, "answer": f"Navigation service error: {str(exc)}"}

    summary = route.get("route_summary", {})
    speakable = " ".join(step["instruction"] for step in route.get("instructions", []) if step.get("instruction"))
    return {
        "intent": "NAVIGATIONAL",
        "navigation_target": {"node_id": matches[0].node_id, "label": matches[0].label},
        "navigation": route,
        "route_summary": summary,
        "instructions": route.get("instructions", []),
        "visualisation": route.get("visualisation", {}),
        "answer": speakable,
    }
