from __future__ import annotations

import re
from collections import defaultdict

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession
from app.core.config import settings
from app.models.admin import User
from app.models.audit import AuditLog
from app.models.documents import Document, DocumentLink
from app.models.email import EmailTemplate
from app.models.stock import StockInvoiceImport
from app.models.suppliers import (
    SupplierAddress,
    SupplierContact,
    SupplierType,
    SupplierTypeAssignment,
)
from app.partners.compat import StockSupplier
from app.partners.facade import PartnersFacade
from app.services.audit import record_audit
from app.services.authorization import get_user_permission_codes
from app.web.router import templates

supplier_router = APIRouter(include_in_schema=False)
CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{1,79}$")
MODULE_CODES = {"stock", "workshop", "fleet", "finance", "documentation", "general"}


def _user_and_permissions(request: Request, db: DbSession) -> tuple[User | None, set[str]]:
    raw_user_id = request.session.get("user_id") if hasattr(request, "session") else None
    user = db.get(User, int(raw_user_id)) if raw_user_id else None
    return user, get_user_permission_codes(db, user) if user and user.active else set()


def _require(request: Request, db: DbSession, *codes: str) -> tuple[User, set[str]] | RedirectResponse:
    user, permissions = _user_and_permissions(request, db)
    if not user:
        return RedirectResponse("/login?next=/v2-clean/suppliers", status_code=303)
    if not permissions.intersection(codes):
        return RedirectResponse("/v2-clean?error=forbidden", status_code=303)
    return user, permissions


def _supplier_types(db: DbSession, supplier_id: int) -> list[SupplierType]:
    return list(
        db.scalars(
            select(SupplierType)
            .join(SupplierTypeAssignment, SupplierTypeAssignment.supplier_type_id == SupplierType.id)
            .where(SupplierTypeAssignment.supplier_id == supplier_id)
            .order_by(SupplierType.sort_order, SupplierType.name)
        )
    )


@supplier_router.get("/v2-clean/suppliers", response_class=HTMLResponse)
def supplier_list(request: Request, db: DbSession, q: str = "", state: str = "active"):
    access = _require(
        request, db, "suppliers.read", "suppliers.write", "stock.read", "stock.manage", "admin.manage"
    )
    if isinstance(access, RedirectResponse):
        return access
    user, permissions = access
    active = True if state == "active" else False if state == "inactive" else None
    suppliers = PartnersFacade(db).list_records(query=q, active=active)
    supplier_ids = [item.id for item in suppliers]
    type_rows = db.execute(
        select(SupplierTypeAssignment.supplier_id, SupplierType)
        .join(SupplierType, SupplierType.id == SupplierTypeAssignment.supplier_type_id)
        .where(SupplierTypeAssignment.supplier_id.in_(supplier_ids or [-1]))
        .order_by(SupplierType.sort_order, SupplierType.name)
    ).all()
    types_by_supplier: dict[int, list[SupplierType]] = defaultdict(list)
    for supplier_id, supplier_type in type_rows:
        types_by_supplier[supplier_id].append(supplier_type)
    return templates.TemplateResponse(
        request,
        "clean_suppliers.html",
        {
            "active_menu": "suppliers",
            "current_user": user,
            "permission_codes": permissions,
            "suppliers": suppliers,
            "types_by_supplier": types_by_supplier,
            "supplier_types": list(
                db.scalars(
                    select(SupplierType)
                    .where(SupplierType.active.is_(True), SupplierType.parent_id.is_(None))
                    .order_by(SupplierType.sort_order, SupplierType.name)
                )
            ),
            "q": q,
            "state": state,
            "can_edit": bool(permissions.intersection({"suppliers.write", "admin.manage"})),
            "foundation_ui_enabled": settings.visual_foundation_enabled,
        },
    )


@supplier_router.post("/v2-clean/suppliers")
def supplier_create(
    request: Request,
    db: DbSession,
    name: str = Form(""),
    legal_name: str = Form(""),
    tax_id: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    type_ids: list[int] = Form(default=[]),
):
    access = _require(request, db, "suppliers.write", "admin.manage")
    if isinstance(access, RedirectResponse):
        return access
    user, _permissions = access
    clean_name = name.strip()
    clean_tax_id = tax_id.strip() or None
    if not clean_name:
        return RedirectResponse("/v2-clean/suppliers?error=missing_name", status_code=303)
    if clean_tax_id and db.scalar(select(StockSupplier).where(StockSupplier.tax_id == clean_tax_id)):
        return RedirectResponse("/v2-clean/suppliers?error=duplicate_tax_id", status_code=303)
    supplier = StockSupplier(
        name=clean_name,
        legal_name=legal_name.strip() or None,
        tax_id=clean_tax_id,
        email=email.strip() or None,
        phone=phone.strip() or None,
        created_by_id=user.id,
        updated_by_id=user.id,
        active=True,
    )
    db.add(supplier)
    db.flush()
    valid_type_ids = set(
        db.scalars(select(SupplierType.id).where(SupplierType.id.in_(type_ids or [-1]), SupplierType.active.is_(True)))
    )
    for type_id in valid_type_ids:
        db.add(SupplierTypeAssignment(supplier_id=supplier.id, supplier_type_id=type_id, created_by_id=user.id))
    record_audit(db, "supplier.created", "supplier", supplier.id, detail=supplier.name, user_id=user.id)
    db.commit()
    return RedirectResponse(f"/v2-clean/suppliers/{supplier.id}?saved=created", status_code=303)


@supplier_router.get("/v2-clean/suppliers/{supplier_id}", response_class=HTMLResponse)
def supplier_detail(request: Request, supplier_id: int, db: DbSession):
    access = _require(
        request, db, "suppliers.read", "suppliers.write", "stock.read", "stock.manage", "admin.manage"
    )
    if isinstance(access, RedirectResponse):
        return access
    user, permissions = access
    supplier = PartnersFacade(db).get_record(supplier_id)
    if not supplier:
        return RedirectResponse("/v2-clean/suppliers?error=missing", status_code=303)
    document_rows = db.execute(
        select(DocumentLink, Document)
        .join(Document, Document.id == DocumentLink.document_id)
        .where(DocumentLink.entity_type == "supplier", DocumentLink.entity_id == str(supplier.id))
        .order_by(Document.created_at.desc())
    ).all()
    audit = list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.entity_type == "supplier", AuditLog.entity_id == str(supplier.id))
            .order_by(AuditLog.created_at.desc())
            .limit(50)
        )
    )
    return templates.TemplateResponse(
        request,
        "clean_supplier_detail.html",
        {
            "active_menu": "suppliers",
            "current_user": user,
            "permission_codes": permissions,
            "supplier": supplier,
            "assigned_types": _supplier_types(db, supplier.id),
            "available_types": list(
                db.scalars(select(SupplierType).where(SupplierType.active.is_(True)).order_by(SupplierType.sort_order, SupplierType.name))
            ),
            "contacts": list(db.scalars(select(SupplierContact).where(SupplierContact.supplier_id == supplier.id).order_by(SupplierContact.is_primary.desc(), SupplierContact.name))),
            "addresses": list(db.scalars(select(SupplierAddress).where(SupplierAddress.supplier_id == supplier.id).order_by(SupplierAddress.is_primary.desc(), SupplierAddress.label))),
            "documents": document_rows,
            "invoice_count": db.scalar(select(func.count()).select_from(StockInvoiceImport).where(StockInvoiceImport.supplier_id == supplier.id)) or 0,
            "audit_entries": audit,
            "audit_users": {item.id: item for item in db.scalars(select(User))},
            "can_edit": bool(permissions.intersection({"suppliers.write", "admin.manage"})),
            "can_email": bool(permissions.intersection({"email.reply", "email.manage", "admin.manage"})) and supplier.active and bool(supplier.email),
            "foundation_ui_enabled": settings.visual_foundation_enabled,
        },
    )


@supplier_router.post("/v2-clean/suppliers/{supplier_id}")
def supplier_update(
    request: Request,
    supplier_id: int,
    db: DbSession,
    name: str = Form(""), legal_name: str = Form(""), tax_id: str = Form(""),
    registration_number: str = Form(""), email: str = Form(""), secondary_email: str = Form(""),
    phone: str = Form(""), secondary_phone: str = Form(""), contact_name: str = Form(""),
    website: str = Form(""), address: str = Form(""), address_line2: str = Form(""),
    postal_code: str = Form(""), city: str = Form(""), country_code: str = Form("PT"),
    payment_terms: str = Form(""), notes: str = Form(""), active: str = Form(""),
    type_ids: list[int] = Form(default=[]),
):
    access = _require(request, db, "suppliers.write", "admin.manage")
    if isinstance(access, RedirectResponse):
        return access
    user, _permissions = access
    supplier = db.get(StockSupplier, supplier_id)
    if not supplier or not name.strip():
        return RedirectResponse("/v2-clean/suppliers?error=missing", status_code=303)
    clean_tax_id = tax_id.strip() or None
    duplicate = clean_tax_id and db.scalar(select(StockSupplier.id).where(StockSupplier.tax_id == clean_tax_id, StockSupplier.id != supplier.id))
    if duplicate:
        return RedirectResponse(f"/v2-clean/suppliers/{supplier.id}?error=duplicate_tax_id", status_code=303)
    before = {key: getattr(supplier, key) for key in ("name", "tax_id", "email", "phone", "active", "notes")}
    for field, value in {
        "name": name, "legal_name": legal_name, "registration_number": registration_number,
        "email": email, "secondary_email": secondary_email, "phone": phone,
        "secondary_phone": secondary_phone, "contact_name": contact_name, "website": website,
        "address": address, "address_line2": address_line2, "postal_code": postal_code,
        "city": city, "payment_terms": payment_terms, "notes": notes,
    }.items():
        setattr(supplier, field, value.strip() or None)
    supplier.tax_id = clean_tax_id
    supplier.country_code = (country_code.strip().upper() or "PT")[:2]
    supplier.active = active == "on"
    supplier.updated_by_id = user.id
    current = {item.supplier_type_id: item for item in db.scalars(select(SupplierTypeAssignment).where(SupplierTypeAssignment.supplier_id == supplier.id))}
    valid_type_ids = set(db.scalars(select(SupplierType.id).where(SupplierType.id.in_(type_ids or [-1]), SupplierType.active.is_(True))))
    # Inactivation prevents new selections but never erases historical/current
    # associations merely because an unrelated field on the supplier is edited.
    inactive_current_ids = set(
        db.scalars(
            select(SupplierType.id).where(
                SupplierType.id.in_(set(current) or {-1}),
                SupplierType.active.is_(False),
            )
        )
    )
    valid_type_ids.update(inactive_current_ids)
    for type_id in valid_type_ids - set(current):
        db.add(SupplierTypeAssignment(supplier_id=supplier.id, supplier_type_id=type_id, created_by_id=user.id))
    for type_id in set(current) - valid_type_ids:
        db.delete(current[type_id])
    record_audit(db, "supplier.updated", "supplier", supplier.id, detail=supplier.name, user_id=user.id, before_json=before, after_json={key: getattr(supplier, key) for key in before})
    db.commit()
    return RedirectResponse(f"/v2-clean/suppliers/{supplier.id}?saved=1", status_code=303)


@supplier_router.post("/v2-clean/suppliers/{supplier_id}/contacts")
def supplier_contact_create(request: Request, supplier_id: int, db: DbSession, name: str = Form(""), role: str = Form(""), email: str = Form(""), phone: str = Form(""), is_primary: str = Form(""), notes: str = Form("")):
    access = _require(request, db, "suppliers.write", "admin.manage")
    if isinstance(access, RedirectResponse): return access
    user, _ = access
    if not db.get(StockSupplier, supplier_id) or not name.strip(): return RedirectResponse("/v2-clean/suppliers?error=missing", status_code=303)
    if is_primary == "on":
        for item in db.scalars(select(SupplierContact).where(SupplierContact.supplier_id == supplier_id, SupplierContact.is_primary.is_(True))): item.is_primary = False
    item = SupplierContact(supplier_id=supplier_id, name=name.strip(), role=role.strip() or None, email=email.strip() or None, phone=phone.strip() or None, is_primary=is_primary == "on", notes=notes.strip() or None, active=True)
    db.add(item); db.flush(); record_audit(db, "supplier.contact_created", "supplier", supplier_id, detail=item.name, user_id=user.id); db.commit()
    return RedirectResponse(f"/v2-clean/suppliers/{supplier_id}?saved=contact", status_code=303)


@supplier_router.post("/v2-clean/suppliers/{supplier_id}/addresses")
def supplier_address_create(request: Request, supplier_id: int, db: DbSession, label: str = Form("Principal"), address_line1: str = Form(""), address_line2: str = Form(""), postal_code: str = Form(""), city: str = Form(""), country_code: str = Form("PT"), is_primary: str = Form("")):
    access = _require(request, db, "suppliers.write", "admin.manage")
    if isinstance(access, RedirectResponse): return access
    user, _ = access
    if not db.get(StockSupplier, supplier_id) or not address_line1.strip(): return RedirectResponse("/v2-clean/suppliers?error=missing", status_code=303)
    if is_primary == "on":
        for item in db.scalars(select(SupplierAddress).where(SupplierAddress.supplier_id == supplier_id, SupplierAddress.is_primary.is_(True))): item.is_primary = False
    item = SupplierAddress(supplier_id=supplier_id, label=label.strip() or "Principal", address_line1=address_line1.strip(), address_line2=address_line2.strip() or None, postal_code=postal_code.strip() or None, city=city.strip() or None, country_code=(country_code.strip().upper() or "PT")[:2], is_primary=is_primary == "on", active=True)
    db.add(item); db.flush(); record_audit(db, "supplier.address_created", "supplier", supplier_id, detail=item.label, user_id=user.id); db.commit()
    return RedirectResponse(f"/v2-clean/suppliers/{supplier_id}?saved=address", status_code=303)


@supplier_router.post("/v2-clean/suppliers/{supplier_id}/documents")
def supplier_document_link(request: Request, supplier_id: int, db: DbSession, document_id: int = Form(...), category: str = Form("general")):
    access = _require(request, db, "suppliers.write", "admin.manage")
    if isinstance(access, RedirectResponse): return access
    user, _ = access
    if not db.get(StockSupplier, supplier_id) or not db.get(Document, document_id): return RedirectResponse(f"/v2-clean/suppliers/{supplier_id}?error=document_missing", status_code=303)
    existing = db.scalar(select(DocumentLink).where(DocumentLink.document_id == document_id, DocumentLink.entity_type == "supplier", DocumentLink.entity_id == str(supplier_id)))
    if not existing:
        db.add(DocumentLink(document_id=document_id, entity_type="supplier", entity_id=str(supplier_id), category=category.strip() or "general"))
        record_audit(db, "supplier.document_linked", "supplier", supplier_id, detail=f"document:{document_id}", user_id=user.id)
        db.commit()
    return RedirectResponse(f"/v2-clean/suppliers/{supplier_id}?saved=document", status_code=303)


@supplier_router.get("/v2-clean/admin/suppliers", response_class=HTMLResponse)
def supplier_admin(request: Request, db: DbSession):
    access = _require(request, db, "suppliers.configuration.manage", "admin.manage")
    if isinstance(access, RedirectResponse): return access
    user, permissions = access
    supplier_types = list(db.scalars(select(SupplierType).order_by(SupplierType.module_code, SupplierType.sort_order, SupplierType.name)))
    return templates.TemplateResponse(request, "clean_suppliers_admin.html", {
        "active_menu": "clean_admin", "current_user": user, "permission_codes": permissions,
        "supplier_types": supplier_types, "types_by_id": {item.id: item for item in supplier_types},
        "suppliers": list(db.scalars(select(StockSupplier).order_by(StockSupplier.name))),
        "email_templates": list(db.scalars(select(EmailTemplate).order_by(EmailTemplate.module_code, EmailTemplate.name))),
        "module_codes": sorted(MODULE_CODES),
    })


@supplier_router.post("/v2-clean/admin/suppliers/types")
def supplier_type_create(request: Request, db: DbSession, code: str = Form(""), name: str = Form(""), module_code: str = Form("general"), parent_id: int | None = Form(None), description: str = Form(""), sort_order: int = Form(100)):
    access = _require(request, db, "suppliers.configuration.manage", "admin.manage")
    if isinstance(access, RedirectResponse): return access
    user, _ = access; clean_code = code.strip().lower(); clean_module = module_code.strip().lower()
    if not CODE_PATTERN.fullmatch(clean_code) or not name.strip() or clean_module not in MODULE_CODES: return RedirectResponse("/v2-clean/admin/suppliers?error=invalid_type", status_code=303)
    if parent_id and not db.get(SupplierType, parent_id): return RedirectResponse("/v2-clean/admin/suppliers?error=invalid_parent", status_code=303)
    db.add(SupplierType(code=clean_code, name=name.strip(), module_code=clean_module, parent_id=parent_id, description=description.strip() or None, sort_order=sort_order, active=True, created_by_id=user.id))
    try: db.commit()
    except IntegrityError: db.rollback(); return RedirectResponse("/v2-clean/admin/suppliers?error=duplicate_type", status_code=303)
    return RedirectResponse("/v2-clean/admin/suppliers?saved=type", status_code=303)


@supplier_router.post("/v2-clean/admin/suppliers/types/{type_id}")
def supplier_type_update(request: Request, type_id: int, db: DbSession, name: str = Form(""), module_code: str = Form("general"), parent_id: int | None = Form(None), description: str = Form(""), sort_order: int = Form(100), active: str = Form("")):
    access = _require(request, db, "suppliers.configuration.manage", "admin.manage")
    if isinstance(access, RedirectResponse): return access
    user, _ = access; item = db.get(SupplierType, type_id)
    if not item or not name.strip() or module_code not in MODULE_CODES or parent_id == item.id: return RedirectResponse("/v2-clean/admin/suppliers?error=invalid_type", status_code=303)
    before = {"name": item.name, "module_code": item.module_code, "parent_id": item.parent_id, "active": item.active}
    item.name=name.strip(); item.module_code=module_code; item.parent_id=parent_id; item.description=description.strip() or None; item.sort_order=sort_order; item.active=active == "on"
    record_audit(db, "supplier_type.updated", "supplier_type", item.id, user_id=user.id, before_json=before, after_json={"name": item.name, "module_code": item.module_code, "parent_id": item.parent_id, "active": item.active}); db.commit()
    return RedirectResponse("/v2-clean/admin/suppliers?saved=type", status_code=303)


def _template_scope_valid(db: DbSession, supplier_id: int | None, supplier_type_id: int | None, module_code: str | None) -> bool:
    return (not supplier_id or db.get(StockSupplier, supplier_id) is not None) and (not supplier_type_id or db.get(SupplierType, supplier_type_id) is not None) and (not module_code or module_code in MODULE_CODES)


@supplier_router.post("/v2-clean/admin/suppliers/email-templates")
def supplier_template_create(request: Request, db: DbSession, code: str = Form(""), name: str = Form(""), subject_template: str = Form(""), body_template: str = Form(""), supplier_id: int | None = Form(None), supplier_type_id: int | None = Form(None), module_code: str = Form(""), context_code: str = Form("")):
    access = _require(request, db, "suppliers.configuration.manage", "admin.manage")
    if isinstance(access, RedirectResponse): return access
    user, _ = access; clean_code=code.strip().lower(); clean_module=module_code.strip().lower() or None
    if not CODE_PATTERN.fullmatch(clean_code) or not name.strip() or not body_template.strip() or not _template_scope_valid(db, supplier_id, supplier_type_id, clean_module): return RedirectResponse("/v2-clean/admin/suppliers?error=invalid_template", status_code=303)
    db.add(EmailTemplate(code=clean_code, name=name.strip(), subject_template=subject_template.strip() or None, body_template=body_template.strip(), version=1, allowed_variables_json=[], supplier_id=supplier_id, supplier_type_id=supplier_type_id, module_code=clean_module, context_code=context_code.strip() or None, active=True, created_by_id=user.id))
    try: db.commit()
    except IntegrityError: db.rollback(); return RedirectResponse("/v2-clean/admin/suppliers?error=duplicate_template", status_code=303)
    return RedirectResponse("/v2-clean/admin/suppliers?saved=template", status_code=303)


@supplier_router.post("/v2-clean/admin/suppliers/email-templates/{template_id}")
def supplier_template_update(request: Request, template_id: int, db: DbSession, name: str = Form(""), subject_template: str = Form(""), body_template: str = Form(""), supplier_id: int | None = Form(None), supplier_type_id: int | None = Form(None), module_code: str = Form(""), context_code: str = Form(""), active: str = Form("")):
    access = _require(request, db, "suppliers.configuration.manage", "admin.manage")
    if isinstance(access, RedirectResponse): return access
    user, _ = access; item=db.get(EmailTemplate, template_id); clean_module=module_code.strip().lower() or None
    if not item or not name.strip() or not body_template.strip() or not _template_scope_valid(db, supplier_id, supplier_type_id, clean_module): return RedirectResponse("/v2-clean/admin/suppliers?error=invalid_template", status_code=303)
    before={"name":item.name,"version":item.version,"active":item.active}; changed=any((item.name!=name.strip(), item.subject_template!=(subject_template.strip() or None), item.body_template!=body_template.strip(), item.supplier_id!=supplier_id, item.supplier_type_id!=supplier_type_id, item.module_code!=clean_module, item.context_code!=(context_code.strip() or None)))
    item.name=name.strip(); item.subject_template=subject_template.strip() or None; item.body_template=body_template.strip(); item.supplier_id=supplier_id; item.supplier_type_id=supplier_type_id; item.module_code=clean_module; item.context_code=context_code.strip() or None; item.active=active == "on"; item.version += 1 if changed else 0
    record_audit(db,"supplier_email_template.updated","email_template",item.id,user_id=user.id,before_json=before,after_json={"name":item.name,"version":item.version,"active":item.active}); db.commit()
    return RedirectResponse("/v2-clean/admin/suppliers?saved=template", status_code=303)
