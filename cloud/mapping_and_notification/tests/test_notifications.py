from cloud.mapping_and_notification.notifications.builder import build_notification
from cloud.mapping_and_notification.notifications.templates import visitor_email


def test_notification_builder_has_unique_id_and_safe_template():
    first = build_notification(recipient_user_id=7, title="Route", body="Walk to room")
    second = build_notification(recipient_user_id=7, title="Route", body="Walk to room")
    assert first.message_id != second.message_id
    assert "<script>" not in visitor_email(visitor_name="<script>", destination="Room", instructions=["Walk"])
