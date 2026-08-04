from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ConfigDict


class FloorplanCreate(BaseModel):
    building_id: int
    floor_level: int
    scale_ratio: float | None = None


class FloorplanPatch(BaseModel):
    floor_level: int | None = None
    scale_ratio: float | None = None


class GraphNodeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: int | None = None
    coord_x: float
    coord_y: float
    room_label: str
    node_type: str = "OTHER"
    is_accessible: str = "ALLOW"
    role_ids: list[int] = Field(default_factory=list)


class GraphEdgeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    edge_id: int | None = None
    source_node_id: int
    destination_node_id: int
    weight_distance: float = Field(ge=0)
    is_accessible: str = "ALLOW"
    is_bidirectional: bool = True
    custom_path: Any = None
    role_ids: list[int] = Field(default_factory=list)


class GraphUpdate(BaseModel):
    graph_version: int | None = Field(default=None, ge=0)
    nodes: list[GraphNodeInput] = Field(default_factory=list)
    edges: list[GraphEdgeInput] = Field(default_factory=list)


class RouteRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    start_node_id: int | None = None
    destination_node_id: int | None = None
    destination_label: str | None = None
    walking_speed: float = Field(default=1.2, gt=0, le=10)
    device_id: str | None = None
    # Cutover aliases. They are translated into the same service and never
    # treated as a trusted role or arbitrary user location.
    current_location: int | None = None
    destination_node: int | None = None
    rbac_role: str | None = None

    def canonical_start(self) -> int | None:
        return self.start_node_id if self.start_node_id is not None else self.current_location

    def canonical_destination_id(self) -> int | None:
        return self.destination_node_id if self.destination_node_id is not None else self.destination_node


class NotificationTestRequest(BaseModel):
    recipient_user_id: int
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1, max_length=10000)
    event_type: str = "test"
    email_delivery_mode: Literal["ethereal", "smtp"] | None = None


class RouteAndNotifyRequest(RouteRequest):
    recipient_user_id: int
    title: str = "Campus route notification"
    body: str | None = Field(default=None, min_length=1, max_length=10000)
    event_type: str = "appointment_routing"
    email_delivery_mode: Literal["ethereal", "smtp"] | None = None
