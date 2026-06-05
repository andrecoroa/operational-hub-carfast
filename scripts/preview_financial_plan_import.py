from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import SessionLocal
from app.services.financial_plan_importer import (
    DEFAULT_PLAN_ROOT,
    DEFAULT_SALES_DEBT_MAP,
    preview_financial_plan_import,
    write_preview_report,
)


def main() -> None:
    parser = ArgumentParser(description="Preview/dry-run da importação de planos financeiros para documentos.")
    parser.add_argument("--plan-root", default=str(DEFAULT_PLAN_ROOT), help="Pasta fonte dos planos de renda.")
    parser.add_argument("--sales-debt-map", default=str(DEFAULT_SALES_DEBT_MAP), help="Mapa venda/dívida para cruzamento.")
    parser.add_argument("--output-dir", default="", help="Diretório de saída. Por defeito usa exports/financial_plan_preview_<timestamp>.")
    parser.add_argument("--use-db", action="store_true", help="Consultar a frota da app para preencher vehicle_id e validar matrículas.")
    parser.add_argument("--no-db", action="store_true", help="Compatibilidade: mantém execução sem consultar a base de dados.")
    args = parser.parse_args()

    output_dir = Path(args.output_dir) if args.output_dir else Path("exports") / f"financial_plan_preview_{datetime.now():%Y%m%d_%H%M%S}"
    db = None
    db_error = ""
    if args.use_db and not args.no_db:
        try:
            db = SessionLocal()
        except Exception as exc:
            db_error = str(exc)

    try:
        report = preview_financial_plan_import(
            db,
            plan_root=Path(args.plan_root),
            sales_debt_map=Path(args.sales_debt_map),
        )
        if db_error:
            report["db_error"] = db_error
        outputs = write_preview_report(report, output_dir)
    finally:
        if db is not None:
            db.close()

    print("Preview gerado.")
    print(f"Saida: {output_dir}")
    print(f"Resumo: {report['summary']}")
    print(f"Viaturas carregadas da app: {report['vehicle_count']}")
    if db_error:
        print(f"Aviso DB: {db_error}")
    for key, value in outputs.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
