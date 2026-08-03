from __future__ import annotations

import hashlib
import logging
from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import DbSession
from app.models.admin import User
from app.models.documents import Document, DocumentEvent
from app.models.stock import (
    StockArticle,
    StockArticleSupplierRef,
    StockCategory,
    StockInvoiceImport,
    StockInvoiceLine,
    StockLocation,
    StockMinimum,
    StockMovement,
    StockReceipt,
    StockReceiptInvoiceLink,
    StockReceiptLine,
    StockSupplier,
)
from app.schemas.stock import (
    StockInvoiceLineReview,
    StockInvoiceReview,
    StockMovementCreate,
    StockReceiptCreate,
    StockReceiptLineCreate,
)
from app.services.authorization import get_user_permission_codes
from app.services.document_workflow import classify_invoice_nature
from app.services.stock import (
    StockDomainError,
    create_manual_movement,
    create_physical_receipt,
    ensure_invoice_import,
    extract_stock_invoice,
    low_stock_rows,
    review_and_validate_invoice,
    stock_balances,
)
from app.web.router import document_archive_root, sanitize_archive_component, templates

stock_router = APIRouter()
ZERO = Decimal("0")
logger = logging.getLogger(__name__)


def _user_id(request: Request) -> int | None:
    value = request.session.get("user_id") if hasattr(request, "session") else None
    return int(value) if value else None


def _permission_codes(request: Request, db: DbSession) -> set[str]:
    user_id = _user_id(request)
    if not user_id:
        return set()
    user = db.get(User, user_id)
    return get_user_permission_codes(db, user) if user and user.active else set()


def _denied(request: Request, db: DbSession, *codes: str) -> RedirectResponse | None:
    if not _user_id(request):
        return RedirectResponse("/login?next=/v2-clean/stock", status_code=303)
    if not _permission_codes(request, db).intersection(codes):
        return RedirectResponse("/v2-clean?error=forbidden", status_code=303)
    return None


def _page_context(request: Request, db: DbSession) -> dict:
    permissions = _permission_codes(request, db)
    return {
        "can_operate_stock": bool(permissions & {"stock.operate", "stock.manage", "admin.manage"}),
        "can_manage_stock": bool(permissions & {"stock.manage", "admin.manage"}),
    }


def _parse_date(value: str) -> date | None:
    return date.fromisoformat(value.strip()) if value.strip() else None


def _parse_decimal(value: str, default: str = "0") -> Decimal:
    clean = (value or default).strip().replace(" ", "")
    if "," in clean:
        clean = clean.replace(".", "").replace(",", ".")
    return Decimal(clean or default)


def _article_rows(db: DbSession, articles: list[StockArticle]) -> list[dict]:
    article_ids = [article.id for article in articles]
    balances = stock_balances(db, article_ids=article_ids)
    locations = db.scalars(
        select(StockLocation).where(StockLocation.active.is_(True)).order_by(StockLocation.id)
    ).all()
    categories = {category.id: category for category in db.scalars(select(StockCategory)).all()}
    suppliers = {supplier.id: supplier for supplier in db.scalars(select(StockSupplier)).all()}
    minimums = {
        (minimum.article_id, minimum.location_id): minimum.minimum_quantity
        for minimum in db.scalars(
            select(StockMinimum).where(StockMinimum.article_id.in_(article_ids or [-1]))
        ).all()
    }
    rows = []
    for article in articles:
        by_location = {
            location.code: balances.get((article.id, location.id), ZERO) for location in locations
        }
        minimum_total = sum(
            (minimums.get((article.id, location.id), ZERO) for location in locations), ZERO
        )
        total = sum(by_location.values(), ZERO)
        low = any(
            balances.get((article.id, location.id), ZERO)
            < minimums.get((article.id, location.id), ZERO)
            for location in locations
            if (article.id, location.id) in minimums
        )
        rows.append(
            {
                "article": article,
                "category": categories.get(article.category_id),
                "supplier": suppliers.get(article.primary_supplier_id),
                "by_location": by_location,
                "available": total,
                "minimum": minimum_total,
                "low": low,
            }
        )
    return rows


@stock_router.get("/v2-clean/stock", response_class=HTMLResponse)
def stock_dashboard(request: Request, db: DbSession):
    if denied := _denied(
        request, db, "stock.read", "stock.operate", "stock.manage", "admin.manage"
    ):
        return denied
    articles = db.scalars(
        select(StockArticle).where(StockArticle.active.is_(True)).order_by(StockArticle.name)
    ).all()
    rows = _article_rows(db, articles)
    low_rows = low_stock_rows(db)
    physical_receipts = int(db.scalar(select(func.count()).select_from(StockReceipt)) or 0)
    value = sum(
        (max(row["available"], ZERO) * (row["article"].average_cost or ZERO) for row in rows),
        ZERO,
    )
    recent_movements = db.execute(
        select(StockMovement, StockArticle)
        .join(StockArticle, StockArticle.id == StockMovement.article_id)
        .order_by(StockMovement.occurred_at.desc(), StockMovement.id.desc())
        .limit(8)
    ).all()
    return templates.TemplateResponse(
        request,
        "clean_stock_dashboard.html",
        {
            **_page_context(request, db),
            "metrics": {
                "articles": len(articles),
                "value": value,
                "low": len(low_rows),
                "physical_receipts": physical_receipts,
            },
            "low_rows": low_rows[:8],
            "article_rows": rows[:25],
            "recent_movements": recent_movements,
        },
    )


@stock_router.get("/v2-clean/stock/articles", response_class=HTMLResponse)
def stock_articles(
    request: Request,
    db: DbSession,
    q: str = "",
    category_id: int | None = None,
    supplier_id: int | None = None,
    location_id: int | None = None,
    state: str = "active",
    low_stock: bool = False,
):
    if denied := _denied(
        request, db, "stock.read", "stock.operate", "stock.manage", "admin.manage"
    ):
        return denied
    statement = select(StockArticle).order_by(StockArticle.name, StockArticle.id)
    if q.strip():
        token = f"%{q.strip()}%"
        statement = statement.where(
            or_(StockArticle.internal_ref.ilike(token), StockArticle.name.ilike(token))
        )
    if category_id:
        statement = statement.where(StockArticle.category_id == category_id)
    if supplier_id:
        statement = statement.where(StockArticle.primary_supplier_id == supplier_id)
    if state in {"active", "inactive"}:
        statement = statement.where(StockArticle.active.is_(state == "active"))
    rows = _article_rows(db, db.scalars(statement).all())
    if location_id:
        location = db.get(StockLocation, location_id)
        if location:
            rows = [row for row in rows if row["by_location"].get(location.code, ZERO) != ZERO]
    if low_stock:
        rows = [row for row in rows if row["low"]]
    return templates.TemplateResponse(
        request,
        "clean_stock_articles.html",
        {
            **_page_context(request, db),
            "rows": rows,
            "categories": db.scalars(select(StockCategory).order_by(StockCategory.name)).all(),
            "suppliers": db.scalars(select(StockSupplier).order_by(StockSupplier.name)).all(),
            "locations": db.scalars(select(StockLocation).order_by(StockLocation.name)).all(),
            "filters": {
                "q": q,
                "category_id": category_id,
                "supplier_id": supplier_id,
                "location_id": location_id,
                "state": state,
                "low_stock": low_stock,
            },
        },
    )


@stock_router.post("/v2-clean/stock/articles")
def stock_article_create(
    request: Request,
    db: DbSession,
    internal_ref: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    unit: str = Form("un."),
    category_id: int | None = Form(None),
    classification: str = Form(""),
    primary_supplier_id: int | None = Form(None),
):
    if denied := _denied(request, db, "stock.operate", "stock.manage", "admin.manage"):
        return denied
    clean_ref = internal_ref.strip()
    if db.scalar(select(StockArticle).where(StockArticle.internal_ref == clean_ref)):
        return RedirectResponse("/v2-clean/stock/articles?error=duplicate_ref", status_code=303)
    article = StockArticle(
        internal_ref=clean_ref,
        name=name.strip(),
        description=description.strip() or None,
        unit=unit.strip() or "un.",
        category_id=category_id,
        classification=classification.strip() or None,
        primary_supplier_id=primary_supplier_id,
    )
    db.add(article)
    db.commit()
    return RedirectResponse(f"/v2-clean/stock/articles/{article.id}?saved=1", status_code=303)


@stock_router.get("/v2-clean/stock/articles/{article_id}", response_class=HTMLResponse)
def stock_article_detail(request: Request, article_id: int, db: DbSession):
    if denied := _denied(
        request, db, "stock.read", "stock.operate", "stock.manage", "admin.manage"
    ):
        return denied
    article = db.get(StockArticle, article_id)
    if not article:
        return RedirectResponse("/v2-clean/stock/articles?error=missing", status_code=303)
    row = _article_rows(db, [article])[0]
    references = db.execute(
        select(StockArticleSupplierRef, StockSupplier)
        .join(StockSupplier, StockSupplier.id == StockArticleSupplierRef.supplier_id)
        .where(StockArticleSupplierRef.article_id == article.id)
        .order_by(StockArticleSupplierRef.preferred.desc(), StockSupplier.name)
    ).all()
    minimums = {
        item.location_id: item
        for item in db.scalars(
            select(StockMinimum).where(StockMinimum.article_id == article.id)
        ).all()
    }
    movements = db.scalars(
        select(StockMovement)
        .where(StockMovement.article_id == article.id)
        .order_by(StockMovement.occurred_at.desc(), StockMovement.id.desc())
        .limit(100)
    ).all()
    receipt_lines = db.execute(
        select(StockReceiptLine, StockReceipt, StockSupplier)
        .join(StockReceipt, StockReceipt.id == StockReceiptLine.receipt_id)
        .outerjoin(StockSupplier, StockSupplier.id == StockReceipt.supplier_id)
        .where(StockReceiptLine.article_id == article.id)
        .order_by(StockReceipt.confirmed_at.desc(), StockReceipt.id.desc())
        .limit(50)
    ).all()
    return templates.TemplateResponse(
        request,
        "clean_stock_article_detail.html",
        {
            **_page_context(request, db),
            "article": article,
            "row": row,
            "category": db.get(StockCategory, article.category_id) if article.category_id else None,
            "references": references,
            "locations": db.scalars(select(StockLocation).order_by(StockLocation.name)).all(),
            "minimums": minimums,
            "movements": movements,
            "receipt_lines": receipt_lines,
        },
    )


@stock_router.post("/v2-clean/stock/articles/{article_id}/minimums")
def stock_article_minimum(
    request: Request,
    article_id: int,
    db: DbSession,
    location_id: int = Form(...),
    minimum_quantity: str = Form(...),
):
    if denied := _denied(request, db, "stock.manage", "admin.manage"):
        return denied
    minimum = db.scalar(
        select(StockMinimum).where(
            StockMinimum.article_id == article_id,
            StockMinimum.location_id == location_id,
        )
    )
    if not minimum:
        minimum = StockMinimum(article_id=article_id, location_id=location_id)
        db.add(minimum)
    minimum.minimum_quantity = _parse_decimal(minimum_quantity)
    db.commit()
    return RedirectResponse(f"/v2-clean/stock/articles/{article_id}?saved=minimum", status_code=303)


@stock_router.get("/v2-clean/stock/suppliers", response_class=HTMLResponse)
def stock_suppliers(request: Request, db: DbSession, q: str = ""):
    if denied := _denied(
        request, db, "stock.read", "stock.operate", "stock.manage", "admin.manage"
    ):
        return denied
    statement = select(StockSupplier).order_by(StockSupplier.name)
    if q.strip():
        token = f"%{q.strip()}%"
        statement = statement.where(
            or_(StockSupplier.name.ilike(token), StockSupplier.tax_id.ilike(token))
        )
    suppliers = db.scalars(statement).all()
    rows = []
    for supplier in suppliers:
        rows.append(
            {
                "supplier": supplier,
                "references": int(
                    db.scalar(
                        select(func.count())
                        .select_from(StockArticleSupplierRef)
                        .where(StockArticleSupplierRef.supplier_id == supplier.id)
                    )
                    or 0
                ),
                "invoices": int(
                    db.scalar(
                        select(func.count())
                        .select_from(StockInvoiceImport)
                        .where(StockInvoiceImport.supplier_id == supplier.id)
                    )
                    or 0
                ),
            }
        )
    return templates.TemplateResponse(
        request,
        "clean_stock_suppliers.html",
        {**_page_context(request, db), "rows": rows, "q": q},
    )


@stock_router.post("/v2-clean/stock/suppliers")
def stock_supplier_create(
    request: Request,
    db: DbSession,
    name: str = Form(...),
    tax_id: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    address: str = Form(""),
    payment_terms: str = Form(""),
):
    if denied := _denied(request, db, "stock.manage", "admin.manage"):
        return denied
    clean_tax_id = tax_id.strip() or None
    if clean_tax_id and db.scalar(
        select(StockSupplier).where(StockSupplier.tax_id == clean_tax_id)
    ):
        return RedirectResponse("/v2-clean/stock/suppliers?error=duplicate_tax_id", status_code=303)
    supplier = StockSupplier(
        name=name.strip(),
        tax_id=clean_tax_id,
        email=email.strip() or None,
        phone=phone.strip() or None,
        address=address.strip() or None,
        payment_terms=payment_terms.strip() or None,
    )
    db.add(supplier)
    db.commit()
    return RedirectResponse(f"/v2-clean/stock/suppliers/{supplier.id}?saved=1", status_code=303)


@stock_router.get("/v2-clean/stock/suppliers/{supplier_id}", response_class=HTMLResponse)
def stock_supplier_detail(request: Request, supplier_id: int, db: DbSession):
    if denied := _denied(
        request, db, "stock.read", "stock.operate", "stock.manage", "admin.manage"
    ):
        return denied
    supplier = db.get(StockSupplier, supplier_id)
    if not supplier:
        return RedirectResponse("/v2-clean/stock/suppliers?error=missing", status_code=303)
    references = db.execute(
        select(StockArticleSupplierRef, StockArticle)
        .join(StockArticle, StockArticle.id == StockArticleSupplierRef.article_id)
        .where(StockArticleSupplierRef.supplier_id == supplier.id)
        .order_by(StockArticle.name)
    ).all()
    imports = db.scalars(
        select(StockInvoiceImport)
        .where(StockInvoiceImport.supplier_id == supplier.id)
        .order_by(StockInvoiceImport.invoice_date.desc().nullslast(), StockInvoiceImport.id.desc())
    ).all()
    return templates.TemplateResponse(
        request,
        "clean_stock_supplier_detail.html",
        {
            **_page_context(request, db),
            "supplier": supplier,
            "references": references,
            "imports": imports,
        },
    )


@stock_router.get("/v2-clean/stock/invoices", response_class=HTMLResponse)
def stock_invoices(request: Request, db: DbSession, q: str = "", status_filter: str = ""):
    if denied := _denied(
        request, db, "stock.read", "stock.operate", "stock.manage", "admin.manage"
    ):
        return denied
    statement = (
        select(StockInvoiceImport, Document, StockSupplier)
        .join(Document, Document.id == StockInvoiceImport.document_id)
        .outerjoin(StockSupplier, StockSupplier.id == StockInvoiceImport.supplier_id)
        .order_by(StockInvoiceImport.created_at.desc(), StockInvoiceImport.id.desc())
    )
    if status_filter:
        statement = statement.where(StockInvoiceImport.status == status_filter)
    if q.strip():
        token = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                StockInvoiceImport.invoice_number.ilike(token),
                StockSupplier.name.ilike(token),
                Document.title.ilike(token),
            )
        )
    rows = []
    for invoice_import, document, supplier in db.execute(statement).all():
        linked_receipts = int(
            db.scalar(
                select(func.count())
                .select_from(StockReceiptInvoiceLink)
                .where(StockReceiptInvoiceLink.invoice_import_id == invoice_import.id)
            )
            or 0
        )
        rows.append(
            {
                "invoice_import": invoice_import,
                "document": document,
                "supplier": supplier,
                "linked_receipts": linked_receipts,
            }
        )
    return templates.TemplateResponse(
        request,
        "clean_stock_invoices.html",
        {**_page_context(request, db), "rows": rows, "q": q, "status_filter": status_filter},
    )


async def _import_stock_invoice_file(
    db: DbSession, *, file: UploadFile, user_id: int | None
) -> tuple[str, int | None, str]:
    original_name = Path(file.filename or "fatura_stock.pdf").name
    if Path(original_name).suffix.lower() != ".pdf":
        return "failed", None, f"{original_name}: o ficheiro não é PDF."
    content = await file.read()
    if not content:
        return "failed", None, f"{original_name}: o ficheiro está vazio."
    if len(content) > 25 * 1024 * 1024:
        return "failed", None, f"{original_name}: o PDF excede 25 MB."
    digest = hashlib.sha256(content).hexdigest()
    existing = db.scalar(
        select(StockInvoiceImport)
        .join(Document, Document.id == StockInvoiceImport.document_id)
        .where(Document.file_hash == digest)
    )
    if existing:
        return "duplicate", existing.id, f"{original_name}: já estava importado."

    folder_path = f"Stock/Faturas/{date.today().year}"
    storage_dir = document_archive_root().joinpath("Stock", "Faturas", str(date.today().year))
    stem = sanitize_archive_component(Path(original_name).stem, "fatura_stock")
    stored_name = f"{stem}_{digest[:12]}.pdf"
    stored_path = storage_dir / stored_name
    try:
        storage_dir.mkdir(parents=True, exist_ok=True)
        stored_path.write_bytes(content)
    except OSError:
        logger.exception("Failed to persist direct stock invoice upload")
        return (
            "failed",
            None,
            f"{original_name}: não foi possível guardar no arquivo documental.",
        )
    document = Document(
        title=Path(original_name).stem[:200],
        document_type="workshop_supplier_invoice",
        classification="invoice",
        source="stock_direct_import",
        entry_channel="stock_invoice_import",
        source_subject="Importação direta em Stock",
        original_name=original_name[:255],
        file_name=stored_name[:255],
        file_type="pdf",
        file_size=len(content),
        storage_provider="local",
        storage_path=str(stored_path),
        storage_key=digest,
        folder_path=folder_path,
        status="received",
        file_hash=digest,
        uploaded_by_id=user_id,
    )
    try:
        db.add(document)
        db.flush()
        classify_invoice_nature(
            db,
            document=document,
            nature="stock",
            user_id=user_id,
            suggested_nature="stock",
            suggestion_confidence=1.0,
            decision_reason="Importação iniciada no módulo Stock",
        )
        invoice_import = ensure_invoice_import(db, document=document, user_id=user_id)
        db.add(
            DocumentEvent(
                document_id=document.id,
                action="stock.invoice.direct_imported",
                old_value=None,
                new_value=f"stock_invoice_import:{invoice_import.id}",
                user_id=user_id,
            )
        )
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        stored_path.unlink(missing_ok=True)
        logger.exception("Failed to register direct stock invoice upload")
        error_name = type(exc.orig).__name__ if getattr(exc, "orig", None) else type(exc).__name__
        return (
            "failed",
            None,
            f"{original_name}: não foi possível registar ({error_name}).",
        )

    # OCR is deliberately isolated from document ingestion. A parser or database
    # failure during extraction must never roll back the received invoice.
    try:
        invoice_import = db.get(StockInvoiceImport, invoice_import.id)
        extract_stock_invoice(db, invoice_import)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Automatic extraction failed for stock invoice %s", original_name)
        invoice_import = db.get(StockInvoiceImport, invoice_import.id)
        if invoice_import:
            invoice_import.status = "needs_review"
            invoice_import.error_details = (
                "Extração automática indisponível. O documento ficou disponível para revisão "
                f"manual ({type(exc).__name__})."
            )
            db.commit()
    return "imported", invoice_import.id, f"{original_name}: importado."


@stock_router.post("/v2-clean/stock/invoices/import")
async def stock_invoice_direct_import(
    request: Request,
    db: DbSession,
    files: list[UploadFile] = File(..., alias="file"),
):
    if denied := _denied(request, db, "stock.operate", "stock.manage", "admin.manage"):
        return denied
    if not files:
        return RedirectResponse(
            "/v2-clean/stock/invoices?" + urlencode({"error": "Seleciona pelo menos um PDF."}),
            status_code=303,
        )
    counts = {"imported": 0, "duplicate": 0, "failed": 0}
    messages: list[str] = []
    last_import_id: int | None = None
    for file in files[:100]:
        status, import_id, message = await _import_stock_invoice_file(
            db, file=file, user_id=_user_id(request)
        )
        counts[status] += 1
        messages.append(message)
        if status == "imported":
            last_import_id = import_id
    if len(files) == 1 and counts["failed"]:
        return RedirectResponse(
            "/v2-clean/stock/invoices?" + urlencode({"error": messages[0]}), status_code=303
        )
    notice = {
        "batch_imported": counts["imported"],
        "batch_duplicates": counts["duplicate"],
        "batch_failed": counts["failed"],
    }
    if messages and counts["failed"]:
        notice["batch_errors"] = " | ".join(messages)[:1000]
    if len(files) == 1 and last_import_id and not counts["failed"]:
        return RedirectResponse(
            f"/v2-clean/stock/invoices/{last_import_id}?imported=1", status_code=303
        )
    return RedirectResponse(f"/v2-clean/stock/invoices?{urlencode(notice)}", status_code=303)


@stock_router.get("/v2-clean/stock/invoices/{invoice_import_id}", response_class=HTMLResponse)
def stock_invoice_review(request: Request, invoice_import_id: int, db: DbSession):
    if denied := _denied(
        request, db, "stock.read", "stock.operate", "stock.manage", "admin.manage"
    ):
        return denied
    invoice_import = db.get(StockInvoiceImport, invoice_import_id)
    if not invoice_import:
        return RedirectResponse("/v2-clean/stock/invoices?error=missing", status_code=303)
    document = db.get(Document, invoice_import.document_id)
    saved_lines = db.scalars(
        select(StockInvoiceLine)
        .where(StockInvoiceLine.invoice_import_id == invoice_import.id)
        .order_by(StockInvoiceLine.line_number)
    ).all()
    raw = (
        invoice_import.raw_extraction_json
        if isinstance(invoice_import.raw_extraction_json, dict)
        else {}
    )
    line_rows = saved_lines or raw.get("lines", [])
    linked_receipts = db.execute(
        select(StockReceipt, StockLocation)
        .join(StockReceiptInvoiceLink, StockReceiptInvoiceLink.receipt_id == StockReceipt.id)
        .join(StockLocation, StockLocation.id == StockReceipt.location_id)
        .where(StockReceiptInvoiceLink.invoice_import_id == invoice_import.id)
        .order_by(StockReceipt.confirmed_at.desc(), StockReceipt.id.desc())
    ).all()
    articles = db.scalars(
        select(StockArticle)
        .where(StockArticle.active.is_(True))
        .order_by(StockArticle.internal_ref, StockArticle.name)
    ).all()
    supplier_article_matches: dict[str, int] = {}
    if invoice_import.supplier_id:
        supplier_article_matches = {
            reference.supplier_ref: reference.article_id
            for reference in db.scalars(
                select(StockArticleSupplierRef).where(
                    StockArticleSupplierRef.supplier_id == invoice_import.supplier_id
                )
            ).all()
        }
    return templates.TemplateResponse(
        request,
        "clean_stock_invoice_review.html",
        {
            **_page_context(request, db),
            "invoice_import": invoice_import,
            "document": document,
            "supplier": db.get(StockSupplier, invoice_import.supplier_id)
            if invoice_import.supplier_id
            else None,
            "suppliers": db.scalars(
                select(StockSupplier)
                .where(StockSupplier.active.is_(True))
                .order_by(StockSupplier.name)
            ).all(),
            "line_rows": line_rows,
            "raw": raw,
            "linked_receipts": linked_receipts,
            "articles": articles,
            "locations": db.scalars(
                select(StockLocation)
                .where(StockLocation.active.is_(True))
                .order_by(StockLocation.name)
            ).all(),
            "supplier_article_matches": supplier_article_matches,
        },
    )


@stock_router.post("/v2-clean/stock/invoices/{invoice_import_id}/extract")
def stock_invoice_extract(request: Request, invoice_import_id: int, db: DbSession):
    if denied := _denied(request, db, "stock.operate", "stock.manage", "admin.manage"):
        return denied
    invoice_import = db.get(StockInvoiceImport, invoice_import_id)
    if not invoice_import:
        return RedirectResponse("/v2-clean/stock/invoices?error=missing", status_code=303)
    try:
        extract_stock_invoice(db, invoice_import)
        db.commit()
        notice = (
            {"extracted": "1"}
            if invoice_import.extractor_name != "unsupported"
            else {"extraction_review": "1"}
        )
    except (StockDomainError, OSError) as exc:
        db.rollback()
        notice = {"error": str(exc)}
    except Exception as exc:
        db.rollback()
        logger.exception(
            "Manual extraction failed for stock invoice import %s",
            invoice_import_id,
        )
        invoice_import = db.get(StockInvoiceImport, invoice_import_id)
        if invoice_import:
            invoice_import.status = "needs_review"
            invoice_import.error_details = (
                "Extração automática indisponível. O documento ficou disponível para "
                f"revisão manual ({type(exc).__name__})."
            )
            try:
                db.commit()
            except Exception:
                db.rollback()
                logger.exception(
                    "Failed to persist extraction error for stock invoice import %s",
                    invoice_import_id,
                )
        notice = {"extraction_review": "1"}
    return RedirectResponse(
        f"/v2-clean/stock/invoices/{invoice_import_id}?{urlencode(notice)}", status_code=303
    )


@stock_router.post("/v2-clean/stock/invoices/{invoice_import_id}/validate")
async def stock_invoice_validate(request: Request, invoice_import_id: int, db: DbSession):
    if denied := _denied(request, db, "stock.operate", "stock.manage", "admin.manage"):
        return denied
    invoice_import = db.get(StockInvoiceImport, invoice_import_id)
    if not invoice_import:
        return RedirectResponse("/v2-clean/stock/invoices?error=missing", status_code=303)
    form = await request.form()
    try:
        line_numbers = form.getlist("line_number")
        lines = []
        for index, line_number in enumerate(line_numbers):

            def value(name: str, default: str = "", row_index: int = index) -> str:
                values = form.getlist(name)
                return str(values[row_index]) if row_index < len(values) else default

            lines.append(
                StockInvoiceLineReview(
                    line_number=int(line_number),
                    supplier_ref=value("supplier_ref") or None,
                    description=value("description"),
                    quantity=_parse_decimal(value("quantity")),
                    unit=value("unit", "un."),
                    unit_cost=_parse_decimal(value("unit_cost")),
                    discount=_parse_decimal(value("discount")),
                    eco_value=_parse_decimal(value("eco_value")),
                    tax_rate=_parse_decimal(value("tax_rate")),
                    line_total=_parse_decimal(value("line_total")) if value("line_total") else None,
                )
            )
        review = StockInvoiceReview(
            supplier_id=int(str(form.get("supplier_id")))
            if str(form.get("supplier_id") or "")
            else None,
            supplier_tax_id=str(form.get("supplier_tax_id") or "") or None,
            supplier_name=str(form.get("supplier_name") or ""),
            supplier_email=str(form.get("supplier_email") or "") or None,
            supplier_phone=str(form.get("supplier_phone") or "") or None,
            supplier_address=str(form.get("supplier_address") or "") or None,
            payment_terms=str(form.get("payment_terms") or "") or None,
            invoice_number=str(form.get("invoice_number") or ""),
            invoice_date=_parse_date(str(form.get("invoice_date") or "")),
            due_date=_parse_date(str(form.get("due_date") or "")),
            net_total=_parse_decimal(str(form.get("net_total"))) if form.get("net_total") else None,
            tax_total=_parse_decimal(str(form.get("tax_total"))) if form.get("tax_total") else None,
            gross_total=_parse_decimal(str(form.get("gross_total")))
            if form.get("gross_total")
            else None,
            content_hash=str(form.get("content_hash") or "") or None,
            lines=lines,
        )
        review_and_validate_invoice(
            db, invoice_import=invoice_import, review=review, user_id=_user_id(request)
        )
        db.commit()
        notice = {"validated": "1"}
    except (ValueError, StockDomainError) as exc:
        db.commit()
        notice = {"error": str(exc)}
    return RedirectResponse(
        f"/v2-clean/stock/invoices/{invoice_import_id}?{urlencode(notice)}", status_code=303
    )


@stock_router.post("/v2-clean/stock/invoices/{invoice_import_id}/receive")
async def stock_invoice_receive(request: Request, invoice_import_id: int, db: DbSession):
    if denied := _denied(request, db, "stock.operate", "stock.manage", "admin.manage"):
        return denied
    invoice_import = db.get(StockInvoiceImport, invoice_import_id)
    if not invoice_import:
        return RedirectResponse("/v2-clean/stock/invoices?error=missing", status_code=303)
    if invoice_import.status != "validated":
        return RedirectResponse(
            f"/v2-clean/stock/invoices/{invoice_import_id}?error=Valida primeiro a conferência documental.",
            status_code=303,
        )
    form = await request.form()
    try:
        invoice_lines = {
            line.id: line
            for line in db.scalars(
                select(StockInvoiceLine).where(
                    StockInvoiceLine.invoice_import_id == invoice_import.id
                )
            ).all()
        }
        article_ids = form.getlist("article_id")
        invoice_line_ids = form.getlist("invoice_line_id")
        internal_refs = form.getlist("internal_ref")
        article_names = form.getlist("article_name")
        classifications = form.getlist("classification")
        quantities = form.getlist("accepted_quantity")
        divergences = form.getlist("divergence_reason")
        receipt_items: dict[int, dict] = {}
        for index, invoice_line_id_value in enumerate(invoice_line_ids):
            invoice_line = invoice_lines.get(int(str(invoice_line_id_value)))
            if not invoice_line:
                raise StockDomainError("Linha documental inválida para esta fatura.")
            accepted_quantity = _parse_decimal(
                str(quantities[index] if index < len(quantities) else "0")
            )
            if accepted_quantity <= ZERO:
                continue
            selected_article_id = str(
                article_ids[index] if index < len(article_ids) else ""
            ).strip()
            article = db.get(StockArticle, int(selected_article_id)) if selected_article_id else None
            if not article:
                internal_ref = str(
                    internal_refs[index] if index < len(internal_refs) else ""
                ).strip()
                article_name = str(
                    article_names[index] if index < len(article_names) else ""
                ).strip()
                if not internal_ref or not article_name:
                    raise StockDomainError(
                        f"Linha {invoice_line.line_number}: seleciona um artigo ou indica referência e nome para o criar."
                    )
                article = db.scalar(
                    select(StockArticle).where(StockArticle.internal_ref == internal_ref)
                )
                if not article:
                    article = StockArticle(
                        internal_ref=internal_ref,
                        name=article_name,
                        description=invoice_line.description,
                        unit=invoice_line.unit,
                        classification=str(
                            classifications[index] if index < len(classifications) else ""
                        ).strip()
                        or None,
                        primary_supplier_id=invoice_import.supplier_id,
                    )
                    db.add(article)
                    db.flush()
            invoice_line.article_id = article.id
            divergence = str(
                divergences[index] if index < len(divergences) else ""
            ).strip() or None
            current = receipt_items.get(article.id)
            if current:
                current["accepted_quantity"] += accepted_quantity
                if divergence:
                    current["divergence_reason"] = "; ".join(
                        filter(None, [current.get("divergence_reason"), divergence])
                    )
            else:
                receipt_items[article.id] = {
                    "article_id": article.id,
                    "supplier_ref": invoice_line.supplier_ref,
                    "accepted_quantity": accepted_quantity,
                    "unit_cost": invoice_line.unit_cost,
                    "divergence_reason": divergence,
                }
        if not receipt_items:
            raise StockDomainError("Indica pelo menos uma quantidade fisicamente recebida.")
        source_type = str(form.get("source_type") or "invoice")
        source_reference = str(form.get("source_reference") or "").strip() or None
        if source_type == "invoice" and not source_reference:
            source_reference = invoice_import.invoice_number
        command = StockReceiptCreate(
            location_id=int(str(form.get("location_id"))),
            supplier_id=invoice_import.supplier_id,
            source_type=source_type,
            source_reference=source_reference,
            responsible_name=str(form.get("responsible_name") or "") or None,
            notes=str(form.get("notes") or "") or None,
            invoice_import_ids=[invoice_import.id],
            lines=[StockReceiptLineCreate(**item) for item in receipt_items.values()],
        )
        receipt = create_physical_receipt(db, command=command, user_id=_user_id(request))
        db.commit()
        notice = {"received": str(receipt.id)}
    except (ValueError, StockDomainError) as exc:
        db.rollback()
        notice = {"error": str(exc)}
    return RedirectResponse(
        f"/v2-clean/stock/invoices/{invoice_import_id}?{urlencode(notice)}", status_code=303
    )


@stock_router.get("/v2-clean/stock/receipts", response_class=HTMLResponse)
def stock_receipts(request: Request, db: DbSession):
    if denied := _denied(
        request, db, "stock.read", "stock.operate", "stock.manage", "admin.manage"
    ):
        return denied
    receipt_rows = db.execute(
        select(StockReceipt, StockLocation, StockSupplier)
        .join(StockLocation, StockLocation.id == StockReceipt.location_id)
        .outerjoin(StockSupplier, StockSupplier.id == StockReceipt.supplier_id)
        .order_by(StockReceipt.confirmed_at.desc(), StockReceipt.id.desc())
        .limit(200)
    ).all()
    linked_counts = {
        receipt_id: count
        for receipt_id, count in db.execute(
            select(
                StockReceiptInvoiceLink.receipt_id,
                func.count(StockReceiptInvoiceLink.id),
            ).group_by(StockReceiptInvoiceLink.receipt_id)
        ).all()
    }
    return templates.TemplateResponse(
        request,
        "clean_stock_receipts.html",
        {
            **_page_context(request, db),
            "receipt_rows": receipt_rows,
            "linked_counts": linked_counts,
            "articles": db.scalars(
                select(StockArticle)
                .where(StockArticle.active.is_(True))
                .order_by(StockArticle.name)
            ).all(),
            "locations": db.scalars(
                select(StockLocation)
                .where(StockLocation.active.is_(True))
                .order_by(StockLocation.name)
            ).all(),
            "suppliers": db.scalars(
                select(StockSupplier)
                .where(StockSupplier.active.is_(True))
                .order_by(StockSupplier.name)
            ).all(),
            "invoices": db.execute(
                select(StockInvoiceImport, Document)
                .join(Document, Document.id == StockInvoiceImport.document_id)
                .order_by(StockInvoiceImport.invoice_date.desc().nullslast())
                .limit(100)
            ).all(),
        },
    )


@stock_router.post("/v2-clean/stock/receipts")
async def stock_receipt_create(request: Request, db: DbSession):
    if denied := _denied(request, db, "stock.operate", "stock.manage", "admin.manage"):
        return denied
    form = await request.form()
    try:
        article_ids = form.getlist("article_id")
        quantities = form.getlist("accepted_quantity")
        costs = form.getlist("unit_cost")
        supplier_refs = form.getlist("supplier_ref")
        lots = form.getlist("lot")
        divergences = form.getlist("divergence_reason")
        lines = []
        for index, article_id in enumerate(article_ids):
            if not article_id:
                continue
            lines.append(
                StockReceiptLineCreate(
                    article_id=int(article_id),
                    supplier_ref=str(supplier_refs[index])
                    if index < len(supplier_refs) and supplier_refs[index]
                    else None,
                    accepted_quantity=_parse_decimal(
                        str(quantities[index] if index < len(quantities) else "0")
                    ),
                    unit_cost=_parse_decimal(str(costs[index]))
                    if index < len(costs) and costs[index]
                    else None,
                    lot=str(lots[index]) if index < len(lots) and lots[index] else None,
                    divergence_reason=str(divergences[index])
                    if index < len(divergences) and divergences[index]
                    else None,
                )
            )
        command = StockReceiptCreate(
            location_id=int(str(form.get("location_id"))),
            supplier_id=int(str(form.get("supplier_id"))) if form.get("supplier_id") else None,
            source_type=str(form.get("source_type") or "manual"),
            source_reference=str(form.get("source_reference") or "") or None,
            responsible_name=str(form.get("responsible_name") or "") or None,
            notes=str(form.get("notes") or "") or None,
            invoice_import_ids=[int(value) for value in form.getlist("invoice_import_ids")],
            lines=lines,
        )
        receipt = create_physical_receipt(db, command=command, user_id=_user_id(request))
        db.commit()
        notice = {"received": str(receipt.id)}
    except (ValueError, StockDomainError) as exc:
        db.rollback()
        notice = {"error": str(exc)}
    return RedirectResponse(f"/v2-clean/stock/receipts?{urlencode(notice)}", status_code=303)


@stock_router.get("/v2-clean/stock/movements", response_class=HTMLResponse)
def stock_movements(request: Request, db: DbSession, movement_type: str = "", q: str = ""):
    if denied := _denied(
        request, db, "stock.read", "stock.operate", "stock.manage", "admin.manage"
    ):
        return denied
    statement = (
        select(StockMovement, StockArticle)
        .join(StockArticle, StockArticle.id == StockMovement.article_id)
        .order_by(StockMovement.occurred_at.desc(), StockMovement.id.desc())
        .limit(500)
    )
    if movement_type:
        statement = statement.where(StockMovement.movement_type == movement_type)
    if q.strip():
        token = f"%{q.strip()}%"
        statement = statement.where(
            or_(StockArticle.internal_ref.ilike(token), StockArticle.name.ilike(token))
        )
    return templates.TemplateResponse(
        request,
        "clean_stock_movements.html",
        {
            **_page_context(request, db),
            "rows": db.execute(statement).all(),
            "articles": db.scalars(
                select(StockArticle)
                .where(StockArticle.active.is_(True))
                .order_by(StockArticle.name)
            ).all(),
            "locations": db.scalars(
                select(StockLocation)
                .where(StockLocation.active.is_(True))
                .order_by(StockLocation.name)
            ).all(),
            "movement_type": movement_type,
            "q": q,
        },
    )


@stock_router.get("/v2-clean/stock/current", response_class=HTMLResponse)
def stock_current(request: Request, db: DbSession, q: str = "", location_id: int | None = None):
    if denied := _denied(
        request, db, "stock.read", "stock.operate", "stock.manage", "admin.manage"
    ):
        return denied
    statement = select(StockArticle).where(StockArticle.active.is_(True))
    if q.strip():
        token = f"%{q.strip()}%"
        statement = statement.where(
            or_(StockArticle.internal_ref.ilike(token), StockArticle.name.ilike(token))
        )
    articles = db.scalars(statement.order_by(StockArticle.internal_ref)).all()
    locations = db.scalars(
        select(StockLocation).where(StockLocation.active.is_(True)).order_by(StockLocation.name)
    ).all()
    if location_id:
        locations = [location for location in locations if location.id == location_id]
    balances = stock_balances(db, article_ids=[article.id for article in articles])
    minimums = {
        (minimum.article_id, minimum.location_id): minimum.minimum_quantity
        for minimum in db.scalars(select(StockMinimum)).all()
    }
    rows = [
        {
            "article": article,
            "location": location,
            "quantity": balances.get((article.id, location.id), ZERO),
            "minimum": minimums.get((article.id, location.id)),
        }
        for article in articles
        for location in locations
    ]
    return templates.TemplateResponse(
        request,
        "clean_stock_current.html",
        {
            **_page_context(request, db),
            "rows": rows,
            "locations": db.scalars(
                select(StockLocation).where(StockLocation.active.is_(True)).order_by(StockLocation.name)
            ).all(),
            "q": q,
            "location_id": location_id,
        },
    )


@stock_router.post("/v2-clean/stock/current/count")
def stock_current_count(
    request: Request,
    db: DbSession,
    article_id: int = Form(...),
    location_id: int = Form(...),
    counted_quantity: str = Form(...),
    reason: str = Form(...),
):
    if denied := _denied(request, db, "stock.manage", "admin.manage"):
        return denied
    try:
        current = stock_balances(db, article_ids=[article_id]).get((article_id, location_id), ZERO)
        counted = _parse_decimal(counted_quantity)
        difference = counted - current
        if difference == ZERO:
            notice = {"confirmed": "unchanged"}
        else:
            movement = create_manual_movement(
                db,
                command=StockMovementCreate(
                    article_id=article_id,
                    movement_type="adjustment",
                    quantity=difference,
                    to_location_id=location_id,
                    reason=f"Contagem física: {reason.strip()}",
                    external_reference_type="stock_count",
                ),
                user_id=_user_id(request),
            )
            db.commit()
            notice = {"confirmed": movement.id}
    except (ValueError, StockDomainError) as exc:
        db.rollback()
        notice = {"error": str(exc)}
    return RedirectResponse(f"/v2-clean/stock/current?{urlencode(notice)}", status_code=303)


@stock_router.post("/v2-clean/stock/movements")
def stock_movement_create(
    request: Request,
    db: DbSession,
    article_id: int = Form(...),
    movement_type: str = Form(...),
    quantity: str = Form(...),
    unit_cost: str = Form(""),
    from_location_id: int | None = Form(None),
    to_location_id: int | None = Form(None),
    reason: str = Form(...),
):
    required = (
        ("stock.manage", "admin.manage")
        if movement_type == "adjustment"
        else ("stock.operate", "stock.manage", "admin.manage")
    )
    if denied := _denied(request, db, *required):
        return denied
    try:
        command = StockMovementCreate(
            article_id=article_id,
            movement_type=movement_type,
            quantity=_parse_decimal(quantity),
            unit_cost=_parse_decimal(unit_cost) if unit_cost.strip() else None,
            from_location_id=from_location_id,
            to_location_id=to_location_id,
            reason=reason,
        )
        movement = create_manual_movement(db, command=command, user_id=_user_id(request))
        db.commit()
        notice = {"created": str(movement.id)}
    except (ValueError, StockDomainError) as exc:
        db.rollback()
        notice = {"error": str(exc)}
    return RedirectResponse(f"/v2-clean/stock/movements?{urlencode(notice)}", status_code=303)
