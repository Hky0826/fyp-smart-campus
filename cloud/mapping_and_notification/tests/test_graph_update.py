import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.models import Building, Floorplan, Node, Edge, NodeRBAC, EdgeRBAC, Role
from cloud.mapping_and_notification.api.maps import update_graph
from cloud.mapping_and_notification.api.schemas import GraphUpdate, GraphNodeInput, GraphEdgeInput

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    building = Building(building_id=1, building_name="Test Building")
    floorplan = Floorplan(floorplan_id=1, building_id=1, floor_level=1, image_path="test.png", graph_version=1)
    role_student = Role(role_id=1, role_name="STUDENT")
    role_staff = Role(role_id=2, role_name="STAFF")
    
    session.add(building)
    session.add(floorplan)
    session.add(role_student)
    session.add(role_staff)
    session.commit()
    
    yield session
    session.close()

def test_update_graph_new_nodes_and_edges(db_session):
    payload = GraphUpdate(
        graph_version=1,
        nodes=[
            GraphNodeInput(node_id=-1, coord_x=10.0, coord_y=20.0, room_label="Room A", node_type="CLASSROOM", is_accessible="ALLOW", role_ids=[1, 2]),
            GraphNodeInput(node_id=-2, coord_x=30.0, coord_y=40.0, room_label="Room B", node_type="OFFICE", is_accessible="ALLOW", role_ids=[2])
        ],
        edges=[
            GraphEdgeInput(edge_id=None, source_node_id=-1, destination_node_id=-2, weight_distance=5.0, is_accessible="ALLOW", is_bidirectional=True, role_ids=[2])
        ]
    )

    result = update_graph(floorplan_id=1, payload=payload, db=db_session, _admin=None)

    assert result["floorplan_id"] == 1
    assert result["graph_version"] == 2
    assert len(result["node_ids"]) == 2
    assert result["edge_count"] == 1

    nodes = db_session.query(Node).filter(Node.floorplan_id == 1).all()
    assert len(nodes) == 2
    
    node_a = next(n for n in nodes if n.room_label == "Room A")
    node_b = next(n for n in nodes if n.room_label == "Room B")

    rbac_a = [r.role_id for r in db_session.query(NodeRBAC).filter(NodeRBAC.node_id == node_a.node_id).all()]
    rbac_b = [r.role_id for r in db_session.query(NodeRBAC).filter(NodeRBAC.node_id == node_b.node_id).all()]
    assert set(rbac_a) == {1, 2}
    assert set(rbac_b) == {2}

    edges = db_session.query(Edge).all()
    assert len(edges) == 1
    edge = edges[0]
    assert edge.source_node_id == node_a.node_id
    assert edge.destination_node_id == node_b.node_id

    edge_rbac = [r.role_id for r in db_session.query(EdgeRBAC).filter(EdgeRBAC.edge_id == edge.edge_id).all()]
    assert set(edge_rbac) == {2}
