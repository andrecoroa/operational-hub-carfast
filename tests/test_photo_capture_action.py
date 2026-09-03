import io
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select

from app.core.config import settings
from app.main import app
from app.models.admin import User
from app.models.audit import AuditLog
from app.models.documents import Document, DocumentLink
from app.models.photo_capture import PhotoCaptureItem, PhotoCaptureSession, PhotoMedia
from app.models.tasks import Task
from app.models.vehicles import Vehicle
from app.models.workshop_phased import WorkshopPhasedProcess, WorkshopPhasedProcessPhase
from app.services.photo_capture import required_photo_blockers
from app.services.users import create_user
from tests.conftest import TEST_ADMIN_EMAIL


def jpeg_bytes(color: tuple[int, int, int] = (190, 60, 45)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (1200, 800), color).save(output, format="JPEG", quality=95)
    return output.getvalue()


def create_context(db_session):
    admin = db_session.scalar(select(User).where(User.email == TEST_ADMIN_EMAIL))
    vehicle = Vehicle(plate="PH-01-TO", brand="Peugeot", model="308")
    db_session.add(vehicle)
    db_session.flush()
    task = Task(
        title="Registar estado da viatura",
        task_type="workshop_task",
        status="new",
        priority="normal",
        plate=vehicle.plate,
        created_by_id=admin.id,
    )
    db_session.add(task)
    process = WorkshopPhasedProcess(
        process_type="maintenance",
        title="Processo fotográfico",
        creation_mode="operational",
        status="in_progress",
        vehicle_id=vehicle.id,
        plate_snapshot=vehicle.plate,
        current_phase_code="entrada",
        created_by_id=admin.id,
    )
    db_session.add(process)
    db_session.flush()
    phase = WorkshopPhasedProcessPhase(
        process_id=process.id,
        phase_code="entrada",
        name="Entrada",
        status="in_progress",
        sort_order=1,
    )
    db_session.add(phase)
    db_session.commit()
    return admin, vehicle, task, process, phase


def photo_config(**overrides):
    config = {
        "title": "Fotografias de entrada",
        "instructions": "Fotografar a frente e qualquer dano visível.",
        "min_photos": 1,
        "max_photos": 2,
        "required": True,
        "allow_camera": True,
        "allow_gallery": True,
        "categories": ["front", "damage"],
        "observation": "optional",
        "location_enabled": False,
        "require_new_capture": False,
        "review_required": True,
        "max_file_bytes": 2_000_000,
    }
    config.update(overrides)
    return config


def create_session(authenticated_client, task, vehicle, process, phase, **config_overrides):
    response = authenticated_client.post(
        "/api/photo-actions/sessions",
        json={
            "config": photo_config(**config_overrides),
            "task_id": task.id,
            "phased_process_id": process.id,
            "phase_id": phase.id,
            "vehicle_id": vehicle.id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_authorized_capture_deduplicates_and_links_every_context(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "document_archive_root", str(tmp_path))
    _admin, vehicle, task, process, phase = create_context(db_session)
    first = create_session(authenticated_client, task, vehicle, process, phase)
    content = jpeg_bytes()
    upload = authenticated_client.post(
        f"/api/photo-actions/sessions/{first['id']}/photos",
        files={"photo": ("frente.jpg", content, "text/plain")},
        data={"category": "front", "capture_source": "camera", "is_new_capture": "true"},
    )
    assert upload.status_code == 201, upload.text
    assert upload.json()["session"]["progress"]["label"] == "1 de 2 fotografias"

    second = create_session(authenticated_client, task, vehicle, process, phase)
    duplicate = authenticated_client.post(
        f"/api/photo-actions/sessions/{second['id']}/photos",
        files={"photo": ("outra-frente.jpeg", content, "image/jpeg")},
        data={"category": "front", "capture_source": "camera", "is_new_capture": "true"},
    )
    assert duplicate.status_code == 201, duplicate.text

    assert db_session.scalar(select(func.count()).select_from(PhotoMedia)) == 1
    assert db_session.scalar(select(func.count()).select_from(Document)) == 1
    assert db_session.scalar(select(func.count()).select_from(PhotoCaptureItem)) == 2
    document = db_session.scalar(select(Document))
    assert document.file_hash and len(document.file_hash) == 64
    assert document.file_type == "image/jpeg"
    assert document.storage_key.startswith("photos/sha256/")
    assert Path(document.storage_path).is_file()
    linked_types = set(
        db_session.scalars(
            select(DocumentLink.entity_type).where(DocumentLink.document_id == document.id)
        ).all()
    )
    assert {"task", "workshop_phased_process", "workshop_phase", "vehicle"} <= linked_types

    content_response = authenticated_client.get(
        duplicate.json()["session"]["items"][0]["content_url"]
    )
    assert content_response.status_code == 200
    assert content_response.headers["x-content-type-options"] == "nosniff"
    assert content_response.headers["cache-control"].startswith("private")


def test_minimum_maximum_mime_extension_and_observation_are_enforced(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "document_archive_root", str(tmp_path))
    _admin, vehicle, task, process, phase = create_context(db_session)
    session = create_session(
        authenticated_client,
        task,
        vehicle,
        process,
        phase,
        min_photos=2,
        max_photos=2,
        observation="required",
    )
    early = authenticated_client.post(f"/api/photo-actions/sessions/{session['id']}/submit")
    assert early.status_code == 400

    invalid = authenticated_client.post(
        f"/api/photo-actions/sessions/{session['id']}/photos",
        files={"photo": ("ataque.svg", b"<svg><script>alert(1)</script></svg>", "image/svg+xml")},
        data={"category": "front", "observation": "x", "capture_source": "camera"},
    )
    assert invalid.status_code == 400
    assert "SVG" in invalid.json()["detail"]

    mismatch = authenticated_client.post(
        f"/api/photo-actions/sessions/{session['id']}/photos",
        files={"photo": ("frente.png", jpeg_bytes(), "image/png")},
        data={"category": "front", "observation": "x", "capture_source": "camera"},
    )
    assert mismatch.status_code == 400
    assert "extensão" in mismatch.json()["detail"]

    missing_observation = authenticated_client.post(
        f"/api/photo-actions/sessions/{session['id']}/photos",
        files={"photo": ("frente.jpg", jpeg_bytes(), "image/jpeg")},
        data={"category": "front", "capture_source": "camera"},
    )
    assert missing_observation.status_code == 400
    assert "observação" in missing_observation.json()["detail"].lower()

    for index, category in enumerate(("front", "damage")):
        response = authenticated_client.post(
            f"/api/photo-actions/sessions/{session['id']}/photos",
            files={
                "photo": (
                    f"photo-{index}.jpg",
                    jpeg_bytes((190, 60 + index, 45)),
                    "image/jpeg",
                )
            },
            data={
                "category": category,
                "observation": f"Observação {index}",
                "capture_source": "camera",
            },
        )
        assert response.status_code == 201, response.text
    overflow = authenticated_client.post(
        f"/api/photo-actions/sessions/{session['id']}/photos",
        files={"photo": ("extra.jpg", jpeg_bytes((1, 2, 3)), "image/jpeg")},
        data={"category": "front", "observation": "extra", "capture_source": "camera"},
    )
    assert overflow.status_code == 400
    submitted = authenticated_client.post(f"/api/photo-actions/sessions/{session['id']}/submit")
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "submitted"


def test_new_capture_and_location_require_explicit_allowed_source_and_consent(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "document_archive_root", str(tmp_path))
    _admin, vehicle, task, process, phase = create_context(db_session)
    session = create_session(
        authenticated_client,
        task,
        vehicle,
        process,
        phase,
        allow_gallery=False,
        require_new_capture=True,
        location_enabled=True,
    )
    gallery = authenticated_client.post(
        f"/api/photo-actions/sessions/{session['id']}/photos",
        files={"photo": ("foto.jpg", jpeg_bytes(), "image/jpeg")},
        data={"category": "front", "capture_source": "gallery", "is_new_capture": "false"},
    )
    assert gallery.status_code == 400
    no_consent = authenticated_client.post(
        f"/api/photo-actions/sessions/{session['id']}/photos",
        files={"photo": ("foto.jpg", jpeg_bytes(), "image/jpeg")},
        data={
            "category": "front",
            "capture_source": "camera",
            "is_new_capture": "true",
            "location_latitude": "38.72",
            "location_longitude": "-9.13",
        },
    )
    assert no_consent.status_code == 400
    accepted = authenticated_client.post(
        f"/api/photo-actions/sessions/{session['id']}/photos",
        files={"photo": ("foto.jpg", jpeg_bytes(), "image/jpeg")},
        data={
            "category": "front",
            "capture_source": "camera",
            "is_new_capture": "true",
            "location_latitude": "38.72",
            "location_longitude": "-9.13",
            "location_consent": "true",
        },
    )
    assert accepted.status_code == 201, accepted.text
    item = db_session.get(PhotoCaptureItem, accepted.json()["item_id"])
    assert item.location_consented_at is not None
    assert item.location_latitude == 38.72


def test_required_capture_blocks_task_and_phase_until_approved(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "document_archive_root", str(tmp_path))
    _admin, vehicle, task, process, phase = create_context(db_session)
    session = create_session(authenticated_client, task, vehicle, process, phase)
    assert required_photo_blockers(db_session, task_id=task.id)
    assert required_photo_blockers(db_session, phased_process_id=process.id, phase_id=phase.id)
    blocked_close = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/close",
        data={"return_url": f"/task-board/{task.id}"},
        follow_redirects=False,
    )
    assert blocked_close.status_code == 303
    assert "Fotografias+obrigat" in blocked_close.headers["location"]

    upload = authenticated_client.post(
        f"/api/photo-actions/sessions/{session['id']}/photos",
        files={"photo": ("frente.jpg", jpeg_bytes(), "image/jpeg")},
        data={"category": "front", "capture_source": "camera"},
    )
    assert upload.status_code == 201
    assert (
        authenticated_client.post(f"/api/photo-actions/sessions/{session['id']}/submit").status_code
        == 200
    )
    assert required_photo_blockers(db_session, task_id=task.id)
    approved = authenticated_client.post(
        f"/api/photo-actions/sessions/{session['id']}/review",
        json={"decision": "approved"},
    )
    assert approved.status_code == 200
    assert required_photo_blockers(db_session, task_id=task.id) == []


def test_rejection_requires_reason_and_repeat_preserves_audit(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "document_archive_root", str(tmp_path))
    _admin, vehicle, task, process, phase = create_context(db_session)
    session = create_session(authenticated_client, task, vehicle, process, phase)
    authenticated_client.post(
        f"/api/photo-actions/sessions/{session['id']}/photos",
        files={"photo": ("dano.jpg", jpeg_bytes(), "image/jpeg")},
        data={"category": "damage", "capture_source": "camera"},
    )
    authenticated_client.post(f"/api/photo-actions/sessions/{session['id']}/submit")
    invalid = authenticated_client.post(
        f"/api/photo-actions/sessions/{session['id']}/review",
        json={"decision": "rejected"},
    )
    assert invalid.status_code == 400
    rejected = authenticated_client.post(
        f"/api/photo-actions/sessions/{session['id']}/review",
        json={"decision": "rejected", "reason": "Imagem desfocada"},
    )
    assert rejected.status_code == 200
    repeated = authenticated_client.post(f"/api/photo-actions/sessions/{session['id']}/repeat")
    assert repeated.status_code == 201
    assert repeated.json()["attempt_number"] == 2
    new_session = db_session.get(PhotoCaptureSession, repeated.json()["id"])
    assert new_session.repeats_session_id == session["id"]
    audit_actions = set(
        db_session.scalars(select(AuditLog.action).where(AuditLog.action.like("photo.%"))).all()
    )
    assert {
        "photo.session.created",
        "photo.captured",
        "photo.session.submitted",
        "photo.session.rejected",
        "photo.session.repeated",
    } <= audit_actions


def test_capture_is_denied_without_photo_permission(client, db_session):
    create_user(
        db_session,
        name="Consulta",
        email="viewer.photo@carfast.local",
        password="Secret123!",
        role_codes=["viewer"],
        organizational_unit_codes=["carfast"],
    )
    vehicle = Vehicle(plate="NO-01-PH")
    db_session.add(vehicle)
    db_session.commit()
    viewer = TestClient(app)
    login = viewer.post(
        "/login",
        data={"email": "viewer.photo@carfast.local", "password": "Secret123!"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    denied = viewer.post(
        "/api/photo-actions/sessions",
        json={"definition_code": "take_photo.default", "vehicle_id": vehicle.id},
    )
    assert denied.status_code == 403


def test_mobile_camera_markup_and_all_operational_surfaces_are_wired():
    root = Path(__file__).resolve().parents[1]
    partial = (root / "app/templates/_photo_capture.html").read_text(encoding="utf-8")
    script = (root / "app/static/js/photo_capture.js").read_text(encoding="utf-8")
    assert "data-photo-capture" in partial
    assert 'capture="environment"' in script
    assert "data-photo-preview" in script
    assert "Remover / substituir" in script
    assert "navigator.geolocation" in script
    for template in (
        "task_detail.html",
        "clean_fleet_detail.html",
        "clean_workshop_entry.html",
        "clean_workshop_phase.html",
    ):
        assert "_photo_capture.html" in (root / "app/templates" / template).read_text(
            encoding="utf-8"
        )


def test_photo_migration_is_the_single_alembic_head():
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["fff8cd3e4f5a"]
    assert scripts.get_revision("fff26e7f8a9c").down_revision == "fff15d6e7f8b"
    assert scripts.get_revision("fff15d6e7f8b").down_revision == "ffd05e6f7a8b"
