import logging
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Response, status
from fastapi.responses import FileResponse
from PIL import Image, ImageOps

from ...appconfig import appconfig
from ...container import container
from ...services.processor.four_photo import FourPhotoJob, FourPhotoSettings
from ...utils.exceptions import ProcessMachineOccupiedError
from ...utils.media_resizer import resize

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/processing", tags=["processing"])


@router.get("/approval/{capture_id}", response_class=Response)
def api_get_preview_image_filtered(capture_id: UUID, background_tasks: BackgroundTasks):
    try:
        capture = container.processing_service.get_capture(capture_id)

        filepath_in = capture.filepath
        filepath_out = Path(NamedTemporaryFile(mode="wb", delete=False, dir="tmp", prefix="approval_img_", suffix=filepath_in.suffix).name)

        if capture.target_height and capture.target_width:
            img = ImageOps.fit(Image.open(filepath_in), (capture.target_width, capture.target_height), method=Image.Resampling.BILINEAR)
            img.save(filepath_out)
        else:
            resize(filepath_in, filepath_out, appconfig.mediaprocessing.preview_still_length)

        background_tasks.add_task(lambda path: path.unlink(), filepath_out)

        return FileResponse(filepath_out)

    except FileNotFoundError as exc:
        # either db_get_image_by_id or open both raise FileNotFoundErrors if file/db entry not found
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{capture_id=} cannot be found. {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error preview: {exc}") from exc


@router.get("/next")
@router.get("/confirm")
def api_cmd_confirm_get():
    try:
        container.processing_service.continue_process()
        return "OK"
    except Exception as exc:
        # other errors
        logger.critical(exc)
        raise HTTPException(status_code=500, detail=f"something went wrong, Exception: {exc}") from exc


@router.get("/reject")
def api_cmd_reject_get():
    try:
        container.processing_service.reject_capture()
        return "OK"
    except Exception as exc:
        # other errors
        logger.critical(exc)
        raise HTTPException(status_code=500, detail=f"something went wrong, Exception: {exc}") from exc


@router.get("/abort")
def api_cmd_abort_get():
    try:
        container.processing_service.abort_process()
        return "OK"
    except Exception as exc:
        # other errors
        logger.critical(exc)
        raise HTTPException(status_code=500, detail=f"something went wrong, Exception: {exc}") from exc


@router.post("/four-photo/start")
def api_start_four_photo(settings: FourPhotoSettings):
    try:
        container.processing_service.trigger_four_photo(settings)
    except ProcessMachineOccupiedError as exc:
        raise HTTPException(status_code=409, detail="Another session is already running") from exc
    return "OK"


def _four_photo_job() -> FourPhotoJob:
    job = container.processing_service._workflow_jobmodel
    if not isinstance(job, FourPhotoJob):
        raise HTTPException(status_code=409, detail="No four-photo session is running")
    return job


@router.post("/four-photo/displayed/{capture_id}")
def api_four_photo_displayed(capture_id: UUID):
    if not _four_photo_job().control.displayed(capture_id):
        raise HTTPException(status_code=409, detail="Capture is no longer awaiting display")
    return "OK"


@router.post("/four-photo/decision/{capture_id}/{decision}")
def api_four_photo_decision(capture_id: UUID, decision: Literal["next", "reject"]):
    if not _four_photo_job().control.decide(capture_id, decision):
        raise HTTPException(status_code=409, detail="Capture is no longer awaiting a decision")
    return "OK"


@router.post("/four-photo/{command}")
def api_four_photo_control(command: Literal["pause", "resume", "stop"]):
    job = _four_photo_job()
    getattr(job.control, command)()
    return "OK"


@router.get("/four-photo/draft/{session_id}")
def api_four_photo_draft(session_id: UUID):
    try:
        return FileResponse(container.processing_service.get_four_photo_draft(session_id), media_type="image/jpeg")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Draft not found") from exc
