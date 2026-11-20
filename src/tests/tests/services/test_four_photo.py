import pytest
from pydantic import ValidationError

from photobooth.services.processor.four_photo import FourPhotoJob, FourPhotoSettings, make_four_photo_configuration


def test_four_photo_settings_and_preset_are_independent():
    settings = FourPhotoSettings(countdown=2, review=5)
    config = make_four_photo_configuration(settings)
    settings.countdown = 7
    assert config.jobcontrol.countdown_capture == 2
    assert config.jobcontrol.countdown_capture_second_following == 2
    assert config.jobcontrol.approve_autoconfirm_timeout == 5
    assert config.jobcontrol.ask_approval_each_capture
    slots = config.processing.merge_definition
    assert len(slots) == 4 and all(slot.predefined_image is None for slot in slots)
    assert not config.processing.capture_remove_background
    assert not config.processing.capture_fill_background_enable
    assert not config.processing.capture_img_background_enable


@pytest.mark.parametrize("values", [{"countdown": -1, "review": 5}, {"countdown": 2, "review": 0}, {"countdown": 21, "review": 5}])
def test_four_photo_rejects_invalid_timers(values):
    with pytest.raises(ValidationError):
        FourPhotoSettings(**values)


def test_review_waits_for_display_and_rejects_stale_decisions():
    from threading import Thread
    from time import sleep
    from uuid import uuid4

    from photobooth.services.processor.four_photo import ReviewControl

    control = ReviewControl()
    current, stale = uuid4(), uuid4()
    control.open(current)
    result = []
    worker = Thread(target=lambda: result.append(control.wait(0.05)))
    worker.start()
    sleep(0.1)
    assert worker.is_alive()
    assert not control.decide(stale, "reject")
    assert control.displayed(current)
    assert control.decide(current, "reject")
    assert not control.decide(current, "next")
    worker.join(1)
    assert result == ["reject"]


def test_review_auto_confirms_after_display():
    from threading import Thread
    from uuid import uuid4

    from photobooth.services.processor.four_photo import ReviewControl

    control = ReviewControl()
    current = uuid4()
    control.open(current)
    result = []
    worker = Thread(target=lambda: result.append(control.wait(0.05)))
    worker.start()
    assert control.displayed(current)
    worker.join(1)
    assert result == ["next"]
    assert not control.decide(current, "reject")


def test_review_pause_freezes_timeout_and_stop_interrupts():
    from threading import Thread
    from time import sleep
    from uuid import uuid4

    from photobooth.services.processor.four_photo import ReviewControl

    control = ReviewControl()
    capture_id = uuid4()
    control.open(capture_id)
    control.pause()
    assert control.displayed(capture_id)
    result = []
    worker = Thread(target=lambda: result.append(control.wait(0.05)))
    worker.start()
    sleep(0.12)
    assert worker.is_alive()
    control.stop()
    worker.join(1)
    assert result == ["abort"]


def test_countdown_restarts_after_pause_and_stop_interrupts():
    from threading import Thread
    from time import monotonic, sleep

    from photobooth.services.processor.four_photo import ReviewControl

    control = ReviewControl()
    result = []
    start = monotonic()
    worker = Thread(target=lambda: result.append(control.countdown(0.2)))
    worker.start()
    sleep(0.1)
    control.pause()
    sleep(0.12)
    control.resume()
    worker.join(1)
    assert result == [True]
    assert monotonic() - start >= 0.37

    control.pause()
    worker = Thread(target=lambda: result.append(control.countdown(1)))
    worker.start()
    control.stop()
    worker.join(1)
    assert result[-1] is False


def test_reject_removes_only_current_session_capture(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from photobooth.services.processor.four_photo import FourPhotoJob
    from photobooth.services.processor.models import Capture, CaptureSet

    monkeypatch.chdir(tmp_path)
    (tmp_path / "tmp").mkdir()
    job = FourPhotoJob(make_four_photo_configuration(FourPhotoSettings(countdown=2, review=5)), Mock())
    job._session_dir.mkdir(parents=True)
    accepted = job._session_dir / "accepted.jpg"
    rejected = job._session_dir / "rejected.jpg"
    unrelated = tmp_path / "unrelated.jpg"
    for path in (accepted, rejected, unrelated):
        path.write_bytes(b"photo")
    job._capture_sets = [CaptureSet([Capture(accepted)]), CaptureSet([Capture(rejected)])]
    job.on_exit_approval(job._status_sm.reject)
    assert accepted.exists() and unrelated.exists() and not rejected.exists()
    assert len(job._capture_sets) == 1

    job._capture_sets.append(CaptureSet([Capture(unrelated)]))
    with pytest.raises(ValueError):
        job.on_exit_approval(job._status_sm.reject)
    assert unrelated.exists()


def test_four_photo_service_retake_and_exactly_four_results(tmp_path, monkeypatch):
    from time import monotonic, sleep
    from unittest.mock import Mock

    from PIL import Image

    from photobooth.services.processing import ProcessingService

    monkeypatch.chdir(tmp_path)
    for folder in ("tmp", "media/camera_original", "media/processed_full", "cache"):
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
    unrelated = tmp_path / "unrelated.jpg"
    unrelated.write_bytes(b"keep")
    captures = []
    acquisition = Mock()

    def capture():
        path = tmp_path / "tmp" / f"capture-{len(captures)}.jpg"
        Image.new("RGB", (800, 600), (20 + len(captures) * 30, 30, 40)).save(path)
        captures.append(path)
        return path

    acquisition.wait_for_still_file.side_effect = capture
    collection = Mock()
    service = ProcessingService(acquisition, collection, Mock())
    service.start()
    service.trigger_four_photo(FourPhotoSettings(countdown=0.1, review=0.3))
    job = service._workflow_jobmodel
    assert isinstance(job, FourPhotoJob)
    assert job is not None
    seen = set()
    for decision in ("reject", "next", "auto", "next", "next"):
        deadline = monotonic() + 8
        while monotonic() < deadline:
            capture_id = job._approval_id
            if capture_id and capture_id not in seen:
                break
            sleep(0.01)
        else:
            pytest.fail("approval did not arrive")
        seen.add(capture_id)
        assert job.control.displayed(capture_id)
        if decision != "auto":
            assert job.control.decide(capture_id, decision)
    service.wait_until_job_finished()
    assert len(captures) == 5 and not captures[0].exists() and unrelated.read_bytes() == b"keep"
    assert not list(job._session_dir.glob("capture-0.jpg"))
    collection.add_item.assert_not_called()
    assert len(list(job._session_dir.glob("capture-*.jpg"))) == 4
    draft = service.get_four_photo_draft(job._job_identifier)
    with Image.open(draft) as collage:
        centers = [(410, 310), (1190, 310), (410, 890), (1190, 890)]
        assert all(abs(collage.getpixel(point)[0] - expected) < 12 for point, expected in zip(centers, (50, 80, 110, 140), strict=True))


def test_camera_failure_keeps_accepted_capture_without_export(tmp_path, monkeypatch):
    from time import monotonic, sleep
    from unittest.mock import Mock

    from PIL import Image

    from photobooth.services.processing import ProcessingService

    monkeypatch.chdir(tmp_path)
    (tmp_path / "tmp").mkdir()
    first = tmp_path / "tmp" / "accepted.jpg"
    Image.new("RGB", (20, 20), "red").save(first)
    acquisition = Mock()
    acquisition.wait_for_still_file.side_effect = [first, RuntimeError("camera disconnected")]
    collection = Mock()
    service = ProcessingService(acquisition, collection, Mock())
    service.start()
    service.trigger_four_photo(FourPhotoSettings(countdown=0.1, review=5))
    job = service._workflow_jobmodel
    assert isinstance(job, FourPhotoJob)
    deadline = monotonic() + 5
    while not job._approval_id and monotonic() < deadline:
        sleep(0.01)
    assert job._approval_id
    assert job.control.displayed(job._approval_id)
    assert job.control.decide(job._approval_id, "next")
    service.wait_until_job_finished()
    assert len(job._capture_sets) == 1 and job._capture_sets[0].captures[0].filepath.is_file()
    collection.add_item.assert_not_called()


def test_stop_during_review_preserves_captures_without_export(tmp_path, monkeypatch):
    from time import monotonic, sleep
    from unittest.mock import Mock

    from PIL import Image

    from photobooth.services.processing import ProcessingService

    monkeypatch.chdir(tmp_path)
    (tmp_path / "tmp").mkdir()
    path = tmp_path / "tmp" / "capture.jpg"
    Image.new("RGB", (20, 20), "red").save(path)
    acquisition = Mock()
    acquisition.wait_for_still_file.return_value = path
    collection = Mock()
    service = ProcessingService(acquisition, collection, Mock())
    service.start()
    service.trigger_four_photo(FourPhotoSettings(countdown=0.1, review=5))
    job = service._workflow_jobmodel
    assert isinstance(job, FourPhotoJob)
    deadline = monotonic() + 5
    while not job._approval_id and monotonic() < deadline:
        sleep(0.01)
    assert job._approval_id
    job.control.stop()
    service.wait_until_job_finished()
    assert job._capture_sets[0].captures[0].filepath.is_file()
    collection.add_item.assert_not_called()


def test_pause_while_capturing_waits_until_received_then_resumes(tmp_path, monkeypatch):
    from threading import Event
    from time import monotonic, sleep
    from unittest.mock import Mock

    from PIL import Image

    from photobooth.services.processing import ProcessingService

    monkeypatch.chdir(tmp_path)
    (tmp_path / "tmp").mkdir()
    path = tmp_path / "tmp" / "capture.jpg"
    Image.new("RGB", (20, 20), "red").save(path)
    entered, release = Event(), Event()
    acquisition = Mock()

    def capture():
        entered.set()
        assert release.wait(3)
        return path

    acquisition.wait_for_still_file.side_effect = capture
    service = ProcessingService(acquisition, Mock(), Mock())
    service.start()
    service.trigger_four_photo(FourPhotoSettings(countdown=0.1, review=5))
    job = service._workflow_jobmodel
    assert isinstance(job, FourPhotoJob)
    assert entered.wait(3)
    job.control.pause()
    release.set()
    sleep(0.15)
    assert len(job._capture_sets) == 1 and job._approval_id is None
    job.control.resume()
    deadline = monotonic() + 3
    while not job._approval_id and monotonic() < deadline:
        sleep(0.01)
    assert job._approval_id
    job.control.stop()
    service.wait_until_job_finished()
    assert job._capture_sets[0].captures[0].filepath.is_file()


def test_reject_does_not_delete_another_sessions_temporary_file(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from photobooth.services.processor.four_photo import FourPhotoJob
    from photobooth.services.processor.models import Capture, CaptureSet

    monkeypatch.chdir(tmp_path)
    (tmp_path / "tmp").mkdir()
    unrelated = tmp_path / "tmp" / "other-session.jpg"
    unrelated.write_bytes(b"keep")
    job = FourPhotoJob(make_four_photo_configuration(FourPhotoSettings(countdown=2, review=5)), Mock())
    job._capture_sets = [CaptureSet([Capture(unrelated)])]
    with pytest.raises(ValueError):
        job.on_exit_approval(job._status_sm.reject)
    assert unrelated.read_bytes() == b"keep"


def test_stop_during_countdown_does_not_capture(tmp_path, monkeypatch):
    from time import monotonic, sleep
    from unittest.mock import Mock

    from photobooth.services.processing import ProcessingService

    monkeypatch.chdir(tmp_path)
    acquisition = Mock()
    collection = Mock()
    service = ProcessingService(acquisition, collection, Mock())
    service.start()
    service.trigger_four_photo(FourPhotoSettings(countdown=1, review=5))
    job = service._workflow_jobmodel
    assert isinstance(job, FourPhotoJob)
    deadline = monotonic() + 3
    while next(iter(job._status_sm.configuration)).id != "counting" and monotonic() < deadline:
        sleep(0.01)
    assert next(iter(job._status_sm.configuration)).id == "counting"
    job.control.stop()
    service.wait_until_job_finished()
    acquisition.wait_for_still_file.assert_not_called()
    collection.add_item.assert_not_called()


def test_exported_timers_match_actual_four_photo_settings():
    from unittest.mock import Mock
    from uuid import uuid4

    job = FourPhotoJob(make_four_photo_configuration(FourPhotoSettings(countdown=2, review=5)), Mock())
    job._countdown_timer._duration = 2
    assert job.export().duration == 2
    job._approval_id = uuid4()
    assert job.export().duration == 5


def test_decision_at_timeout_resolves_only_once():
    from threading import Thread
    from time import sleep
    from uuid import uuid4

    from photobooth.services.processor.four_photo import ReviewControl

    control = ReviewControl()
    capture_id = uuid4()
    control.open(capture_id)
    assert control.displayed(capture_id)
    result = []
    worker = Thread(target=lambda: result.append(control.wait(0.05)))
    worker.start()
    sleep(0.049)
    accepted = control.decide(capture_id, "reject")
    worker.join(1)
    assert result == (["reject"] if accepted else ["next"])
    assert not control.decide(capture_id, "next")
