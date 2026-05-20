import csv
import hashlib
import io
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.imports import ImportBatch, ImportError, ImportFile, ImportRawRow
from app.models.vehicles import Vehicle
from app.models.workshop import WorkshopProcess, WorkshopTechnicalReading
from app.services.audit import record_audit
from app.services.spreadsheets import (
    build_column_lookup,
    clean_int,
    clean_text,
    excel_date_to_iso,
    first_row_value,
    iter_xlsx_rows,
    normalize_header,
)
from app.services.vehicles import find_vehicle_by_any_identifier, normalize_identifier


TECHNICAL_HISTORY_IMPORT_COLUMNS = [
    ("matricula", "Matrícula", "Obrigatório se não houver VIN"),
    ("vin", "VIN / chassi", "Obrigatório se não houver matrícula"),
    ("data_relatorio", "Data do relatório/documento", "Obrigatório"),
    ("origem_maquina", "Máquina/origem", "Obrigatório. Ex.: PSA-DIAG/Stellantis, Autel, Service Box"),
    ("tipo_registo", "Tipo de registo", "Obrigatório"),
    ("resumo", "Resumo", "Opcional"),
    ("link_documento_original", "Link documento original", "Obrigatório"),
    ("km_leitura", "KM leitura", "Opcional"),
    ("modulo_calculador", "Módulo/calculador", "Opcional. Ex.: BSI2010_EV"),
    ("processo_oficina_id", "ID processo oficina", "Opcional"),
    ("km_ultima_reposicao_manutencao", "KM última reposição manutenção", "Opcional"),
    ("km_ate_proxima_manutencao", "KM até próxima manutenção", "Opcional"),
    ("dias_ate_proxima_manutencao", "Dias até próxima manutenção", "Opcional"),
    ("dias_desde_ultima_reposicao_manutencao", "Dias desde última reposição manutenção", "Opcional"),
    ("numero_manutencoes_efetuadas", "Nº manutenções efetuadas", "Opcional"),
    ("limite_temporal_ultrapassado", "Limite temporal ultrapassado", "Opcional"),
    ("limite_quilometrico_ultrapassado", "Limite quilométrico ultrapassado", "Opcional"),
    ("limiar_manutencao_km", "Limiar manutenção km", "Opcional"),
    ("duracao_manutencao_meses", "Duração manutenção meses", "Opcional"),
    ("inicio_primeira_manutencao_km", "Início primeira manutenção km", "Opcional"),
    ("duracao_antes_primeira_manutencao_meses", "Duração antes primeira manutenção meses", "Opcional"),
    ("gestao_manutencao", "Gestão manutenção", "Opcional. Dinâmica/Estática"),
    ("taxa_diluicao_oleo", "Taxa diluição óleo", "Opcional"),
    ("taxa_carbono_oleo", "Taxa carbono óleo", "Opcional"),
    ("protecao_anti_diluicao", "Proteção anti-diluição", "Opcional"),
    ("intervalo_calculado_calculador_km", "Intervalo calculado pelo calculador", "Opcional"),
    ("existem_defeitos", "Existem defeitos", "Opcional"),
    ("numero_total_codigos_eventos", "Nº total códigos/eventos", "Opcional"),
    ("codigos_principais", "Códigos principais", "Opcional"),
    ("defeito_critico", "Defeito crítico", "Opcional"),
    ("estado_principal", "Estado principal", "Opcional"),
    ("caracterizacao_defeito", "Caracterização/resumo defeito", "Opcional"),
    ("km_associado_defeito", "KM associado ao defeito", "Opcional"),
    ("acao_recomendada", "Ação recomendada", "Opcional"),
    ("fornecedor_ecu", "Fornecedor ECU", "Opcional"),
    ("referencia_material", "Referência material", "Opcional"),
    ("referencia_software", "Referência software", "Opcional"),
    ("edicao_calibracao", "Edição calibração", "Opcional"),
    ("edicao_software", "Edição software", "Opcional"),
    ("data_telecarregamento", "Data telecarregamento", "Opcional"),
    ("numero_telecarregamentos", "Nº telecarregamentos", "Opcional"),
    ("origem_ficheiro", "Origem ficheiro", "Opcional"),
    ("observacoes_importacao", "Observações importação", "Opcional"),
]

TEXT_FIELD_MAP = {
    "machine_source": ["origem_maquina", "maquina", "machine", "source_machine", "origem"],
    "report_type": ["tipo_registo", "tipo_relatorio", "reading_type", "tipo"],
    "summary": ["resumo", "summary", "descricao", "descrição"],
    "external_url": ["link_documento_original", "link_documento", "document_url", "external_url", "url"],
    "module_name": ["modulo_calculador", "módulo_calculador", "modulo", "calculador", "ecu"],
    "source_file": ["origem_ficheiro", "ficheiro_origem", "source_file", "pdf_origem"],
    "import_note": ["observacoes_importacao", "observações_importação", "notas_importacao"],
    "import_status": ["estado_importacao"],
    "import_key": ["chave_importacao"],
    "duplicate_candidate": ["duplicado_provavel"],
    "chronological_order": ["ordem_cronologica"],
    "work_order_reference": ["folha_obra"],
    "document_time": ["hora_documento"],
    "document_datetime": ["data_hora_documento"],
    "source_created_by": ["criado_por"],
    "source_created_at": ["criado_em"],
    "maintenance_last_reset_km": ["km_ultima_reposicao_manutencao", "maintenance_last_reset_km"],
    "maintenance_km_until_next": ["km_ate_proxima_manutencao", "maintenance_km_until_next"],
    "maintenance_days_until_next": ["dias_ate_proxima_manutencao", "maintenance_days_until_next"],
    "maintenance_days_since_last_reset": [
        "dias_desde_ultima_reposicao_manutencao",
        "dias_desde_ultima_reposicao",
        "maintenance_days_since_last_reset",
    ],
    "maintenance_count": ["numero_manutencoes_efetuadas", "n_manutencoes", "maintenance_count"],
    "maintenance_temporal_limit_exceeded": ["limite_temporal_ultrapassado"],
    "maintenance_distance_limit_exceeded": ["limite_quilometrico_ultrapassado"],
    "maintenance_threshold_km": ["limiar_manutencao_km", "maintenance_threshold_km"],
    "maintenance_duration_months": ["duracao_manutencao_meses", "maintenance_duration_months"],
    "maintenance_first_start_km": ["inicio_primeira_manutencao_km"],
    "maintenance_first_duration_months": ["duracao_antes_primeira_manutencao_meses"],
    "maintenance_management_mode": ["gestao_manutencao", "maintenance_management_mode"],
    "oil_dilution_rate": ["taxa_diluicao_oleo", "taxa_diluicao_oleo_pct", "oil_dilution_rate"],
    "oil_carbon_rate": ["taxa_carbono_oleo", "taxa_carbono_oleo_pct", "oil_carbon_rate"],
    "oil_anti_dilution_status": ["protecao_anti_diluicao", "oil_anti_dilution_status"],
    "engine_calculated_interval_km": ["intervalo_calculado_calculador_km"],
    "faults_present": ["existem_defeitos", "faults_present"],
    "fault_event_count": ["numero_total_codigos_eventos", "total_codigos", "fault_event_count"],
    "fault_codes": ["codigos_principais", "fault_codes"],
    "critical_fault": ["defeito_critico", "critical_fault"],
    "fault_main_status": ["estado_principal", "fault_main_status"],
    "fault_characterization": [
        "caracterizacao_defeito",
        "caracterização_defeito",
        "caracterizacao_resumo_defeito",
        "fault_characterization",
    ],
    "fault_odometer_km": ["km_associado_defeito", "fault_odometer_km"],
    "recommended_action": ["acao_recomendada", "ação_recomendada", "recommended_action"],
    "ecu_supplier": ["fornecedor_ecu", "nome_fornecedor"],
    "material_reference": ["referencia_material", "referência_material"],
    "software_reference": ["referencia_software", "referência_software"],
    "calibration_edition": ["edicao_calibracao", "edição_calibração"],
    "software_edition": ["edicao_software", "edição_software"],
    "download_date": ["data_telecarregamento", "download_date"],
    "download_count": ["numero_telecarregamentos", "n_telecarregamentos", "download_count"],
}

REPORT_TYPE_TO_READING_TYPE = {
    "informacoesmanutencao": "maintenance_info",
    "informacaomanutencao": "maintenance_info",
    "manutencao": "maintenance_info",
    "parametrizacaomanutencao": "maintenance_info",
    "parametrizacaointervalomanutencao": "maintenance_info",
    "parametrosmanutencaorecuperadosdoveiculo": "maintenance_info",
    "lubrificacaomotor": "lubrication_info",
    "informacoeslubrificacaomotor": "lubrication_info",
    "leituradefeitos": "fault_reading",
    "jornaldefeitos": "fault_reading",
    "dosdefeitos": "fault_reading",
    "identificacaotelecarregamento": "software_identification",
    "telecarregamentoecuidentificacao": "software_identification",
    "identificacao": "software_identification",
    "folhaobra": "other",
    "fatura": "other",
}


def technical_history_template_csv() -> str:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow([column for column, _, _ in TECHNICAL_HISTORY_IMPORT_COLUMNS])
    writer.writerow(
        [
            "BC-10-EB",
            "VR7EFYHT2PJ697244",
            "2026-04-20",
            "PSA-DIAG/Stellantis",
            "informacoes_manutencao",
            "Leitura de manutenção antes da revisão",
            "https://sharepoint/relatorio.pdf",
            "5149",
            "BSI2010_EV",
            "",
            "9587.7",
            "380",
            "542",
            "188",
            "2",
            "Não",
            "Sim",
            "40000",
            "24",
            "0",
            "0",
            "Dinâmico",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "amostra.pdf",
            "",
        ]
    )
    return output.getvalue()


def iter_import_rows(path: Path):
    if path.suffix.lower() == ".csv":
        raw_bytes = path.read_bytes()
        try:
            text = raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw_bytes.decode("cp1252")
        reader = csv.DictReader(io.StringIO(text))
        headers = reader.fieldnames or []
        for row_number, raw in enumerate(reader, start=2):
            row = tuple(raw.get(header) for header in headers)
            yield "CSV", headers, row_number, row, raw
        return

    yield from iter_xlsx_rows(path)


def normalize_report_type(value: str | None) -> str:
    key = normalize_header(value or "")
    return REPORT_TYPE_TO_READING_TYPE.get(key, "other")


def parse_date_value(value: Any) -> date | None:
    iso = excel_date_to_iso(value)
    if not iso:
        return None
    try:
        return date.fromisoformat(iso[:10])
    except ValueError:
        return None


def parse_process_reference(value: Any) -> int | None:
    text = clean_text(value)
    if not text:
        return None
    number_match = re.search(r"\d+", text)
    if not number_match:
        return None
    return clean_int(number_match.group(0))


def row_text(row: tuple[Any, ...], col: dict[str, int], field: str) -> str:
    return clean_text(first_row_value(row, col, TEXT_FIELD_MAP[field])) or ""


def build_reading_data(row: tuple[Any, ...], col: dict[str, int], reading_date: date, batch_id: int) -> dict[str, str]:
    data = {
        key: row_text(row, col, key)
        for key in TEXT_FIELD_MAP
        if key
        not in {
            "summary",
            "external_url",
            "report_type",
            "machine_source",
        }
    }
    data = {key: value for key, value in data.items() if value}
    data["record_origin"] = "historical_import"
    data["import_batch_id"] = str(batch_id)

    machine_source = row_text(row, col, "machine_source")
    report_type = row_text(row, col, "report_type")
    if machine_source:
        data["machine_source"] = machine_source
    if report_type:
        data["source_report_type"] = report_type

    days_until_next = clean_int(data.get("maintenance_days_until_next"))
    if days_until_next is not None:
        data["maintenance_next_due_date"] = (reading_date + timedelta(days=days_until_next)).isoformat()
    days_since_reset = clean_int(data.get("maintenance_days_since_last_reset"))
    if days_since_reset is not None:
        data["maintenance_last_reset_date_estimated"] = (
            reading_date - timedelta(days=days_since_reset)
        ).isoformat()
    duration_months = clean_int(data.get("maintenance_duration_months"))
    if days_until_next is not None and duration_months is not None:
        plan_days = round(duration_months * 365 / 12)
        days_since_last = max(plan_days - days_until_next, 0)
        data["maintenance_days_since_last_estimated"] = str(days_since_last)
        data["maintenance_last_date_estimated"] = (reading_date - timedelta(days=days_since_last)).isoformat()
    return data


def import_workshop_technical_history_file(
    db: Session,
    path: str | Path,
    original_name: str | None = None,
    imported_by_id: int | None = None,
) -> dict[str, int]:
    file_path = Path(path)
    stats = {"total_rows": 0, "created_rows": 0, "updated_rows": 0, "skipped_rows": 0, "error_rows": 0}
    batch = ImportBatch(
        source_system="workshop_history",
        import_type="technical_history",
        status="running",
        imported_by_id=imported_by_id,
    )
    db.add(batch)
    db.flush()

    try:
        for sheet_name, headers, row_number, row, raw in iter_import_rows(file_path):
            if not db.scalar(select(ImportFile).where(ImportFile.batch_id == batch.id)):
                db.add(
                    ImportFile(
                        batch_id=batch.id,
                        original_name=original_name or file_path.name,
                        file_name=file_path.name,
                        storage_path=str(file_path),
                        sheet_name=sheet_name,
                        columns_json=headers,
                    )
                )

            col = build_column_lookup(headers)
            stats["total_rows"] += 1
            raw_json = json.dumps(raw, ensure_ascii=False, default=str, sort_keys=True)
            raw_hash = hashlib.sha1(raw_json.encode("utf-8")).hexdigest()
            plate = normalize_identifier(clean_text(first_row_value(row, col, ["matricula", "plate"])))
            vin = normalize_identifier(clean_text(first_row_value(row, col, ["vin", "vin_chassi", "chassi", "chassis"])))
            external_reference = plate or vin
            db.add(
                ImportRawRow(
                    batch_id=batch.id,
                    row_number=row_number,
                    external_reference=external_reference,
                    raw_json=raw,
                    row_hash=raw_hash,
                )
            )

            try:
                if not external_reference:
                    raise ValueError("Linha sem matrícula ou VIN.")
                vehicle = find_vehicle_by_any_identifier(db, plate=plate, vin=vin)
                if not vehicle:
                    raise ValueError(f"Viatura não encontrada: {external_reference}.")
                reading_date = parse_date_value(
                    first_row_value(row, col, ["data_relatorio", "data_documento", "data_leitura", "reading_date"])
                )
                if not reading_date:
                    raise ValueError("Data do relatório/documento em falta ou inválida.")
                machine_source = row_text(row, col, "machine_source")
                if not machine_source:
                    raise ValueError("Máquina/origem em falta.")
                report_type = row_text(row, col, "report_type")
                if not report_type:
                    raise ValueError("Tipo de registo em falta.")
                external_url = row_text(row, col, "external_url")
                if not external_url:
                    raise ValueError("Link do documento original em falta.")

                process_id = parse_process_reference(
                    first_row_value(row, col, ["processo_oficina_id", "processo_oficina", "process_id"])
                )
                process = db.get(WorkshopProcess, process_id) if process_id else None
                if process_id and not process:
                    raise ValueError(f"Processo de oficina #{process_id} não encontrado.")
                if process and process.vehicle_id != vehicle.id:
                    raise ValueError(f"Processo #{process_id} não pertence à viatura {external_reference}.")

                data_json = build_reading_data(row, col, reading_date, batch.id)
                reading = WorkshopTechnicalReading(
                    process_id=process.id if process else None,
                    vehicle_id=vehicle.id,
                    user_id=imported_by_id,
                    reading_type=normalize_report_type(report_type),
                    reading_date=reading_date,
                    odometer_km=clean_int(first_row_value(row, col, ["km_leitura", "odometer_km"])),
                    summary=row_text(row, col, "summary") or None,
                    data_json=data_json or None,
                    differences_json=None,
                    storage_provider="external",
                    external_url=external_url,
                )
                db.add(reading)
                db.flush()
                stats["created_rows"] += 1
            except Exception as exc:
                stats["error_rows"] += 1
                db.add(
                    ImportError(
                        batch_id=batch.id,
                        row_number=row_number,
                        entity_type="workshop_technical_reading",
                        error_message=str(exc),
                        raw_json=raw,
                    )
                )

        batch.status = "completed" if stats["error_rows"] == 0 else "completed_with_errors"
        batch.total_rows = stats["total_rows"]
        batch.created_rows = stats["created_rows"]
        batch.updated_rows = stats["updated_rows"]
        batch.skipped_rows = stats["skipped_rows"]
        batch.error_rows = stats["error_rows"]
        batch.detail = "Importação de histórico técnico de oficina."
        record_audit(
            db,
            action="import.workshop_technical_history.completed",
            entity_type="import_batch",
            entity_id=batch.id,
            after_json=stats,
            user_id=imported_by_id,
        )
        db.commit()
    except Exception:
        batch.status = "failed"
        batch.total_rows = stats["total_rows"]
        batch.error_rows = stats["error_rows"] + 1
        db.commit()
        raise

    return {"batch_id": batch.id, **stats}
