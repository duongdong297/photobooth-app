from unittest.mock import Mock

from photobooth.container import container
from photobooth.utils.exceptions import ProcessMachineOccupiedError


def test_four_photo_start_validates_and_snapshots_timers(client, monkeypatch):
    trigger = Mock()
    monkeypatch.setattr(container.processing_service, "trigger_four_photo", trigger)
    response = client.post("/processing/four-photo/start", json={"countdown": 2, "review": 5})
    assert response.status_code == 200
    settings = trigger.call_args.args[0]
    assert settings.countdown == 2 and settings.review == 5
    for payload in ({"countdown": 0, "review": 5}, {"countdown": 2, "review": 0}, {"countdown": 2.05, "review": 5}):
        assert client.post("/processing/four-photo/start", json=payload).status_code == 422
    assert trigger.call_count == 1


def test_four_photo_start_rejects_occupied_session(client, monkeypatch):
    monkeypatch.setattr(container.processing_service, "trigger_four_photo", Mock(side_effect=ProcessMachineOccupiedError("occupied")))
    assert client.post("/processing/four-photo/start", json={"countdown": 2, "review": 5}).status_code == 409
