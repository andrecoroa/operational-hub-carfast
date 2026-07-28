from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as app_main
import app.web.router as web_router
from app.main import app
from app.models import Base
from app.models.documents import DiagnosticDocument, Document
from app.models.vehicles import Vehicle
from app.models.workshop import WorkshopProcess
from app.services.bootstrap import seed_initial_data
from app.services.diagnostic_documents import backfill_legacy_diagnostics
from app.services.users import create_user


@contextmanager
def diagnostic_test_context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    previous_main_session = app_main.SessionLocal
    previous_web_session = web_router.SessionLocal
    app_main.SessionLocal = testing_session
    web_router.SessionLocal = testing_session
    with testing_session() as db:
        seed_initial_data(db)
        create_user(
            db,
            name="Diagnósticos",
            email="diagnosticos@example.com",
            password="Secret123!",
            role_codes=["admin"],
            organizational_unit_codes=["carfast", "workshop"],
        )
        db.commit()
    client = TestClient(app)
    login = client.post(
        "/login",
        data={"email": "diagnosticos@example.com", "password": "Secret123!"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    notice = client.post(
        "/change-notice",
        data={"next_url": "/"},
        follow_redirects=False,
    )
    assert notice.status_code == 303
    try:
        yield testing_session, client
    finally:
        client.close()
        app_main.SessionLocal = previous_main_session
        web_router.SessionLocal = previous_web_session


def make_document(**overrides):
    values = {
        "title": "Documento",
        "document_type": "workshop_other",
        "classification": "workshop",
        "original_name": "documento.pdf",
        "file_name": "documento.pdf",
        "storage_provider": "sharepoint",
        "storage_path": "https://example.com/documento.pdf",
        "status": "received",
    }
    values.update(overrides)
    return Document(**values)


def test_backfill_reproduces_and_repairs_unit_485_document_1522():
    with diagnostic_test_context() as (testing_session, _):
        with testing_session() as db:
            vehicle = Vehicle(
                id=485,
                plate="AA-48-BB",
                vin="VF7TESTUNIT485000",
                rentway_unit_nr="485",
                brand="Citroën",
                model="Jumper",
                lifecycle_status="active",
                operational_status="free",
            )
            document = make_document(
                id=1522,
                title="Relatório de diagnóstico Unit 485",
                original_name="Unit_485_relatorio-de-diagnostico-do-veiculo.pdf",
                file_name="Unit_485_relatorio-de-diagnostico-do-veiculo.pdf",
                folder_path="Oficina/Sem matrícula/Diagnósticos",
            )
            invoice = make_document(
                id=1523,
                title="Fatura de intervenção com diagnóstico",
                document_type="workshop_supplier_invoice",
                original_name="fatura-diagnostico.pdf",
                file_name="fatura-diagnostico.pdf",
            )
            db.add_all([vehicle, document, invoice])
            db.flush()

            assert document.vehicle_id is None
            assert document.document_type == "workshop_other"

            stats = backfill_legacy_diagnostics(db)
            db.flush()
            profile = db.scalar(
                select(DiagnosticDocument).where(DiagnosticDocument.document_id == 1522)
            )

            assert stats == {
                "scanned": 2,
                "diagnostics": 1,
                "profiles_created": 1,
                "associated": 1,
            }
            assert profile is not None
            assert profile.diagnostic_type == "vehicle_diagnostic_report"
            assert profile.association_status == "automatic"
            assert document.vehicle_id == 485
            assert document.plate == "AA-48-BB"
            assert document.document_type == "workshop_diagnostic"
            assert db.scalar(
                select(DiagnosticDocument).where(DiagnosticDocument.document_id == 1523)
            ) is None


def test_vehicle_page_has_separate_diagnostic_table_and_real_counts():
    with diagnostic_test_context() as (testing_session, client):
        with testing_session() as db:
            vehicle = Vehicle(
                plate="AB-12-CD",
                vin="VF7DIAGNOSTIC001",
                rentway_unit_nr="120",
                brand="Peugeot",
                model="208",
                lifecycle_status="active",
                operational_status="free",
            )
            db.add(vehicle)
            db.flush()
            vehicle_id = vehicle.id
            for index in range(25):
                db.add(
                    make_document(
                        title=f"Documento genérico {index}",
                        original_name=f"generico-{index}.pdf",
                        file_name=f"generico-{index}.pdf",
                        storage_path=f"https://example.com/generico-{index}.pdf",
                        vehicle_id=vehicle.id,
                        plate=vehicle.plate,
                    )
                )
            db.commit()

        response = client.post(
            f"/fleet/{vehicle_id}/diagnostics",
            data={
                "title": "Leitura de defeitos inicial",
                "diagnostic_type": "fault_codes_global_test",
                "document_date": "2026-07-28",
                "odometer_km": "85420",
                "report_number": "MAXIA202607281200",
                "diagnostic_tool": "Autel MaxiSys",
                "ocr_status": "extracted",
                "validation_status": "needs_review",
                "url_original": "https://example.com/diagnostico.pdf",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        page = client.get(f"/fleet/{vehicle_id}")
        assert page.status_code == 200
        assert "Diagnósticos <span>1</span>" in page.text
        assert "Outros documentos <span>25</span>" in page.text
        assert "Códigos de avaria / teste global" in page.text
        assert "OCR Extraído" in page.text
        assert "KM 85420" in page.text

        with testing_session() as db:
            diagnostic = db.scalar(select(DiagnosticDocument))
            document = db.get(Document, diagnostic.document_id)
            assert document.vehicle_id == vehicle_id
            assert document.document_type == "workshop_diagnostic"
            assert diagnostic.odometer_km == 85420
            assert diagnostic.ocr_status == "extracted"
            assert diagnostic.validation_status == "needs_review"


def test_document_intake_normalizes_plate_and_creates_diagnostic_profile():
    with diagnostic_test_context() as (testing_session, client):
        with testing_session() as db:
            vehicle = Vehicle(
                plate="AZ-90-XT",
                vin="VF7NORMALIZEDPLATE",
                rentway_unit_nr="900",
                lifecycle_status="active",
                operational_status="free",
            )
            db.add(vehicle)
            db.commit()
            vehicle_id = vehicle.id

        response = client.post(
            "/documents/new",
            data={
                "title": "Informações lubrificação motor",
                "classification": "workshop",
                "document_type": "workshop_diagnostic",
                "status": "received",
                "plate": "az 90 xt",
                "url_original": "https://example.com/lubrificacao.pdf",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        with testing_session() as db:
            document = db.scalar(select(Document))
            profile = db.scalar(select(DiagnosticDocument))
            assert document.vehicle_id == vehicle_id
            assert profile.document_id == document.id
            assert profile.diagnostic_type == "engine_lubrication_information"
            assert profile.association_status == "confirmed"


def test_manual_link_and_diagnostic_validation_are_independent_from_invoice_fields():
    with diagnostic_test_context() as (testing_session, client):
        with testing_session() as db:
            vehicle = Vehicle(
                plate="BB-48-CC",
                vin="VF7MANUALLINK485",
                rentway_unit_nr="485",
                lifecycle_status="active",
                operational_status="free",
            )
            document = make_document(
                id=1522,
                title="Relatório recebido sem associação",
                document_type="workshop_other",
            )
            db.add_all([vehicle, document])
            db.commit()
            vehicle_id = vehicle.id

        linked = client.post(
            f"/fleet/{vehicle_id}/diagnostics/link",
            data={
                "document_id": "1522",
                "diagnostic_type": "fault_codes_global_test",
            },
            follow_redirects=False,
        )
        assert linked.status_code == 303

        validated = client.post(
            "/documents/1522/diagnostic",
            data={
                "diagnostic_type": "engine_lubrication_information",
                "diagnostic_status": "completed",
                "odometer_km": "90210",
                "ocr_status": "extracted",
                "ocr_confidence": "0,87",
                "validation_status": "validated",
                "validation_notes": "Valores confirmados no relatório original.",
            },
            follow_redirects=False,
        )
        assert validated.status_code == 303

        detail = client.get("/documents/1522")
        assert detail.status_code == 200
        assert "Relatório, OCR e validação" in detail.text
        assert "Valores confirmados no relatório original." in detail.text

        with testing_session() as db:
            document = db.get(Document, 1522)
            profile = db.scalar(
                select(DiagnosticDocument).where(DiagnosticDocument.document_id == 1522)
            )
            assert document.vehicle_id == vehicle_id
            assert document.document_type == "workshop_diagnostic"
            assert document.supplier_name is None
            assert profile.association_status == "manual"
            assert profile.diagnostic_type == "engine_lubrication_information"
            assert profile.diagnostic_status == "completed"
            assert profile.ocr_confidence == 0.87
            assert profile.validation_status == "validated"
            assert profile.validated_at is not None


def test_workshop_document_flow_only_adds_diagnostic_profile_for_diagnostics():
    with diagnostic_test_context() as (testing_session, client):
        with testing_session() as db:
            vehicle = Vehicle(
                plate="CC-10-DD",
                vin="VF7WORKSHOPDIAG",
                rentway_unit_nr="510",
                lifecycle_status="active",
                operational_status="free",
            )
            db.add(vehicle)
            db.flush()
            process = WorkshopProcess(
                vehicle_id=vehicle.id,
                title="Diagnóstico documental",
                status="diagnosis",
            )
            db.add(process)
            db.commit()
            process_id = process.id

        response = client.post(
            f"/workshop/{process_id}/documents",
            data={
                "title": "Teste global",
                "document_type": "workshop_diagnostic",
                "url_original": "https://example.com/teste-global.pdf",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        with testing_session() as db:
            document = db.scalar(select(Document))
            profile = db.scalar(select(DiagnosticDocument))
            assert document.workshop_process_id == process_id
            assert document.document_type == "workshop_diagnostic"
            assert profile.document_id == document.id
