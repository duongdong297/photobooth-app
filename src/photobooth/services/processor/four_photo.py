from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Condition
from time import monotonic

from pydantic import BaseModel, Field

from ...database.models import Mediaitem
from ...utils.media_encode import encode
from ..config.groups.actions import CollageConfigurationSet, CollageProcessing, MultiImageJobControl, SingleImageProcessing
from ..config.models.models import CollageMergeDefinition
from ..config.models.trigger import Trigger
from ..mediaprocessing.processes import process_and_generate_collage, process_image_inner
from .collage import JobModelCollage


class FourPhotoSettings(BaseModel):
    countdown: float = Field(ge=0.1, le=20, multiple_of=0.1)
    review: float = Field(ge=0.1, le=120)


def make_four_photo_configuration(settings: FourPhotoSettings) -> CollageConfigurationSet:
    return CollageConfigurationSet(
        jobcontrol=MultiImageJobControl(
            countdown_capture=settings.countdown,
            countdown_capture_second_following=settings.countdown,
            ask_approval_each_capture=True,
            approve_autoconfirm_timeout=settings.review,
            show_individual_captures_in_gallery=True,
        ),
        processing=CollageProcessing(
            canvas_width=1600,
            canvas_height=1200,
            canvas_fill_background_enable=True,
            canvas_fill_background_color="#ffffff",
            merge_definition=[
                CollageMergeDefinition(description=f"Photo {i + 1}", pos_x=40 + (i % 2) * 780, pos_y=40 + (i // 2) * 580, width=740, height=540)
                for i in range(4)
            ],
        ),
        trigger=Trigger(),
    )


class ReviewControl:
    def __init__(self):
        self._condition = Condition()
        self._current = None
        self._ready = False
        self._decision = None
        self._paused = False
        self._pause_generation = 0
        self._stopped = False

    def open(self, capture_id):
        with self._condition:
            self._current = capture_id
            self._ready = False
            self._decision = None

    def displayed(self, capture_id):
        with self._condition:
            if self._current != capture_id:
                return False
            self._ready = True
            self._condition.notify_all()
            return True

    def decide(self, capture_id, decision):
        with self._condition:
            if self._current != capture_id or not self._ready or self._paused or self._decision is not None:
                return False
            self._decision = decision
            self._current = None
            self._condition.notify_all()
            return True

    def pause(self):
        with self._condition:
            self._paused = True
            self._pause_generation += 1
            self._condition.notify_all()

    def resume(self):
        with self._condition:
            self._paused = False
            self._condition.notify_all()

    def stop(self):
        with self._condition:
            self._stopped = True
            self._current = None
            self._decision = "abort"
            self._condition.notify_all()

    def wait(self, timeout):
        with self._condition:
            remaining = timeout
            while self._decision is None:
                if not self._ready or self._paused:
                    self._condition.wait()
                else:
                    started = monotonic()
                    self._condition.wait(timeout=remaining)
                    remaining -= monotonic() - started
                    if remaining <= 0 and self._decision is None and not self._paused:
                        self._decision = "next"
                        self._current = None
            return self._decision

    def wait_unpaused(self):
        with self._condition:
            self._condition.wait_for(lambda: not self._paused or self._stopped)
            return not self._stopped

    def countdown(self, duration):
        with self._condition:
            remaining = duration
            generation = self._pause_generation
            while not self._stopped:
                if self._paused:
                    self._condition.wait_for(lambda: not self._paused or self._stopped)
                    remaining = duration
                else:
                    if generation != self._pause_generation:
                        generation = self._pause_generation
                        remaining = duration
                    started = monotonic()
                    self._condition.wait(timeout=remaining)
                    remaining -= monotonic() - started
                    if remaining <= 0 and not self._paused and not self._stopped and generation == self._pause_generation:
                        return True
            return False


class FourPhotoStopped(Exception):
    pass


class FourPhotoJob(JobModelCollage):
    def __init__(self, configuration_set, acquisition_service):
        super().__init__(configuration_set, acquisition_service)
        self.control = ReviewControl()
        self._session_dir = Path("data") / "four-photo-sessions" / str(self._job_identifier)
        self._draft_path = self._session_dir / "draft.jpg"

    def export(self):
        result = super().export()
        result.typ = "four_photo"
        if self._approval_id:
            result.duration = self._configuration_set.jobcontrol.approve_autoconfirm_timeout
        else:
            result.duration = self._countdown_timer._duration
        return result

    def on_enter_counting(self):
        self._acquisition_service.thrill_still()
        self._countdown_timer._duration = self._configuration_set.jobcontrol.countdown_capture

    def on_exit_counting(self):
        if not self.control.countdown(self._configuration_set.jobcontrol.countdown_capture):
            raise FourPhotoStopped

    def on_enter_capture(self):
        super().on_enter_capture()
        capture = self._capture_sets[-1].captures[0]
        source = capture.filepath.resolve()
        if not source.is_relative_to(Path("tmp").resolve()) or not source.is_file():
            raise ValueError("Capture is outside the temporary directory")
        self._session_dir.mkdir(parents=True, exist_ok=True)
        destination = self._session_dir / source.name
        if destination.exists():
            raise FileExistsError("Session capture already exists")
        capture.filepath = source.rename(destination)

    def on_enter_approval(self):
        super().on_enter_approval()
        self.control.open(self._approval_id)

    def on_exit_approval(self, event):
        if event == self._status_sm.reject:
            captureset = self._capture_sets[-1]
            for capture in captureset.captures:
                path = capture.filepath.resolve()
                if not path.is_relative_to(self._session_dir.resolve()):
                    raise ValueError("Rejected capture is outside the session directory")
                path.unlink()
            self._capture_sets.pop()
        self._approval_id = None

    def on_enter_completed(self):
        with TemporaryDirectory(prefix="four-photo-processing-", dir="tmp") as temporary:
            processed = []
            for index, captureset in enumerate(self._capture_sets):
                image = process_image_inner(captureset.captures[0].filepath, SingleImageProcessing(), preview=False)
                path = Path(temporary) / f"{index}.jpg"
                encode([image], path)
                processed.append(path)
            draft = Mediaitem(
                id=self._job_identifier,
                job_identifier=self._job_identifier,
                media_type="collage",
                processed=self._draft_path,
                pipeline_config=self._configuration_set.processing.model_dump(mode="json"),
            )
            process_and_generate_collage(processed, draft)
        self._present_mediaitem_id = self._job_identifier
