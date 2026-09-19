from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from app.core.database import SessionLocal
from app.services.workshop_history_unification import build_workshop_history_unification_plan


def _write_csv(path: Path, rows: list[dict]) -> None:
    headers = [
        "sequence",
        "canonical_reference",
        "target_process_id",
        "event_at",
        "vehicle_id",
        "plate",
        "title",
        "original_status",
        "proposed_status",
        "plan_operation",
        "source_records",
        "legacy_references",
        "issues",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, delimiter=";")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    **row,
                    "source_records": " | ".join(row["source_records"]),
                    "legacy_references": " | ".join(row["legacy_references"]),
                    "issues": " | ".join(row["issues"]),
                }
            )


def _write_report(path: Path, payload: dict) -> None:
    summary = payload["summary"]
    lines = [
        "# Pré-visualização da unificação do histórico de Oficina",
        "",
        "Esta execução é apenas de leitura. Não criou, renumerou ou alterou processos.",
        "",
        f"- Formato proposto: `{payload['numbering_format']}`.",
        f"- Processos do modelo atual: {summary['phased_records']}.",
        f"- Processos do modelo antigo: {summary['legacy_records']}.",
        f"- Processos lógicos após ligações já conhecidas: {summary['logical_processes']}.",
        f"- Processos históricos a criar: {summary['to_create']}.",
        f"- Processos atuais a renumerar: {summary['to_renumber']}.",
        f"- Casos que exigem revisão: {summary['review_required']}.",
        f"- Possíveis duplicados: {summary['possible_duplicates']}.",
        "",
        "## Barreiras para aplicação",
        "",
        "- Rever todos os casos assinalados antes de qualquer escrita.",
        "- Confirmar o mapa de referências antigas para novas.",
        "- Validar documentos, tarefas, materiais e stock sem repetir movimentos.",
        "- Executar primeiro numa cópia PostgreSQL isolada.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gera, sem escritas na base de dados, o plano de unificação da Oficina."
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start-at", type=int, default=1)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        plan = build_workshop_history_unification_plan(db, start_at=args.start_at)
    payload = plan.to_dict()

    json_path = args.output_dir / "workshop_history_unification_plan.json"
    csv_path = args.output_dir / "workshop_history_reference_map.csv"
    report_path = args.output_dir / "WORKSHOP_HISTORY_UNIFICATION_REPORT.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_csv(csv_path, payload["items"])
    _write_report(report_path, payload)
    print(
        json.dumps(
            {"output": str(args.output_dir), "summary": payload["summary"]}, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
