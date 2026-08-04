from __future__ import annotations

import hashlib
import logging
import mimetypes
from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import DbSession
from app.models.admin import User
from app.models.documents import Document, DocumentEvent
from app.models.stock import (
    StockArticle,
    StockArticleSupplierRef,
    StockArticleVehicleCompatibility,
    StockCategory,
    StockDiscrepancy,
    StockInventoryCount,
    StockInventorySession,
    StockInvoiceImport,
    StockInvoiceLine,
    StockLocation,
    StockMinimum,
    StockMovement,
    StockPurchaseOrder,
    StockPurchaseOrderLine,
    StockReceipt,
    StockReceiptInvoiceLink,
    StockReceiptLine,
    StockSupplier,
)
from app.schemas.stock import (
    StockArticleVehicleCompatibilityCreate,
    StockConferenceAction,
    StockDiscrepancyRegularize,
    StockInventoryConfirm,
    StockInventoryJustification,
    StockInventorySessionCreate,
    StockInvoiceLineReview,
    StockInvoiceReview,
    StockMovementCreate,
    StockPurchaseOrderCreate,
    StockPurchaseOrderLineCreate,
    StockReceiptCreate,
    StockReceiptLineCreate,
)
from app.services.authorization import get_user_permission_codes
from app.services.document_workflow import classify_invoice_nature
from app.services.stock import (
    StockDomainError,
    _authorized_document_path,
    apply_conference_action,
    conference_comparison,
    confirm_inventory_session,
    create_inventory_session,
    create_manual_movement,
    create_physical_receipt,
    create_purchase_order,
    create_vehicle_compatibility,
    ensure_invoice_import,
    extract_stock_invoice,
    low_stock_rows,
    regularize_discrepancy,
    review_and_validate_invoice,
    save_inventory_counts,
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
        "can_manage_orders": bool(permissions & {"stock.orders.manage", "admin.manage"}),
        "can_count_inventory": bool(
            permissions & {"stock.inventory.count", "stock.manage", "admin.manage"}
        ),
        "can_confirm_inventory": bool(
            permissions & {"stock.inventory.confirm", "stock.manage", "admin.manage"}
        ),
        "can_manage_compatibility": bool(
            permissions & {"stock.compatibility.manage", "stock.manage", "admin.manage"}
        ),
        "can_conference_stock": bool(
            permissions & {"stock.conference", "stock.manage", "admin.manage"}
        ),
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
    low_rows = low_stock_rows(db)
    pending_orders = int(
        db.scalar(
            select(func.count())
            .select_from(StockPurchaseOrder)
            .where(StockPurchaseOrder.receiving_status.in_(("pending", "partial")))
        )
        or 0
    )
    pending_invoices = int(
        db.scalar(
            select(func.count())
            .select_from(StockInvoiceImport)
            .where(StockInvoiceImport.conference_status.in_(("pending", "divergent")))
        )
        or 0
    )
    open_inventories = int(
        db.scalar(
            select(func.count())
            .select_from(StockInventorySession)
            .where(StockInventorySession.status != "completed")
        )
        or 0
    )
    return templates.TemplateResponse(
        request,
        "clean_stock_dashboard.html",
        {
            **_page_context(request, db),
            "metrics": {
                "low": len(low_rows),
                "pending_orders": pending_orders,
                "pending_invoices": pending_invoices,
                "open_inventories": open_inventories,
            },
            "low_rows": low_rows[:8],
        },
    )


@stock_router.get("/v2-clean/stock/articles", response_class=HTMLResponse)
def stock_articles(
    request: Request,
    db: DbSession,
    q: str = "",
    category_id: str = "",
    supplier_id: str = "",
    location_id: str = "",
    state: str = "active",
    low_stock: bool = False,
):
    if denied := _denied(
        request, db, "stock.read", "stock.operate", "stock.manage", "admin.manage"
    ):
        return denied
    clean_category_id = int(category_id) if category_id.strip().isdigit() else None
    clean_supplier_id = int(supplier_id) if supplier_id.strip().isdigit() else None
    clean_location_id = int(location_id) if location_id.strip().isdigit() else None
    statement = select(StockArticle).order_by(StockArticle.name, StockArticle.id)
    if q.strip():
        token = f"%{q.strip()}%"
        statement = statement.where(
            or_(StockArticle.internal_ref.ilike(token), StockArticle.name.ilike(token))
        )
    if clean_category_id:
        statement = statement.where(StockArticle.category_id == clean_category_id)
    if clean_supplier_id:
        statement = statement.where(StockArticle.primary_supplier_id == clean_supplier_id)
    if state in {"active", "inactive"}:
        statement = statement.where(StockArticle.active.is_(state == "active"))
    rows = _article_rows(db, db.scalars(statement).all())
    if clean_location_id:
        location = db.get(StockLocation, clean_location_id)
        if location:
            rows = [row for row in rows if row["by_location"].get(location.code, ZERO) != ZERO]
            for row in rows:
                row["display_available"] = row["by_location"].get(location.code, ZERO)
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
                "category_id": clean_category_id,
                "supplier_id": clean_supplier_id,
                "location_id": clean_location_id,
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
    status: str = Form("active"),
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
        status=status if status in {"active", "inactive", "discontinued"} else "active",
        active=status == "active",
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
            "categories": db.scalars(select(StockCategory).order_by(StockCategory.name)).all(),
            "suppliers": db.scalars(select(StockSupplier).order_by(StockSupplier.name)).all(),
            "locations": db.scalars(select(StockLocation).order_by(StockLocation.name)).all(),
            "location_names": {
                item.id: item.name for item in db.scalars(select(StockLocation)).all()
            },
            "minimums": minimums,
            "movements": movements,
            "receipt_lines": receipt_lines,
            "compatibilities": db.scalars(
                select(StockArticleVehicleCompatibility)
                .where(StockArticleVehicleCompatibility.article_id == article.id)
                .order_by(
                    StockArticleVehicleCompatibility.created_at.desc(),
                    StockArticleVehicleCompatibility.id.desc(),
                )
            ).all(),
        },
    )


@stock_router.post("/v2-clean/stock/articles/{article_id}")
def stock_article_update(
    request: Request,
    article_id: int,
    db: DbSession,
    name: str = Form(...),
    description: str = Form(""),
    unit: str = Form("un."),
    category_id: int | None = Form(None),
    classification: str = Form(""),
    primary_supplier_id: int | None = Form(None),
    status: str = Form("active"),
):
    if denied := _denied(request, db, "stock.operate", "stock.manage", "admin.manage"):
        return denied
    article = db.get(StockArticle, article_id)
    if not article:
        return RedirectResponse("/v2-clean/stock/articles?error=missing", status_code=303)
    if status not in {"active", "inactive", "discontinued"}:
        return RedirectResponse(
            f"/v2-clean/stock/articles/{article_id}?error=invalid_status", status_code=303
        )
    article.name = name.strip()
    article.description = description.strip() or None
    article.unit = unit.strip() or "un."
    article.category_id = category_id
    article.classification = classification.strip() or None
    article.primary_supplier_id = primary_supplier_id
    article.status = status
    article.active = status == "active"
    db.commit()
    return RedirectResponse(f"/v2-clean/stock/articles/{article_id}?saved=article", status_code=303)


@stock_router.post("/v2-clean/stock/articles/{article_id}/compatibilities")
def stock_article_compatibility_create(
    request: Request,
    article_id: int,
    db: DbSession,
    brand: str = Form(...),
    model: str = Form(...),
    version: str = Form(""),
    engine: str = Form(""),
    generation_period: str = Form(""),
    status: str = Form("suggested"),
    evidence_type: str = Form("manual"),
    evidence_reference: str = Form(""),
    evidence_notes: str = Form(""),
):
    if denied := _denied(request, db, "stock.compatibility.manage", "stock.manage", "admin.manage"):
        return denied
    try:
        command = StockArticleVehicleCompatibilityCreate(
            article_id=article_id,
            brand=brand,
            model=model,
            version=version or None,
            engine=engine or None,
            generation_period=generation_period or None,
            status=status,
            evidence_type=evidence_type,
            evidence_reference=evidence_reference or None,
            evidence_notes=evidence_notes or None,
        )
        create_vehicle_compatibility(db, command=command, user_id=_user_id(request))
        db.commit()
        notice = {"saved": "compatibility"}
    except (ValueError, StockDomainError) as exc:
        db.rollback()
        notice = {"error": str(exc)}
    return RedirectResponse(
        f"/v2-clean/stock/articles/{article_id}?{urlencode(notice)}", status_code=303
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
def stock_invoices(
    request: Request,
    db: DbSession,
    q: str = "",
    status_filter: str = "pending",
    supplier_id: str = "",
    page: int = 1,
):
    if denied := _denied(
        request, db, "stock.read", "stock.operate", "stock.manage", "admin.manage"
    ):
        return denied
    statement = (
        select(StockInvoiceImport, Document, StockSupplier)
        .join(Document, Document.id == StockInvoiceImport.document_id)
        .outerjoin(StockSupplier, StockSupplier.id == StockInvoiceImport.supplier_id)
        .order_by(StockInvoiceImport.created_at.asc(), StockInvoiceImport.id.asc())
    )
    if status_filter in {"pending", "divergent", "conferred"}:
        statement = statement.where(StockInvoiceImport.conference_status == status_filter)
    elif status_filter not in {"", "all"}:
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
    clean_supplier_id = int(supplier_id) if supplier_id.strip().isdigit() else None
    if clean_supplier_id:
        statement = statement.where(StockInvoiceImport.supplier_id == clean_supplier_id)
    per_page = 5
    total = int(db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(max(page, 1), total_pages)
    statement = statement.limit(per_page).offset((page - 1) * per_page)
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
        {
            **_page_context(request, db),
            "rows": rows,
            "q": q,
            "status_filter": status_filter,
            "supplier_id": clean_supplier_id,
            "suppliers": db.scalars(
                select(StockSupplier)
                .where(StockSupplier.active.is_(True))
                .order_by(StockSupplier.name)
            ).all(),
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "previous_url": "/v2-clean/stock/invoices?"
            + urlencode({"q": q, "status_filter": status_filter, "supplier_id": supplier_id, "page": page - 1}),
            "next_url": "/v2-clean/stock/invoices?"
            + urlencode({"q": q, "status_filter": status_filter, "supplier_id": supplier_id, "page": page + 1}),
        },
    )


@stock_router.get("/v2-clean/stock/invoices/{invoice_import_id}/modal", response_class=HTMLResponse)
def stock_invoice_conference_modal(request: Request, invoice_import_id: int, db: DbSession):
    if denied := _denied(
        request, db, "stock.read", "stock.operate", "stock.manage", "admin.manage"
    ):
        return denied
    invoice_import = db.get(StockInvoiceImport, invoice_import_id)
    if not invoice_import:
        return HTMLResponse("Documento de Stock não encontrado.", status_code=404)
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
    raw_lines = raw.get("lines", [])
    extracted_lines = (
        saved_lines
        or [line for line in raw_lines if isinstance(line, dict)]
    )
    supplier = (
        db.get(StockSupplier, invoice_import.supplier_id)
        if invoice_import.supplier_id
        else None
    )
    display_invoice_date = invoice_import.invoice_date
    if not display_invoice_date and raw.get("invoice_date"):
        try:
            display_invoice_date = _parse_date(str(raw["invoice_date"]))
        except ValueError:
            display_invoice_date = None
    return templates.TemplateResponse(
        request,
        "_clean_stock_conference_modal.html",
        {
            **_page_context(request, db),
            "invoice_import": invoice_import,
            "document": document,
            "supplier": supplier,
            "display_supplier_name": supplier.name
            if supplier
            else str(raw.get("supplier_name") or "Fornecedor por confirmar"),
            "display_invoice_number": invoice_import.invoice_number
            or str(raw.get("invoice_number") or document.title or document.original_name),
            "display_invoice_date": display_invoice_date,
            "display_invoice_total": invoice_import.gross_total
            or _parse_decimal(str(raw.get("gross_total") or "0")),
            "comparison": conference_comparison(db, invoice_import),
            "extracted_lines": extracted_lines,
        },
    )


@stock_router.get("/v2-clean/stock/invoices/{invoice_import_id}/document")
def stock_invoice_document(request: Request, invoice_import_id: int, db: DbSession):
    if denied := _denied(
        request, db, "stock.read", "stock.operate", "stock.manage", "admin.manage"
    ):
        return denied
    invoice_import = db.get(StockInvoiceImport, invoice_import_id)
    document = db.get(Document, invoice_import.document_id) if invoice_import else None
    if not document:
        return HTMLResponse("Documento de Stock não encontrado.", status_code=404)
    try:
        path = _authorized_document_path(document)
    except StockDomainError as exc:
        return HTMLResponse(str(exc), status_code=404)
    original_name = Path(document.original_name or document.file_name or path.name).name
    media_type = mimetypes.guess_type(original_name)[0] or "application/pdf"
    response = FileResponse(path, media_type=media_type, filename=original_name)
    response.headers["Content-Disposition"] = (
        f'inline; filename="{original_name.replace(chr(34), "")}"'
    )
    return response


@stock_router.post("/v2-clean/stock/invoices/{invoice_import_id}/conference")
def stock_invoice_conference_action(
    request: Request,
    invoice_import_id: int,
    db: DbSession,
    action: str = Form(...),
    notes: str = Form(""),
    tolerance: str = Form("0.01"),
):
    if denied := _denied(request, db, "stock.conference", "stock.manage", "admin.manage"):
        return denied
    invoice_import = db.get(StockInvoiceImport, invoice_import_id)
    if not invoice_import:
        return RedirectResponse("/v2-clean/stock/invoices?error=missing", status_code=303)
    try:
        apply_conference_action(
            db,
            invoice_import=invoice_import,
            command=StockConferenceAction(
                action=action,
                notes=notes or None,
                tolerance=_parse_decimal(tolerance, "0.01"),
            ),
            user_id=_user_id(request),
        )
        db.commit()
        notice = {"conference_saved": invoice_import.conference_status}
    except (ValueError, StockDomainError) as exc:
        db.rollback()
        notice = {"error": str(exc)}
    return RedirectResponse(f"/v2-clean/stock/invoices?{urlencode(notice)}", status_code=303)


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
    files: list[UploadFile] = File(..., alias="file"),  # noqa: B008
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
            "receipt_responsible": db.get(User, _user_id(request)),
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
            f"/v2-clean/stock/invoices/{invoice_import_id}"
            "?error=Valida primeiro a conferência documental.",
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
            article = (
                db.get(StockArticle, int(selected_article_id)) if selected_article_id else None
            )
            if not article:
                internal_ref = str(
                    internal_refs[index] if index < len(internal_refs) else ""
                ).strip()
                article_name = str(
                    article_names[index] if index < len(article_names) else ""
                ).strip()
                if not internal_ref or not article_name:
                    raise StockDomainError(
                        f"Linha {invoice_line.line_number}: seleciona um artigo ou "
                        "indica referência e nome para o criar."
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
            divergence = str(divergences[index] if index < len(divergences) else "").strip() or None
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


@stock_router.get("/v2-clean/stock/orders", response_class=HTMLResponse)
def stock_orders(
    request: Request,
    db: DbSession,
    supplier_id: str = "",
    receiving_status: str = "",
):
    if denied := _denied(
        request, db, "stock.read", "stock.operate", "stock.manage", "admin.manage"
    ):
        return denied
    clean_supplier_id = int(supplier_id) if supplier_id.isdigit() else None
    statement = (
        select(StockPurchaseOrder, StockSupplier)
        .join(StockSupplier, StockSupplier.id == StockPurchaseOrder.supplier_id)
        .order_by(StockPurchaseOrder.effective_date.desc(), StockPurchaseOrder.id.desc())
    )
    if clean_supplier_id:
        statement = statement.where(StockPurchaseOrder.supplier_id == clean_supplier_id)
    if receiving_status in {"pending", "partial", "complete"}:
        statement = statement.where(StockPurchaseOrder.receiving_status == receiving_status)
    line_counts = {
        order_id: count
        for order_id, count in db.execute(
            select(
                StockPurchaseOrderLine.purchase_order_id,
                func.count(StockPurchaseOrderLine.id),
            ).group_by(StockPurchaseOrderLine.purchase_order_id)
        ).all()
    }
    return templates.TemplateResponse(
        request,
        "clean_stock_orders.html",
        {
            **_page_context(request, db),
            "rows": db.execute(statement).all(),
            "line_counts": line_counts,
            "suppliers": db.scalars(
                select(StockSupplier)
                .where(StockSupplier.active.is_(True))
                .order_by(StockSupplier.name)
            ).all(),
            "articles": db.scalars(
                select(StockArticle)
                .where(StockArticle.active.is_(True))
                .order_by(StockArticle.internal_ref)
            ).all(),
            "locations": db.scalars(
                select(StockLocation)
                .where(StockLocation.active.is_(True))
                .order_by(StockLocation.name)
            ).all(),
            "supplier_id": clean_supplier_id,
            "receiving_status": receiving_status,
        },
    )


@stock_router.post("/v2-clean/stock/orders")
async def stock_order_create(request: Request, db: DbSession):
    if denied := _denied(request, db, "stock.orders.manage", "stock.manage", "admin.manage"):
        return denied
    form = await request.form()
    try:
        article_ids = form.getlist("article_id")
        supplier_refs = form.getlist("supplier_ref")
        quantities = form.getlist("quantity")
        units = form.getlist("unit")
        prices = form.getlist("unit_price")
        location_ids = form.getlist("line_location_id")
        lines = []
        for index, raw_article_id in enumerate(article_ids):
            if not raw_article_id:
                continue
            lines.append(
                StockPurchaseOrderLineCreate(
                    article_id=int(raw_article_id),
                    supplier_ref=str(supplier_refs[index]).strip() or None,
                    quantity=_parse_decimal(str(quantities[index])),
                    unit=str(units[index]).strip() or "un.",
                    unit_price=_parse_decimal(str(prices[index])),
                    location_id=int(str(location_ids[index])),
                )
            )
        command = StockPurchaseOrderCreate(
            supplier_id=int(str(form.get("supplier_id"))),
            effective_date=_parse_date(str(form.get("effective_date") or "")) or date.today(),
            commercial_status=str(form.get("commercial_status") or "draft"),
            notes=str(form.get("notes") or "") or None,
            lines=lines,
        )
        order = create_purchase_order(db, command=command, user_id=_user_id(request))
        db.commit()
        notice = {"created": order.order_number}
    except (ValueError, IndexError, StockDomainError) as exc:
        db.rollback()
        notice = {"error": str(exc)}
    return RedirectResponse(f"/v2-clean/stock/orders?{urlencode(notice)}", status_code=303)


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
        .order_by(StockReceipt.effective_date.desc(), StockReceipt.id.desc())
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
    pending_invoice_rows = db.execute(
        select(StockInvoiceImport, StockSupplier)
        .join(StockSupplier, StockSupplier.id == StockInvoiceImport.supplier_id)
        .where(
            StockInvoiceImport.status == "validated",
            ~StockInvoiceImport.id.in_(
                select(StockReceiptInvoiceLink.invoice_import_id)
            ),
        )
        .order_by(
            StockInvoiceImport.invoice_date.asc().nullsfirst(),
            StockInvoiceImport.id.asc(),
        )
    ).all()
    return templates.TemplateResponse(
        request,
        "clean_stock_receipts.html",
        {
            **_page_context(request, db),
            "receipt_rows": receipt_rows,
            "pending_invoice_rows": pending_invoice_rows,
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
            "receipt_responsible": db.get(User, _user_id(request)),
            "completed_count": len(receipt_rows),
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
        order_line_ids = form.getlist("purchase_order_line_id")
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
                    purchase_order_line_id=int(str(order_line_ids[index]))
                    if index < len(order_line_ids) and order_line_ids[index]
                    else None,
                )
            )
        command = StockReceiptCreate(
            location_id=int(str(form.get("location_id"))),
            supplier_id=int(str(form.get("supplier_id"))) if form.get("supplier_id") else None,
            source_type=str(form.get("source_type") or "manual"),
            source_reference=str(form.get("source_reference") or "") or None,
            manual_reason=str(form.get("manual_reason") or "") or None,
            effective_date=_parse_date(str(form.get("effective_date") or "")) or date.today(),
            purchase_order_id=int(str(form.get("purchase_order_id")))
            if form.get("purchase_order_id")
            else None,
            delivery_document_id=int(str(form.get("delivery_document_id")))
            if form.get("delivery_document_id")
            else None,
            idempotency_key=str(form.get("idempotency_key") or "") or None,
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
        .order_by(StockMovement.effective_date.desc(), StockMovement.id.desc())
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
            "location_names": {
                item.id: item.name for item in db.scalars(select(StockLocation)).all()
            },
            "discrepancy_rows": db.execute(
                select(StockDiscrepancy, StockArticle, StockLocation)
                .join(StockArticle, StockArticle.id == StockDiscrepancy.article_id)
                .join(StockLocation, StockLocation.id == StockDiscrepancy.location_id)
                .where(StockDiscrepancy.status == "open")
                .order_by(StockDiscrepancy.created_at, StockDiscrepancy.id)
            ).all(),
        },
    )


@stock_router.get("/v2-clean/stock/current", response_class=HTMLResponse)
def stock_current(request: Request, db: DbSession, q: str = "", location_id: str = ""):
    query = {}
    if q.strip():
        query["q"] = q.strip()
    if location_id.strip().isdigit():
        query["location_id"] = location_id.strip()
    suffix = f"?{urlencode(query)}" if query else ""
    return RedirectResponse(f"/v2-clean/stock/articles{suffix}", status_code=302)


@stock_router.get("/v2-clean/stock/inventory", response_class=HTMLResponse)
def stock_inventory_sessions(request: Request, db: DbSession):
    if denied := _denied(
        request, db, "stock.read", "stock.operate", "stock.manage", "admin.manage"
    ):
        return denied
    rows = db.execute(
        select(StockInventorySession, StockLocation)
        .join(StockLocation, StockLocation.id == StockInventorySession.location_id)
        .order_by(StockInventorySession.created_at.desc(), StockInventorySession.id.desc())
    ).all()
    return templates.TemplateResponse(
        request,
        "clean_stock_inventory.html",
        {
            **_page_context(request, db),
            "rows": rows,
            "locations": db.scalars(
                select(StockLocation)
                .where(StockLocation.active.is_(True))
                .order_by(StockLocation.name)
            ).all(),
        },
    )


@stock_router.post("/v2-clean/stock/inventory")
def stock_inventory_start(
    request: Request,
    db: DbSession,
    location_id: int = Form(...),
    effective_date: str = Form(""),
    notes: str = Form(""),
    idempotency_key: str = Form(""),
):
    if denied := _denied(request, db, "stock.inventory.count", "stock.manage", "admin.manage"):
        return denied
    try:
        inventory = create_inventory_session(
            db,
            command=StockInventorySessionCreate(
                location_id=location_id,
                effective_date=_parse_date(effective_date) or date.today(),
                notes=notes or None,
                idempotency_key=idempotency_key or None,
            ),
            user_id=_user_id(request),
        )
        db.commit()
        return RedirectResponse(f"/v2-clean/stock/inventory/{inventory.id}", status_code=303)
    except (ValueError, StockDomainError) as exc:
        db.rollback()
        return RedirectResponse(
            f"/v2-clean/stock/inventory?{urlencode({'error': str(exc)})}", status_code=303
        )


@stock_router.get("/v2-clean/stock/inventory/{inventory_id}", response_class=HTMLResponse)
def stock_inventory_session_detail(request: Request, inventory_id: int, db: DbSession):
    if denied := _denied(
        request, db, "stock.read", "stock.operate", "stock.manage", "admin.manage"
    ):
        return denied
    inventory = db.get(StockInventorySession, inventory_id)
    if not inventory:
        return RedirectResponse("/v2-clean/stock/inventory?error=missing", status_code=303)
    db_rows = db.execute(
        select(StockInventoryCount, StockArticle)
        .join(StockArticle, StockArticle.id == StockInventoryCount.article_id)
        .where(StockInventoryCount.session_id == inventory.id)
        .order_by(StockArticle.internal_ref)
    ).all()
    reveal = inventory.status in {"review", "completed"}
    if reveal:
        rows = [
            {
                "article_id": article.id,
                "internal_ref": article.internal_ref,
                "name": article.name,
                "expected": count.expected_snapshot,
                "counted": count.counted_quantity,
                "difference": (count.counted_quantity or ZERO) - count.expected_snapshot,
                "justification": count.justification,
                "adjustment_movement_id": count.adjustment_movement_id,
            }
            for count, article in db_rows
        ]
    else:
        # Deliberately build a redacted structure: expected/minimum/status never reach HTML.
        rows = [
            {
                "article_id": article.id,
                "internal_ref": article.internal_ref,
                "name": article.name,
                "counted": count.counted_quantity,
            }
            for count, article in db_rows
        ]
    return templates.TemplateResponse(
        request,
        "clean_stock_inventory_session.html",
        {
            **_page_context(request, db),
            "inventory": inventory,
            "location": db.get(StockLocation, inventory.location_id),
            "rows": rows,
            "reveal": reveal,
        },
    )


@stock_router.post("/v2-clean/stock/inventory/{inventory_id}/counts")
async def stock_inventory_save(request: Request, inventory_id: int, db: DbSession):
    if denied := _denied(request, db, "stock.inventory.count", "stock.manage", "admin.manage"):
        return denied
    inventory = db.get(StockInventorySession, inventory_id)
    if not inventory:
        return RedirectResponse("/v2-clean/stock/inventory?error=missing", status_code=303)
    form = await request.form()
    try:
        article_ids = form.getlist("article_id")
        quantities = form.getlist("counted_quantity")
        counts = {
            int(str(article_id)): _parse_decimal(str(quantities[index]))
            for index, article_id in enumerate(article_ids)
            if article_id and index < len(quantities) and str(quantities[index]).strip()
        }
        save_inventory_counts(
            db,
            inventory=inventory,
            counts=counts,
            user_id=_user_id(request),
            close=str(form.get("action") or "save") == "close",
        )
        db.commit()
        notice = {"saved": inventory.status}
    except (ValueError, StockDomainError) as exc:
        db.rollback()
        notice = {"error": str(exc)}
    return RedirectResponse(
        f"/v2-clean/stock/inventory/{inventory_id}?{urlencode(notice)}", status_code=303
    )


@stock_router.post("/v2-clean/stock/inventory/{inventory_id}/confirm")
async def stock_inventory_confirm(request: Request, inventory_id: int, db: DbSession):
    if denied := _denied(request, db, "stock.inventory.confirm", "stock.manage", "admin.manage"):
        return denied
    inventory = db.get(StockInventorySession, inventory_id)
    if not inventory:
        return RedirectResponse("/v2-clean/stock/inventory?error=missing", status_code=303)
    form = await request.form()
    try:
        article_ids = form.getlist("article_id")
        justifications = form.getlist("justification")
        command = StockInventoryConfirm(
            confirmations=[
                StockInventoryJustification(
                    article_id=int(str(article_id)),
                    justification=str(justifications[index])
                    if index < len(justifications)
                    else None,
                )
                for index, article_id in enumerate(article_ids)
            ]
        )
        confirm_inventory_session(
            db, inventory=inventory, command=command, user_id=_user_id(request)
        )
        db.commit()
        notice = {"confirmed": "1"}
    except (ValueError, StockDomainError) as exc:
        db.rollback()
        notice = {"error": str(exc)}
    return RedirectResponse(
        f"/v2-clean/stock/inventory/{inventory_id}?{urlencode(notice)}", status_code=303
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
    if denied := _denied(request, db, "stock.inventory.count", "stock.manage", "admin.manage"):
        return denied
    return RedirectResponse(
        "/v2-clean/stock/inventory?error=use_blind_inventory_session", status_code=303
    )


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
    effective_date: str = Form(""),
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
            effective_date=_parse_date(effective_date) or date.today(),
        )
        movement = create_manual_movement(db, command=command, user_id=_user_id(request))
        db.commit()
        notice = {"created": str(movement.id)}
    except (ValueError, StockDomainError) as exc:
        db.rollback()
        notice = {"error": str(exc)}
    return RedirectResponse(f"/v2-clean/stock/movements?{urlencode(notice)}", status_code=303)


@stock_router.post("/v2-clean/stock/discrepancies/{discrepancy_id}/regularize")
def stock_discrepancy_regularize(
    request: Request,
    discrepancy_id: int,
    db: DbSession,
    adjustment_quantity: str = Form(...),
    reason: str = Form(...),
    effective_date: str = Form(""),
):
    if denied := _denied(request, db, "stock.inventory.confirm", "stock.manage", "admin.manage"):
        return denied
    discrepancy = db.get(StockDiscrepancy, discrepancy_id)
    if not discrepancy:
        return RedirectResponse("/v2-clean/stock/movements?error=missing", status_code=303)
    try:
        regularize_discrepancy(
            db,
            discrepancy=discrepancy,
            command=StockDiscrepancyRegularize(
                adjustment_quantity=_parse_decimal(adjustment_quantity),
                reason=reason,
                effective_date=_parse_date(effective_date) or date.today(),
            ),
            user_id=_user_id(request),
        )
        db.commit()
        notice = {"regularized": str(discrepancy.id)}
    except (ValueError, StockDomainError) as exc:
        db.rollback()
        notice = {"error": str(exc)}
    return RedirectResponse(f"/v2-clean/stock/movements?{urlencode(notice)}", status_code=303)
