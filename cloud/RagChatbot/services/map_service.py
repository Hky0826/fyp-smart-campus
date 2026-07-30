"""In-process adapter from RAG navigation intents to the cloud map service."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from cloud.mapping_and_notification.mapping.navigation_service import DestinationAmbiguous, NavigationService, NoRouteError, StartLocationRequired
from cloud.mapping_and_notification.mapping.repository import MapRepository


_NAVIGATION_PREFIX = re.compile(
    r"^(?:how do i get to|how can i get to|where is|take me to|navigate to|directions to)\s+",
    re.IGNORECASE,
)
_LEADING_ARTICLE = re.compile(r"^(?:the|a|an)\s+", re.IGNORECASE)
_WASHROOM_WORDS = {"bathroom", "restroom", "toilet", "washroom", "washrooms"}
_WASHROOM_TYPES = {"WASHROOM", "RESTROOM"}


def _destination_text(query: str) -> str:
    value = re.sub(r"\s+", " ", query.strip())
    value = _NAVIGATION_PREFIX.sub("", value)
    value = _LEADING_ARTICLE.sub("", value)
    return value.rstrip("?.!").strip()


def _normalise_label(value: str) -> str:
    """Normalise labels enough to match natural-language destination names."""
    return re.sub(r"[^\w]+", " ", value.casefold(), flags=re.UNICODE).strip()


def _destination_matches(nodes, label: str):
    """Find exact labels first, then common facility aliases."""
    nodes = [node for node in nodes if str(node.node_type).strip().upper() != "CORRIDOR"]
    target = _normalise_label(label)
    exact = [node for node in nodes if _normalise_label(node.label) == target]
    if exact:
        return exact

    target_words = set(target.split())
    if target_words & _WASHROOM_WORDS:
        return [
            node
            for node in nodes
            if str(node.node_type).upper() in _WASHROOM_TYPES
            or bool(set(_normalise_label(node.label).split()) & _WASHROOM_WORDS)
        ]

    # Support labels such as "Cashier Counter" when the user says "cashier".
    return [
        node
        for node in nodes
        if target and target in _normalise_label(node.label).split()
    ]


def _destination_similarity(left: str, right: str) -> float:
    left_normalised = _normalise_label(left)
    right_normalised = _normalise_label(right)
    left_compact = left_normalised.replace(" ", "")
    right_compact = right_normalised.replace(" ", "")
    if not left_compact or not right_compact:
        return 0.0
    if left_compact in right_compact or right_compact in left_compact:
        return 0.9
    return SequenceMatcher(None, left_compact, right_compact).ratio()


def _similar_destination_matches(nodes, label: str):
    """Return close non-corridor labels that need user confirmation."""
    candidates = [
        (node, _destination_similarity(label, node.label))
        for node in nodes
        if str(node.node_type).strip().upper() != "CORRIDOR"
    ]
    candidates = [(node, score) for node, score in candidates if score >= 0.72]
    if not candidates:
        return []
    best_score = max(score for _, score in candidates)
    return [node for node, score in candidates if score >= max(0.72, best_score - 0.08)]


def calculate_navigation(query: str, *, db, context):
    """Resolve a canonical label and calculate a route without an HTTP hop.

    The trusted context supplies the user; query text can only select a unique
    destination label and can never select a role or arbitrary start node.
    """
    label = _destination_text(query)
    snapshot = MapRepository(db).snapshot()
    matches = _destination_matches(snapshot.nodes, label)
    if len(matches) != 1:
        if not matches:
            suggestions = _similar_destination_matches(snapshot.nodes, label)
            if suggestions:
                suggestion_data = [
                    {
                        "node_id": node.node_id,
                        "label": node.label,
                        "floorplan_id": node.floorplan_id,
                        "node_type": node.node_type,
                    }
                    for node in suggestions
                ]
                if len(suggestion_data) == 1:
                    answer = f"Did you mean {suggestion_data[0]['label']}? Is that the place you want to go?"
                else:
                    labels = ", ".join(item["label"] for item in suggestion_data)
                    answer = f"Did you mean one of these places: {labels}?"
                return {
                    "intent": "NAVIGATIONAL",
                    "confirmation_required": True,
                    "navigation_target": {
                        "confirmation_required": True,
                        "candidates": suggestion_data,
                    },
                    "answer": answer,
                }
        if len(matches) > 1:
            is_washroom_query = bool(set(_normalise_label(label).split()) & _WASHROOM_WORDS)
            answer = (
                "I found several washrooms. Please specify men's, women's, or unisex washroom."
                if is_washroom_query
                else "Please specify which floor or building you mean."
            )
            return {"intent": "NAVIGATIONAL", "navigation_target": {"candidates": [{"node_id": n.node_id, "label": n.label, "floorplan_id": n.floorplan_id} for n in matches]}, "answer": answer}
        return None
    user = None
    user_id = getattr(context, "user_id", None)
    if user_id is not None:
        from app.models.models import User
        user = db.query(User).filter(User.user_id == user_id, User.is_active.is_(True)).first()
    try:
        route = NavigationService(db).calculate(destination_node_id=matches[0].node_id, user=user, roles=getattr(context, "roles", ()))
    except StartLocationRequired:
        return {"intent": "NAVIGATIONAL", "navigation_target": {"node_id": matches[0].node_id, "label": matches[0].label}, "answer": "I found the destination, but I need your current campus location to give directions."}
    except NoRouteError:
        return {"intent": "NAVIGATIONAL", "navigation_target": {"node_id": matches[0].node_id, "label": matches[0].label}, "answer": "I could not find an accessible route to that destination."}
    summary = route["route_summary"]
    speakable = " ".join(step["instruction"] for step in route["instructions"] if step.get("instruction"))
    return {"intent": "NAVIGATIONAL", "navigation_target": {"node_id": matches[0].node_id, "label": matches[0].label}, "navigation": route, "route_summary": summary, "instructions": route["instructions"], "visualisation": route["visualisation"], "answer": speakable}
