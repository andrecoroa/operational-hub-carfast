from __future__ import annotations

from datetime import date
from decimal import Decimal
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, or_, select

from app.api.deps import DbSession
from app.models.admin import User
from app.models.documents import Document
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
    StockReceiptLine,
    StockSupplier,
)
from app.schemas.stock import (
    StockInvoiceLineReview,
    StockInvoiceReview,
    StockMovementCreate,
    StockReceiptConfirm,
    StockReceiptLineConfirm,
)
from app.services.authorization import get_user_permission_codes
from app.services.stock import (
    StockDomainError,
    confirm_receipt,
    create_manual_movement,
    extract_stock_invoice,
    low_stock_rows,
    review_and_validate_invoice,
    stock_balances,
)
from app.web.router import templates

stock_router = APIRouter()
ZERO = Decimal("0")


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
    pending_receipts = int(
        db.scalar(
            select(func.count())
            .select_from(StockReceipt)
            .where(StockReceipt.status.in_({"pending", "partial"}))
        )
        or 0
    )
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
                "pending_receipts": pending_receipts,
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
    invoice_lines = db.execute(
        select(StockInvoiceLine, StockInvoiceImport, Document)
        .join(StockInvoiceImport, StockInvoiceImport.id == StockInvoiceLine.invoice_import_id)
        .join(Document, Document.id == StockInvoiceImport.document_id)
        .where(StockInvoiceLine.article_id == article.id)
        .order_by(StockInvoiceImport.invoice_date.desc().nullslast(), StockInvoiceImport.id.desc())
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
            "invoice_lines": invoice_lines,
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
        receipts = db.scalars(
            select(StockReceipt).where(StockReceipt.invoice_import_id == invoice_import.id)
        ).all()
        rows.append(
            {
                "invoice_import": invoice_import,
                "document": document,
                "supplier": supplier,
                "receipt_status": (
                    "completed"
                    if receipts and all(item.status == "completed" for item in receipts)
                    else "partial"
                    if any(item.status == "partial" for item in receipts)
                    else "pending"
                ),
            }
        )
    return templates.TemplateResponse(
        request,
        "clean_stock_invoices.html",
        {**_page_context(request, db), "rows": rows, "q": q, "status_filter": status_filter},
    )


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
    received = {
        line_id: quantity or ZERO
        for line_id, quantity in db.execute(
            select(StockReceiptLine.invoice_line_id, func.sum(StockReceiptLine.received_quantity))
            .join(StockInvoiceLine, StockInvoiceLine.id == StockReceiptLine.invoice_line_id)
            .where(StockInvoiceLine.invoice_import_id == invoice_import.id)
            .group_by(StockReceiptLine.invoice_line_id)
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
            "articles": db.scalars(
                select(StockArticle)
                .where(StockArticle.active.is_(True))
                .order_by(StockArticle.name)
            ).all(),
            "categories": db.scalars(
                select(StockCategory)
                .where(StockCategory.active.is_(True))
                .order_by(StockCategory.name)
            ).all(),
            "locations": db.scalars(
                select(StockLocation)
                .where(StockLocation.active.is_(True))
                .order_by(StockLocation.name)
            ).all(),
            "line_rows": line_rows,
            "raw": raw,
            "received": received,
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
        notice = {"extracted": "1"}
    except (StockDomainError, OSError) as exc:
        db.rollback()
        notice = {"error": str(exc)}
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

            article_id = value("article_id")
            create_article = value("create_article") == "1"
            lines.append(
                StockInvoiceLineReview(
                    line_number=int(line_number),
                    article_id=int(article_id) if article_id else None,
                    create_article=create_article,
                    internal_ref=value("internal_ref") or None,
                    article_name=value("article_name") or None,
                    category_id=int(value("category_id")) if value("category_id") else None,
                    classification=value("classification") or None,
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
    form = await request.form()
    try:
        ids = form.getlist("invoice_line_id")
        quantities = form.getlist("received_quantity")
        costs = form.getlist("received_unit_cost")
        lots = form.getlist("lot")
        divergences = form.getlist("divergence_reason")
        lines = []
        for index, line_id in enumerate(ids):
            quantity = _parse_decimal(str(quantities[index] if index < len(quantities) else "0"))
            if quantity <= ZERO:
                continue
            lines.append(
                StockReceiptLineConfirm(
                    invoice_line_id=int(line_id),
                    received_quantity=quantity,
                    unit_cost=_parse_decimal(str(costs[index]))
                    if index < len(costs) and costs[index]
                    else None,
                    lot=str(lots[index]) if index < len(lots) and lots[index] else None,
                    divergence_reason=str(divergences[index])
                    if index < len(divergences) and divergences[index]
                    else None,
                )
            )
        confirmation = StockReceiptConfirm(
            location_id=int(str(form.get("location_id"))),
            responsible_name=str(form.get("responsible_name") or "") or None,
            notes=str(form.get("notes") or "") or None,
            lines=lines,
        )
        receipt = confirm_receipt(
            db,
            invoice_import=invoice_import,
            confirmation=confirmation,
            user_id=_user_id(request),
        )
        db.commit()
        notice = {"received": str(receipt.id)}
    except (ValueError, StockDomainError) as exc:
        db.rollback()
        notice = {"error": str(exc)}
    return RedirectResponse(
        f"/v2-clean/stock/invoices/{invoice_import_id}?{urlencode(notice)}", status_code=303
    )


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
