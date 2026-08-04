from cloud.mapping_and_notification.notifications.builder import build_notification
from cloud.mapping_and_notification.notifications.broker import Broker
from cloud.mapping_and_notification.notifications.templates import visitor_email


def test_notification_builder_has_unique_id_and_safe_template():
    first = build_notification(recipient_user_id=7, title="Route", body="Walk to room")
    second = build_notification(recipient_user_id=7, title="Route", body="Walk to room")
    assert first.message_id != second.message_id
    assert "<script>" not in visitor_email(visitor_name="<script>", destination="Room", instructions=["Walk"])


def test_notification_builder_preserves_email_delivery_mode():
    payload = build_notification(recipient_user_id=7, title="Route", body="Walk to room", email_delivery_mode="ethereal")

    assert payload.as_dict()["email_delivery_mode"] == "ethereal"


def test_notification_builder_preserves_route_context():
    context = {"instructions": [{"instruction": "Walk straight."}]}
    payload = build_notification(recipient_user_id=7, title="Route", body="Walk", route_context=context)

    assert payload.as_dict()["route_context"] == context


def test_email_service_uses_ethereal_transport(monkeypatch):
    from cloud.mapping_and_notification.notifications.email_service import EmailService

    sent = {}
    account = {"user": "ethereal-user", "pass": "ethereal-pass", "smtp": {"host": "smtp.ethereal.email", "port": 587, "secure": False}}
    monkeypatch.setattr(EmailService, "_get_ethereal_account", staticmethod(lambda: account))
    monkeypatch.setattr(EmailService, "_send_smtp", staticmethod(lambda **kwargs: sent.update(kwargs) or "250 OK"))

    ok, error, preview_url = EmailService().send(to="recipient@example.com", subject="Test", html="<p>Test</p>", email_delivery_mode="ethereal")

    assert ok is True
    assert error is None
    assert preview_url is None
    assert sent["host"] == "smtp.ethereal.email"
    assert sent["user"] == "ethereal-user"


def test_ethereal_preview_url_is_extracted_from_smtp_response():
    from cloud.mapping_and_notification.notifications.email_service import EmailService

    assert EmailService._preview_url_from_response("250 OK [STATUS=success MSGID=abc123]") == "https://ethereal.email/message/abc123"


def test_route_email_contains_instructions_and_inline_floorplan_image(tmp_path, monkeypatch):
    from PIL import Image
    from cloud.mapping_and_notification.notifications import route_email

    image_path = tmp_path / "floorplan.png"
    Image.new("RGB", (160, 100), "white").save(image_path)
    context = {
        "route_summary": {"start_label": "Entrance", "destination_label": "Room 101", "total_distance_m": 18, "estimated_time_seconds": 20},
        "instructions": [{"instruction": "Walk straight to Room 101.", "distance_m": 18}],
        "path": [
            {"node_id": 1, "floorplan_id": 4, "coord_x": 20, "coord_y": 30, "room_label": "Entrance"},
            {"node_id": 2, "floorplan_id": 4, "coord_x": 120, "coord_y": 70, "room_label": "Room 101"},
        ],
        "edges_traversed": [{"from_node_id": 1, "to_node_id": 2, "custom_path": None}],
    }
    monkeypatch.setattr(route_email, "_floorplan_metadata", lambda _db, _ids: {4: {"building_name": "Main", "floor_level": 1, "image_path": image_path}})

    body, attachments = route_email.render_route_email(route_context=context, db=object(), recipient_name="Test User", body="Please follow this route.")

    assert "Walk straight to Room 101." in body
    assert "cid:route-floorplan-4" in body
    assert attachments[0]["cid"] == "route-floorplan-4"
    assert attachments[0]["data"].startswith(b"\x89PNG")
    assert route_email._scale_points([(400, 300)], (160, 100)) == [(80.0, 50.0)]


def test_notification_row_is_committed_before_publish(monkeypatch):
    from cloud.mapping_and_notification.notifications.service import NotificationService

    class FakeQuery:
        def __init__(self, db):
            self.db = db

        def filter(self, *_args):
            return self

        def first(self):
            return self.db.row

    class FakeDb:
        def __init__(self):
            self.row = None
            self.commit_count = 0

        def add(self, row):
            row.notification_id = 1
            self.row = row

        def commit(self):
            self.commit_count += 1

        def query(self, _model):
            return FakeQuery(self)

    class FastWorkerBroker:
        def __init__(self, db):
            self.db = db

        def publish(self, _payload):
            assert self.db.commit_count == 1
            self.db.row.status = "SENT"
            return True

    db = FakeDb()
    service = NotificationService(db, broker=FastWorkerBroker(db))
    payload = build_notification(recipient_user_id=7, title="Route", body="Walk to room")

    row = service.create_and_publish(payload)

    assert row.status == "SENT"
    assert db.commit_count == 2


def test_broker_treats_confirmed_publish_as_success(monkeypatch):
    class FakeChannel:
        def exchange_declare(self, **kwargs):
            pass

        def queue_declare(self, **kwargs):
            pass

        def queue_bind(self, **kwargs):
            pass

        def confirm_delivery(self):
            pass

        def basic_publish(self, **kwargs):
            return None

    class FakeConnection:
        def channel(self):
            return FakeChannel()

        def close(self):
            pass

    class FakePika:
        URLParameters = staticmethod(lambda url: url)
        BlockingConnection = staticmethod(lambda params: FakeConnection())
        BasicProperties = staticmethod(lambda **kwargs: kwargs)

    monkeypatch.setitem(__import__("sys").modules, "pika", FakePika)

    assert Broker().publish({"message_id": "test-message"}) is True
