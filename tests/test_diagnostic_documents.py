from contextlib import contextmanager
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as app_main
import app.web.router as web_router
from app.main import app
from app.models import Base
from app.models.documents import DiagnosticDocument, DiagnosticExtraction, Document
from app.models.vehicles import Vehicle
from app.models.workshop import WorkshopProcess
from app.services.bootstrap import seed_initial_data
from app.services.diagnostic_documents import (
    backfill_legacy_diagnostics,
    ensure_diagnostic_profile,
)
from app.services.diagnostic_ocr import (
    extract_coordinate_observations,
    parse_diagnostic_filename,
    parse_diagnostic_payload,
    parse_diagnostic_report_datetime,
    persist_diagnostic_extraction,
)
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


def test_clean_vehicle_diagnostics_has_dedicated_operational_page():
    with diagnostic_test_context() as (testing_session, client):
        with testing_session() as db:
            vehicle = Vehicle(
                plate="DI-24-GN",
                vin="VF7DIAGNOSTICPAGE01",
                rentway_unit_nr="485",
                brand="Peugeot",
                model="Partner",
                lifecycle_status="active",
                operational_status="free",
            )
            document = make_document(
                title="Leitura de defeitos",
                original_name="A_LD_VF7DIAGNOSTICPAGE01_260728_1425.pdf",
                file_name="A_LD_VF7DIAGNOSTICPAGE01_260728_1425.pdf",
                storage_path=r"C:\diagnostics\A_LD_example.pdf",
                document_type="workshop_diagnostic",
                vehicle_id=None,
                plate=vehicle.plate,
            )
            db.add_all([vehicle, document])
            db.flush()
            document.vehicle_id = vehicle.id
            profile = DiagnosticDocument(
                document_id=document.id,
                diagnostic_type="fault_codes_global_test",
                diagnostic_status="completed",
                association_status="confirmed",
                diagnostic_tool="Autel",
                report_datetime=datetime(2026, 7, 28, 14, 25),
                odometer_km=64000,
                ocr_status="extracted",
                validation_status="needs_review",
            )
            db.add(profile)
            db.flush()
            profile_id = profile.id
            db.add(
                DiagnosticExtraction(
                    diagnostic_document_id=profile.id,
                    extractor_name="diagnostic_pdf",
                    extractor_version="1",
                    parser_name="autel_diagnostic_parser",
                    parser_version="1",
                    source_machine="autel",
                    source_family="LD",
                    source_filename=document.original_name,
                    source_sha256="d" * 64,
                    source_page_count=2,
                    extraction_method="native_text",
                    extraction_status="extracted",
                    confidence=0.96,
                    normalized_data_json={"vin": vehicle.vin},
                    dynamic_fields_json={
                        "observations": [
                            {
                                "label": "Tensão bateria",
                                "value": "12.4",
                                "unit": "V",
                                "page": 1,
                            }
                        ],
                        "dtcs": [
                            {
                                "code": "P0420",
                                "raw_context": "Eficiência do catalisador",
                                "page": 2,
                            }
                        ],
                    },
                    warnings_json=[],
                )
            )
            db.commit()
            vehicle_id = vehicle.id

        page = client.get(f"/v2-clean/fleet/{vehicle_id}/diagnostics")
        assert page.status_code == 200
        assert "Histórico técnico" in page.text
        assert "Arquivo documental" in page.text
        assert "28/07/2026" in page.text
        assert "14:25:00" in page.text
        assert "P0420" in page.text
        assert "Tensão bateria" in page.text
        assert "Qualidade e proveniência da extração" in page.text
        assert "96%" in page.text
        assert "Página 1" in page.text
        assert 'data-src="/v2-clean/documents/' in page.text
        assert 'data-src="/documents/' not in page.text
        assert '<iframe title="Pré-visualização do diagnóstico" src=' not in page.text

        selected_page = client.get(
            f"/v2-clean/fleet/{vehicle_id}/diagnostics?selected=diagnostic-{profile_id}"
        )
        assert selected_page.status_code == 200
        assert 'class="clean-diagnostic-row active"' in selected_page.text

        documents_page = client.get(f"/v2-clean/fleet/{vehicle_id}/documents")
        assert documents_page.status_code == 200
        assert f"/v2-clean/fleet/{vehicle_id}/diagnostics" in documents_page.text


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


def test_diagnostic_filename_preserves_numeric_family_code():
    metadata = parse_diagnostic_filename(
        "S_RVC0_VR3UPHPX4S5036874_260521_1644.pdf"
    )

    assert metadata == {
        "machine_prefix": "S",
        "family": "RVC0",
        "vin": "VR3UPHPX4S5036874",
        "capture_date": "260521",
        "capture_time": "1644",
    }
    without_date = parse_diagnostic_filename(
        "S_PLM_VF7YAAPFBPG032534_sem_data.pdf"
    )
    assert without_date["machine_prefix"] == "S"
    assert without_date["family"] == "PLM"
    assert without_date["vin"] == "VF7YAAPFBPG032534"
    assert without_date["capture_date"] is None
    assert without_date["capture_time"] is None


def test_report_datetime_uses_machine_value_then_filename_fallback():
    printed = parse_diagnostic_report_datetime("30/03/2026 16:19:54")
    filename_fallback = parse_diagnostic_report_datetime(
        None,
        capture_date="260330",
        capture_time="1619",
    )

    assert printed == datetime(2026, 3, 30, 16, 19, 54)
    assert filename_fallback == datetime(2026, 3, 30, 16, 19)

    parsed = parse_diagnostic_payload(
        filename="A_RVC_VR3EDYHT1RJ643860_260330_1619.pdf",
        pages=[
            {
                "number": 1,
                "layout_text": "AUTEL MAXISYS\nVIN: VR3EDYHT1RJ643860",
                "native_text": "",
                "words": [],
                "ocr": None,
            }
        ],
    )
    assert parsed["normalized"]["report_datetime"] == "2026-03-30 16:19:00"


def test_same_vehicle_report_and_date_with_different_times_are_distinct():
    with diagnostic_test_context() as (testing_session, client):
        with testing_session() as db:
            vehicle = Vehicle(
                plate="BI-69-MF",
                vin="VR3EDYHT1RJ643860",
                rentway_unit_nr="485",
                lifecycle_status="active",
                operational_status="free",
            )
            db.add(vehicle)
            db.commit()
            vehicle_id = vehicle.id

        for report_time, suffix in (("09:51:18", "before"), ("16:19:54", "after")):
            response = client.post(
                f"/fleet/{vehicle_id}/diagnostics",
                data={
                    "title": "Relatório de diagnóstico do veículo",
                    "diagnostic_type": "vehicle_diagnostic_report",
                    "document_date": "2026-03-30",
                    "report_time": report_time,
                    "url_original": f"https://example.com/{suffix}.pdf",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303

        with testing_session() as db:
            diagnostics = db.scalars(
                select(DiagnosticDocument).order_by(
                    DiagnosticDocument.report_datetime
                )
            ).all()
            assert [item.report_datetime for item in diagnostics] == [
                datetime(2026, 3, 30, 9, 51, 18),
                datetime(2026, 3, 30, 16, 19, 54),
            ]
            assert len({item.document_id for item in diagnostics}) == 2

        page = client.get(f"/fleet/{vehicle_id}")
        assert page.status_code == 200
        assert "Diagnósticos <span>2</span>" in page.text
        assert "2026-03-30 09:51:18" in page.text
        assert "2026-03-30 16:19:54" in page.text


def test_ocr_only_page_recovers_spaced_vin_and_dtc():
    parsed = parse_diagnostic_payload(
        filename="relatorio_scan.pdf",
        pages=[
            {
                "number": 1,
                "layout_text": "",
                "native_text": "",
                "words": [],
                "ocr": {
                    "text": (
                        "AUTEL MAXISYS\n"
                        "VIN: VF3 YBBPFBPG057051\n"
                        "Código P0420 - eficiência do catalisador"
                    )
                },
            }
        ],
    )

    assert parsed["normalized"]["source_machine"] == "autel"
    assert parsed["normalized"]["vin"] == "VF3YBBPFBPG057051"
    assert parsed["dtcs"][0]["code"] == "P0420"


def _word(text: str, x0: float, top: float) -> dict:
    return {
        "text": text,
        "x0": x0,
        "x1": x0 + max(len(text) * 5, 5),
        "top": top,
        "bottom": top + 8,
        "doctop": top,
    }


def test_coordinate_readers_keep_optional_engine_fields_from_both_machines():
    autel_page = {
        "number": 1,
        "height": 842,
        "words": [
            _word("NO.", 23, 100),
            _word("Nome", 80, 100),
            _word("Valor", 419, 100),
            _word("Unidade", 532, 100),
            _word("1", 23, 132),
            _word("Taxa", 80, 132),
            _word("de", 110, 132),
            _word("diluição", 125, 132),
            _word("estimada", 170, 132),
            _word("2.4", 419, 132),
            _word("%", 532, 132),
            _word("2", 23, 164),
            _word("Estado", 80, 164),
            _word("SCR", 120, 164),
            _word("Ativo", 419, 164),
        ],
    }
    stellantis_page = {
        "number": 1,
        "height": 842,
        "words": [
            _word("Descrição", 36, 100),
            _word("Valor", 155, 100),
            _word("Unidade", 273, 100),
            _word("Ajuda", 392, 100),
            _word("Pressão", 31, 130),
            _word("de", 75, 130),
            _word("óleo", 31, 142),
            _word("1.047", 147, 136),
            _word("Bar", 268, 136),
            _word("Medição", 386, 130),
            _word("do", 425, 130),
            _word("calculador", 445, 130),
        ],
    }

    autel = extract_coordinate_observations([autel_page], "autel")
    stellantis = extract_coordinate_observations(
        [stellantis_page],
        "stellantis_diagbox",
    )

    assert autel[0]["label"] == "Taxa de diluição estimada"
    assert autel[0]["value"] == "2.4"
    assert autel[1]["label"] == "Estado SCR"
    assert autel[1]["unit"] is None
    assert stellantis == [
        {
            "sequence": 1,
            "label": "Pressão de óleo",
            "value": "1.047",
            "unit": "Bar",
            "help": "Medição do calculador",
            "page": 1,
            "source": "stellantis_coordinate_table",
            "anchor_top": 136.0,
        }
    ]


def test_extraction_history_is_lossless_idempotent_and_associates_by_vin():
    with diagnostic_test_context() as (testing_session, client):
        with testing_session() as db:
            vehicle = Vehicle(
                plate="DI-20-AG",
                vin="VF3YBBPFBPG057051",
                rentway_unit_nr="620",
                lifecycle_status="active",
                operational_status="free",
            )
            document = make_document(
                title="Informações lubrificação motor",
                document_type="workshop_diagnostic",
                storage_path=r"C:\diagnostics\A_ILM_example.pdf",
            )
            db.add_all([vehicle, document])
            db.flush()
            profile = ensure_diagnostic_profile(db, document)
            db.flush()
            payload = {
                "extractor_name": "carfast_diagnostic_pdf",
                "extractor_version": "1.0.0",
                "parser_name": "autel_diagnostic_parser",
                "parser_version": "1.0.0",
                "source_machine": "autel",
                "source_family": "ILM",
                "source_filename": "A_ILM_VF3YBBPFBPG057051_260117_0952.pdf",
                "source_sha256": "a" * 64,
                "source_page_count": 1,
                "extraction_method": "native_text+layout_words",
                "extraction_status": "extracted",
                "confidence": 0.98,
                "native_text": "todo o texto nativo, sem truncar",
                "ocr_text": None,
                "raw_metadata": {"pdf": {"/Producer": "iText"}, "filename": {}},
                "pages": [
                    {
                        "number": 1,
                        "native_text": "todo o texto nativo, sem truncar",
                        "layout_text": "todo o texto nativo, sem truncar",
                        "words": [{"text": "todo", "x0": 1, "top": 1}],
                    }
                ],
                "normalized": {
                    "vin": "VF3YBBPFBPG057051",
                    "plate": None,
                    "report_number": "MAXIA20260117095227",
                    "tool": "MaxiDAS DS900-BT",
                    "tool_serial": "VX2GR7V02050",
                    "technician_name": None,
                    "odometer": None,
                    "report_datetime": "2026-01-17 09:52:27",
                    "diagnostic_type": "engine_lubrication_information",
                },
                "dynamic_fields": {
                    "observations": [
                        {
                            "label": "Taxa de diluição estimada",
                            "value": "2.4",
                            "unit": "%",
                        }
                    ],
                    "label_values": [],
                    "dtcs": [],
                },
                "warnings": [],
            }

            first = persist_diagnostic_extraction(db, profile, payload)
            profile.ocr_status = "pending"
            profile.diagnostic_status = "processing"
            profile.validation_status = "pending"
            second = persist_diagnostic_extraction(db, profile, payload)
            db.flush()

            assert first.id == second.id
            assert len(db.scalars(select(DiagnosticExtraction)).all()) == 1
            assert first.raw_metadata_json["pdf"]["/Producer"] == "iText"
            assert first.pages_json[0]["words"][0]["text"] == "todo"
            assert first.dynamic_fields_json["observations"][0]["value"] == "2.4"
            assert profile.report_number == "MAXIA20260117095227"
            assert profile.report_datetime == datetime(2026, 1, 17, 9, 52, 27)
            assert profile.diagnostic_tool == "MaxiDAS DS900-BT"
            assert profile.ocr_status == "extracted"
            assert profile.diagnostic_status == "ready_for_review"
            assert profile.validation_status == "needs_review"
            assert document.vehicle_id == vehicle.id
            assert document.file_hash == "a" * 64
            assert document.document_date.isoformat() == "2026-01-17"
            document_id = document.id
            db.commit()

        detail = client.get(f"/documents/{document_id}")
        assert detail.status_code == 200
        assert "Dados técnicos completos da extração" in detail.text
        assert "Taxa de diluição estimada" in detail.text
        assert "autel_diagnostic_parser" in detail.text


def test_diagnostic_center_separates_health_from_operational_states():
    with diagnostic_test_context() as (testing_session, client):
        with testing_session() as db:
            vehicle = Vehicle(
                plate="AU-10-DI",
                vin="VF7AUDITDIAGNOSTIC",
                rentway_unit_nr="710",
                lifecycle_status="active",
                operational_status="free",
            )
            extracted_document = make_document(
                title="Leitura de defeitos",
                document_type="workshop_diagnostic",
                vehicle_id=None,
            )
            pending_document = make_document(
                title="Plano de manutenção",
                document_type="workshop_diagnostic",
                original_name="plano.pdf",
                file_name="plano.pdf",
                vehicle_id=None,
            )
            db.add_all([vehicle, extracted_document, pending_document])
            db.flush()
            extracted_document.vehicle_id = vehicle.id
            pending_document.vehicle_id = vehicle.id
            extracted_profile = DiagnosticDocument(
                document_id=extracted_document.id,
                diagnostic_type="fault_codes_global_test",
                diagnostic_status="processing",
                association_status="confirmed",
                ocr_status="pending",
                validation_status="pending",
            )
            pending_profile = DiagnosticDocument(
                document_id=pending_document.id,
                diagnostic_type="manufacturer_maintenance_plan",
                diagnostic_status="processing",
                association_status="confirmed",
                ocr_status="pending",
                validation_status="pending",
            )
            db.add_all([extracted_profile, pending_profile])
            db.flush()
            extracted_profile_id = extracted_profile.id
            db.add(
                DiagnosticExtraction(
                    diagnostic_document_id=extracted_profile.id,
                    extractor_name="diagnostic_pdf",
                    extractor_version="1",
                    parser_name="autel",
                    parser_version="1",
                    source_machine="autel",
                    source_family="LD",
                    source_filename="leitura.pdf",
                    source_sha256="e" * 64,
                    source_page_count=1,
                    extraction_method="native_text",
                    extraction_status="extracted",
                    confidence=0.9,
                    native_text="P0420",
                    normalized_data_json={"vin": vehicle.vin},
                    dynamic_fields_json={"dtcs": [{"code": "P0420"}]},
                    warnings_json=[],
                )
            )
            db.commit()

        page = client.get("/v2-clean/diagnostics")
        assert page.status_code == 200
        assert "Auditoria de diagnósticos" in page.text
        assert "Estado incoerente" in page.text
        assert "Sem extração" in page.text
        assert "Lotes importados" in page.text
        assert "Importação sem lote" in page.text
        assert f"selected=diagnostic%3A{extracted_profile_id}" in page.text

        reconciled = client.post(
            "/v2-clean/diagnostics/reconcile",
            follow_redirects=False,
        )
        assert reconciled.status_code == 303
        assert "reconciled=1" in reconciled.headers["location"]

        with testing_session() as db:
            profiles = db.scalars(
                select(DiagnosticDocument).order_by(DiagnosticDocument.id)
            ).all()
            assert profiles[0].ocr_status == "extracted"
            assert profiles[0].diagnostic_status == "ready_for_review"
            assert profiles[0].validation_status == "needs_review"
            assert profiles[1].ocr_status == "pending"
