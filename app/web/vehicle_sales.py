import csv
import hashlib
import io
import secrets
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from sqlalchemy import func, select

import app.web.router as base_router
from app.core.config import settings
from app.models import (
    PortalOrganization,
    PortalPublicationAccess,
    Vehicle,
    VehicleExternalSnapshot,
    VehicleFinancialPlan,
    VehicleImage,
    VehicleManualField,
    VehicleSaleLead,
    VehicleSaleProfile,
    VehicleSalePublication,
)
from app.services.audit import record_audit
from app.services.portal_access import (
    PORTAL_VISIBILITIES,
    PORTAL_VISIBILITY_LABELS,
    portal_context,
    portal_csrf_token,
    publication_allowed_for_portal,
    valid_portal_csrf,
)
from app.services.vehicle_sales import (
    IMAGE_CATEGORIES,
    IMAGE_CATEGORY_LABELS,
    LEAD_KIND_LABELS,
    LEAD_KINDS,
    LEAD_STATUS_LABELS,
    LEAD_STATUSES,
    MARGIN_MODE_LABELS,
    MARGIN_MODES,
    PRICE_BASE_LABELS,
    PRICE_BASES,
    PUBLICATION_AUDIENCE_LABELS,
    PUBLICATION_AUDIENCES,
    ROUNDING_MODE_LABELS,
    ROUNDING_MODES,
    SALE_STATUS_LABELS,
    SALE_STATUSES,
    VEHICLE_SALE_STATE_LABELS,
    VEHICLE_SALE_STATES,
    calculate_selling_price,
    date_value,
    decimal_value,
    margin,
    masked_plate,
    money,
)

vehicle_sales_router = APIRouter(include_in_schema=False)

VEHICLE_IMAGE_MAX_SIZE = 10 * 1024 * 1024
VEHICLE_IMAGE_SIGNATURES = {
    "image/jpeg": (".jpg", lambda content: content.startswith(b"\xff\xd8\xff")),
    "image/png": (".png", lambda content: content.startswith(b"\x89PNG\r\n\x1a\n")),
    "image/webp": (
        ".webp",
        lambda content: content.startswith(b"RIFF") and content[8:12] == b"WEBP",
    ),
}


def _sales_access_denied(request: Request):
    denied = base_router.clean_experience_denied(request)
    if denied:
        return denied
    if not base_router.get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    if not base_router.can_manage_carfast_fleet(request):
        return RedirectResponse("/v2-clean?error=forbidden", status_code=303)
    return None


def _publication_request_context(request: Request, db, publication):
    context = portal_context(request, db)
    allowed = publication_allowed_for_portal(db, publication, context)
    if allowed and context:
        required_price_permission = (
            "vehicles.trade_price.view"
            if publication.audience == "trade"
            else "vehicles.retail_price.view"
        )
        allowed = context.has(required_price_permission)
    if not allowed and base_router.can_manage_carfast_fleet(request):
        allowed = True
    return context, allowed


def _media_root() -> Path:
    configured = (settings.vehicle_sale_media_root or "").strip()
    root = (
        Path(configured).expanduser()
        if configured
        else base_router.APP_PROJECT_ROOT / "uploads" / "vehicle_sales"
    )
    if not root.is_absolute():
        root = base_router.APP_PROJECT_ROOT / root
    return root.resolve()


def _resolved_image_path(image: VehicleImage) -> Path | None:
    root = _media_root()
    candidate = (root / image.storage_path).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        return None
    return candidate


def _detected_image(content: bytes) -> tuple[str, str] | None:
    for content_type, (suffix, validator) in VEHICLE_IMAGE_SIGNATURES.items():
        if validator(content):
            return content_type, suffix
    return None


def _default_sale_status(vehicle: Vehicle) -> str:
    if vehicle.lifecycle_status == "sold" or vehicle.operational_status == "sold":
        return "sold"
    if vehicle.lifecycle_status == "for_sale":
        return "for_sale"
    return "candidate"


def _get_or_create_profile(db, vehicle: Vehicle) -> VehicleSaleProfile:
    profile = db.scalar(
        select(VehicleSaleProfile).where(VehicleSaleProfile.vehicle_id == vehicle.id)
    )
    if profile:
        return profile
    profile = VehicleSaleProfile(vehicle_id=vehicle.id, status=_default_sale_status(vehicle))
    db.add(profile)
    db.flush()
    return profile


def _profile_json(profile: VehicleSaleProfile) -> dict[str, Any]:
    return {
        "status": profile.status,
        "market_trade_value": str(profile.market_trade_value)
        if profile.market_trade_value is not None
        else None,
        "market_retail_value": str(profile.market_retail_value)
        if profile.market_retail_value is not None
        else None,
        "selling_price": str(profile.selling_price) if profile.selling_price is not None else None,
        "market_value_source": profile.market_value_source,
        "market_valued_on": profile.market_valued_on.isoformat()
        if profile.market_valued_on
        else None,
        "price_base": profile.price_base,
        "margin_mode": profile.margin_mode,
        "margin_value": str(profile.margin_value) if profile.margin_value is not None else None,
        "rounding_mode": profile.rounding_mode,
        "rounding_increment": str(profile.rounding_increment)
        if profile.rounding_increment is not None
        else None,
        "sale_notes": profile.sale_notes,
        "public_notes": profile.public_notes,
    }


def _vehicle_state(vehicle: Vehicle, commercial: dict[str, Any]) -> str:
    operational = str(vehicle.operational_status or "").strip().lower()
    rentway_status = str(commercial.get("current_status") or "").strip().lower()
    combined = f"{operational} {rentway_status}"
    if "impro" in combined:
        return "impro"
    if operational in {"free", "available"} or any(
        word in rentway_status for word in ("livre", "free", "available")
    ):
        return "free"
    if (
        operational in {"in_contract", "contract"}
        or commercial.get("document_nr")
        or commercial.get("return_date")
    ):
        return "contract"
    return "free"


def compact_finance_entity(value: object) -> str:
    label = str(value or "").strip()
    normalized = label.casefold()
    if not label:
        return "Sem financiamento"
    if "locação corrente" in normalized or "locacao corrente" in normalized:
        return "CGD Locação"
    if "caixa geral de depósitos" in normalized or "caixa geral de depositos" in normalized:
        return "CGD"
    if normalized == "cgd" or normalized.startswith("cgd "):
        return "CGD"
    if "santander" in normalized:
        return "Santander"
    if "banco bpi" in normalized or normalized == "bpi" or normalized.startswith("bpi "):
        return "BPI"
    if "leaseplan" in normalized:
        return "LeasePlan"
    if "mercedes" in normalized:
        return "Mercedes"
    return label


def _sale_row(
    vehicle: Vehicle,
    snapshot: VehicleExternalSnapshot | None,
    manual: dict[str, Any],
    profile: VehicleSaleProfile | None,
    financial_plan: VehicleFinancialPlan | None,
) -> dict[str, Any]:
    commercial = base_router.rentway_commercial_context(snapshot)
    vehicle_context = base_router.rentway_vehicle_context(snapshot)
    finance = base_router.current_cost_from_snapshot(snapshot)
    rentway_current_cost = decimal_value(finance.get("current_cost_with_vat"))
    cost = rentway_current_cost
    if cost is None:
        cost = decimal_value(
            base_router.current_value_with_financial_amortization(
                finance.get("initial_cost_with_vat"),
                financial_plan.initial_amount if financial_plan else None,
                financial_plan.outstanding_amount if financial_plan else None,
                None,
                finance.get("purchase_date")
                or (financial_plan.start_date if financial_plan else None),
                financial_plan.amount_reference_date if financial_plan else None,
            )
        )
    # A financial margin only exists when an active financial plan supplies a balance.
    # Legacy manual debt fields must not make an unfinanced vehicle look financed.
    debt = decimal_value(financial_plan.outstanding_amount) if financial_plan else None
    market_trade = decimal_value(profile.market_trade_value) if profile else None
    market_retail = decimal_value(profile.market_retail_value) if profile else None
    financial_margin = margin(cost, debt)
    commercial_margin = margin(cost, market_trade, comparison_minus_cost=True)
    registration = date_value(vehicle_context.get("plate_date"))
    return_on = date_value(commercial.get("return_date"))
    state = _vehicle_state(vehicle, commercial)
    status = profile.status if profile else _default_sale_status(vehicle)
    finance_entity = str(
        (financial_plan.finance_entity if financial_plan else None)
        or manual.get("finance_entity")
        or commercial.get("finance_entity")
        or ""
    ).strip()
    return {
        "vehicle": vehicle,
        "snapshot": snapshot,
        "profile": profile,
        "status": status,
        "status_label": SALE_STATUS_LABELS.get(status, status),
        "vehicle_state": state,
        "vehicle_state_label": VEHICLE_SALE_STATE_LABELS.get(state, state),
        "return_on": return_on,
        "return_on_display": return_on.strftime("%d/%m/%Y") if return_on else "-",
        "registration": registration,
        "registration_display": registration.strftime("%d/%m/%Y") if registration else "-",
        "finance_entity": finance_entity,
        "finance_entity_display": compact_finance_entity(finance_entity),
        "cost": cost,
        "cost_missing_reason": (
            "Sem custo de aquisição Rentway"
            if finance.get("initial_cost_with_vat") is None
            else "Sem data de compra para calcular a amortização"
        )
        if cost is None
        else "",
        "debt": debt,
        "financial_margin": financial_margin,
        "market_trade": market_trade,
        "commercial_margin": commercial_margin,
        "market_retail": market_retail,
        "selling_price": decimal_value(profile.selling_price) if profile else None,
        "km": decimal_value(commercial.get("km")),
        "sale_blocked": bool(manual.get("sale_blocked")),
        "sale_notes": profile.sale_notes if profile else "",
        "money": money,
    }


def _active_financial_plan(db, vehicle_id: int) -> VehicleFinancialPlan | None:
    return db.scalar(
        select(VehicleFinancialPlan)
        .where(
            VehicleFinancialPlan.vehicle_id == vehicle_id,
            VehicleFinancialPlan.active.is_(True),
        )
        .order_by(VehicleFinancialPlan.updated_at.desc(), VehicleFinancialPlan.id.desc())
        .limit(1)
    )


def _load_sale_rows(db) -> list[dict[str, Any]]:
    vehicles = db.scalars(
        select(Vehicle)
        .where(Vehicle.active.is_(True))
        .order_by(Vehicle.updated_at.desc(), Vehicle.id.desc())
        .limit(5000)
    ).all()
    vehicle_ids = [vehicle.id for vehicle in vehicles]
    if not vehicle_ids:
        return []
    snapshots = {
        snapshot.vehicle_id: snapshot
        for snapshot in db.scalars(
            select(VehicleExternalSnapshot).where(
                VehicleExternalSnapshot.vehicle_id.in_(vehicle_ids),
                VehicleExternalSnapshot.source_system == "rentway",
            )
        ).all()
    }
    profiles = {
        profile.vehicle_id: profile
        for profile in db.scalars(
            select(VehicleSaleProfile).where(VehicleSaleProfile.vehicle_id.in_(vehicle_ids))
        ).all()
    }
    financial_plans: dict[int, VehicleFinancialPlan] = {}
    for plan in db.scalars(
        select(VehicleFinancialPlan)
        .where(
            VehicleFinancialPlan.vehicle_id.in_(vehicle_ids),
            VehicleFinancialPlan.active.is_(True),
        )
        .order_by(VehicleFinancialPlan.updated_at.desc(), VehicleFinancialPlan.id.desc())
    ).all():
        financial_plans.setdefault(plan.vehicle_id, plan)
    manual_by_vehicle: dict[int, dict[str, Any]] = {vehicle_id: {} for vehicle_id in vehicle_ids}
    for field in db.scalars(
        select(VehicleManualField).where(
            VehicleManualField.vehicle_id.in_(vehicle_ids),
            VehicleManualField.field_code.in_(["finance_entity", "debt_value", "sale_blocked"]),
        )
    ).all():
        manual_by_vehicle[field.vehicle_id][field.field_code] = field.value_json
    return [
        _sale_row(
            vehicle,
            snapshots.get(vehicle.id),
            manual_by_vehicle.get(vehicle.id, {}),
            profiles.get(vehicle.id),
            financial_plans.get(vehicle.id),
        )
        for vehicle in vehicles
    ]


def _financial_audit_rows(db) -> list[dict[str, Any]]:
    vehicles = db.scalars(
        select(Vehicle)
        .where(Vehicle.active.is_(True))
        .order_by(Vehicle.plate, Vehicle.id)
    ).all()
    vehicle_ids = [vehicle.id for vehicle in vehicles]
    if not vehicle_ids:
        return []

    snapshots: dict[int, VehicleExternalSnapshot] = {}
    for snapshot in db.scalars(
        select(VehicleExternalSnapshot)
        .where(
            VehicleExternalSnapshot.vehicle_id.in_(vehicle_ids),
            VehicleExternalSnapshot.source_system == "rentway",
        )
        .order_by(
            VehicleExternalSnapshot.updated_at.desc(),
            VehicleExternalSnapshot.id.desc(),
        )
    ).all():
        snapshots.setdefault(snapshot.vehicle_id, snapshot)

    plans_by_vehicle: dict[int, list[VehicleFinancialPlan]] = {
        vehicle_id: [] for vehicle_id in vehicle_ids
    }
    active_plans: dict[int, VehicleFinancialPlan] = {}
    for plan in db.scalars(
        select(VehicleFinancialPlan)
        .where(VehicleFinancialPlan.vehicle_id.in_(vehicle_ids))
        .order_by(
            VehicleFinancialPlan.active.desc(),
            VehicleFinancialPlan.updated_at.desc(),
            VehicleFinancialPlan.id.desc(),
        )
    ).all():
        plans_by_vehicle[plan.vehicle_id].append(plan)
        if plan.active:
            active_plans.setdefault(plan.vehicle_id, plan)

    active_contract_plans: dict[tuple[str, str], list[VehicleFinancialPlan]] = {}
    for plan in active_plans.values():
        key = (
            str(plan.finance_entity or "").strip().casefold(),
            str(plan.contract_number or "").strip().casefold(),
        )
        active_contract_plans.setdefault(key, []).append(plan)

    rows: list[dict[str, Any]] = []
    for vehicle in vehicles:
        snapshot = snapshots.get(vehicle.id)
        plan = active_plans.get(vehicle.id)
        rentway_cost = base_router.current_cost_from_snapshot(snapshot)
        initial_with_vat = rentway_cost.get("initial_cost_with_vat")
        current_with_vat = base_router.current_value_with_financial_amortization(
            initial_with_vat,
            plan.initial_amount if plan else None,
            plan.outstanding_amount if plan else None,
            rentway_cost.get("current_cost_with_vat"),
            plan.start_date if plan else None,
            plan.amount_reference_date if plan else None,
        )
        contract_key = (
            str(plan.finance_entity or "").strip().casefold(),
            str(plan.contract_number or "").strip().casefold(),
        ) if plan else ("", "")
        residual = base_router.residual_amount_for_vehicle(
            plan,
            active_contract_plans.get(contract_key, []),
        )
        missing: list[str] = []
        if not plan:
            missing.append("plano ativo")
        else:
            for label, value in (
                ("entidade", plan.finance_entity),
                ("contrato", plan.contract_number),
                ("início", plan.start_date),
                ("fim", plan.end_date),
                ("prestação/renda", plan.installment_with_vat),
                ("valor residual", residual),
                ("capital em dívida", plan.outstanding_amount),
                ("data do capital", plan.amount_reference_date),
            ):
                if value in (None, ""):
                    missing.append(label)
        if initial_with_vat is None:
            missing.append("custo inicial Rentway")
        if current_with_vat is None:
            missing.append("valor atual")
        rows.append(
            {
                "vehicle_id": vehicle.id,
                "plate": vehicle.plate or "",
                "unit": vehicle.rentway_unit_nr or "",
                "finance_entity": plan.finance_entity if plan else "",
                "contract_number": plan.contract_number if plan else "",
                "start_date": plan.start_date.isoformat() if plan and plan.start_date else "",
                "end_date": plan.end_date.isoformat() if plan and plan.end_date else "",
                "installment_with_vat": plan.installment_with_vat if plan else None,
                "residual_with_vat": residual,
                "outstanding_with_vat": (
                    base_router.amount_with_standard_vat(plan.outstanding_amount)
                    if plan else None
                ),
                "amount_reference_date": (
                    plan.amount_reference_date.isoformat()
                    if plan and plan.amount_reference_date else ""
                ),
                "initial_cost_with_vat": initial_with_vat,
                "amortization_month": rentway_cost.get("amortization_month"),
                "current_value_with_vat": current_with_vat,
                "plan_count": len(plans_by_vehicle.get(vehicle.id, [])),
                "missing_count": len(missing),
                "missing_fields": ", ".join(missing),
            }
        )
    return rows


def _safe_return_url(value: str, fallback: str) -> str:
    clean = value.strip()
    if clean.startswith("/v2-clean/fleet/sales") and not clean.startswith("//"):
        return clean
    return fallback


def _filter_rows(rows: list[dict[str, Any]], filters: dict[str, str]) -> list[dict[str, Any]]:
    registration_from = date_value(filters["registration_from"])
    registration_to = date_value(filters["registration_to"])
    return_from = date_value(filters["return_from"])
    return_to = date_value(filters["return_to"])
    financial_min = decimal_value(filters["financial_margin_min"])
    financial_max = decimal_value(filters["financial_margin_max"])
    commercial_min = decimal_value(filters["commercial_margin_min"])
    commercial_max = decimal_value(filters["commercial_margin_max"])
    query = filters["q"].casefold()
    filtered = []
    for row in rows:
        vehicle = row["vehicle"]
        haystack = " ".join(
            str(value or "")
            for value in [
                vehicle.plate,
                vehicle.rentway_unit_nr,
                vehicle.vin,
                vehicle.brand,
                vehicle.model,
                row["finance_entity"],
            ]
        ).casefold()
        if query and query not in haystack:
            continue
        if filters["sale_status"] and row["status"] != filters["sale_status"]:
            continue
        if filters["finance_entity"] and row["finance_entity"] != filters["finance_entity"]:
            continue
        if filters["vehicle_state"] and row["vehicle_state"] != filters["vehicle_state"]:
            continue
        if registration_from and (
            not row["registration"] or row["registration"] < registration_from
        ):
            continue
        if registration_to and (not row["registration"] or row["registration"] > registration_to):
            continue
        if return_from and (
            row["vehicle_state"] != "contract"
            or not row["return_on"]
            or row["return_on"] < return_from
        ):
            continue
        if return_to and (
            row["vehicle_state"] != "contract"
            or not row["return_on"]
            or row["return_on"] > return_to
        ):
            continue
        if financial_min is not None and (
            row["financial_margin"] is None or row["financial_margin"] < financial_min
        ):
            continue
        if financial_max is not None and (
            row["financial_margin"] is None or row["financial_margin"] > financial_max
        ):
            continue
        if commercial_min is not None and (
            row["commercial_margin"] is None or row["commercial_margin"] < commercial_min
        ):
            continue
        if commercial_max is not None and (
            row["commercial_margin"] is None or row["commercial_margin"] > commercial_max
        ):
            continue
        if filters["market_state"] == "missing_trade" and row["market_trade"] is not None:
            continue
        if filters["market_state"] == "missing_retail" and row["market_retail"] is not None:
            continue
        filtered.append(row)
    return filtered


@vehicle_sales_router.get("/v2-clean/fleet/sales", response_class=HTMLResponse)
def vehicle_sales_page(
    request: Request,
    q: str = "",
    sale_status: str = "",
    finance_entity: str = "",
    vehicle_state: str = "",
    registration_from: str = "",
    registration_to: str = "",
    return_from: str = "",
    return_to: str = "",
    financial_margin_min: str = "",
    financial_margin_max: str = "",
    commercial_margin_min: str = "",
    commercial_margin_max: str = "",
    market_state: str = "",
    page: int = 1,
    updated: int | None = None,
    error: str = "",
):
    denied = _sales_access_denied(request)
    if denied:
        return denied
    filters = {
        "q": q.strip(),
        "sale_status": sale_status if sale_status in SALE_STATUS_LABELS else "",
        "finance_entity": finance_entity.strip(),
        "vehicle_state": vehicle_state if vehicle_state in VEHICLE_SALE_STATE_LABELS else "",
        "registration_from": registration_from.strip(),
        "registration_to": registration_to.strip(),
        "return_from": return_from.strip(),
        "return_to": return_to.strip(),
        "financial_margin_min": financial_margin_min.strip(),
        "financial_margin_max": financial_margin_max.strip(),
        "commercial_margin_min": commercial_margin_min.strip(),
        "commercial_margin_max": commercial_margin_max.strip(),
        "market_state": market_state if market_state in {"missing_trade", "missing_retail"} else "",
    }
    with base_router.SessionLocal() as db:
        all_rows = _load_sale_rows(db)
        rows = _filter_rows(all_rows, filters)
        page_size = 100
        total_pages = max(1, (len(rows) + page_size - 1) // page_size)
        current_page = min(max(1, page), total_pages)
        visible_rows = rows[(current_page - 1) * page_size : current_page * page_size]
        counts = {
            code: sum(1 for row in all_rows if row["status"] == code) for code in SALE_STATUS_LABELS
        }
        counts["missing_market"] = sum(
            1
            for row in all_rows
            if row["status"] in {"candidate", "for_sale"}
            and (row["market_trade"] is None or row["market_retail"] is None)
        )
        counts["blocked"] = sum(1 for row in all_rows if row["sale_blocked"])
        finance_options = sorted(
            {row["finance_entity"] for row in all_rows if row["finance_entity"]},
            key=str.casefold,
        )
    query_without_page = urlencode({key: value for key, value in filters.items() if value})
    return base_router.templates.TemplateResponse(
        request,
        "clean_vehicle_sales.html",
        {
            "rows": visible_rows,
            "total_filtered": len(rows),
            "counts": counts,
            "filters": filters,
            "sale_statuses": SALE_STATUSES,
            "vehicle_states": VEHICLE_SALE_STATES,
            "finance_options": finance_options,
            "price_bases": PRICE_BASES,
            "margin_modes": MARGIN_MODES,
            "rounding_modes": ROUNDING_MODES,
            "page": current_page,
            "total_pages": total_pages,
            "query_without_page": query_without_page,
            "updated": updated,
            "error": error,
            "money": money,
        },
    )


@vehicle_sales_router.get("/v2-clean/fleet/financial-audit.csv")
def vehicle_financial_audit_export(request: Request, download: int = 1):
    denied = _sales_access_denied(request)
    if denied:
        return denied
    with base_router.SessionLocal() as db:
        rows = _financial_audit_rows(db)
    stream = io.StringIO(newline="")
    fieldnames = list(rows[0]) if rows else ["vehicle_id", "plate", "missing_fields"]
    writer = csv.DictWriter(stream, fieldnames=fieldnames, delimiter=";")
    writer.writeheader()
    writer.writerows(rows)
    headers = {}
    if download:
        headers["Content-Disposition"] = (
            f'attachment; filename="auditoria_financeira_viaturas_{date.today():%Y%m%d}.csv"'
        )
    return Response(
        content="\ufeff" + stream.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )


@vehicle_sales_router.post("/v2-clean/fleet/sales/bulk")
async def vehicle_sales_bulk_update(request: Request):
    denied = _sales_access_denied(request)
    if denied:
        return denied
    user_id = int(base_router.get_web_user_id(request))
    form = await request.form()
    selected_ids: list[int] = []
    for raw_id in form.getlist("vehicle_ids"):
        try:
            selected_ids.append(int(str(raw_id)))
        except ValueError:
            continue
    return_url = _safe_return_url(str(form.get("return_url") or ""), "/v2-clean/fleet/sales")
    action = str(form.get("action") or "")
    if not selected_ids:
        separator = "&" if "?" in return_url else "?"
        return RedirectResponse(f"{return_url}{separator}error=no_selection", status_code=303)

    changed = 0
    with base_router.SessionLocal() as db:
        vehicles = {
            vehicle.id: vehicle
            for vehicle in db.scalars(select(Vehicle).where(Vehicle.id.in_(selected_ids))).all()
        }
        for vehicle_id in selected_ids:
            vehicle = vehicles.get(vehicle_id)
            if not vehicle:
                continue
            profile = _get_or_create_profile(db, vehicle)
            before = _profile_json(profile)
            if action == "status":
                status = str(form.get("bulk_status") or "")
                if status not in SALE_STATUS_LABELS:
                    continue
                if profile.status != status:
                    profile.status = status
                    profile.status_changed_at = datetime.now(UTC)
                    profile.status_changed_by_id = user_id
            elif action == "market_values":
                trade_value = str(form.get("market_trade_value") or "").strip()
                retail_value = str(form.get("market_retail_value") or "").strip()
                if trade_value:
                    profile.market_trade_value = decimal_value(trade_value)
                if retail_value:
                    profile.market_retail_value = decimal_value(retail_value)
                source = str(form.get("market_value_source") or "").strip()
                if source:
                    profile.market_value_source = source[:200]
                profile.market_valued_on = date.today()
            elif action == "price_rule":
                price_base = str(form.get("price_base") or "")
                margin_mode = str(form.get("margin_mode") or "")
                rounding_mode = str(form.get("rounding_mode") or "none")
                if price_base not in PRICE_BASE_LABELS or margin_mode not in MARGIN_MODE_LABELS:
                    continue
                if rounding_mode not in ROUNDING_MODE_LABELS:
                    rounding_mode = "none"
                margin_amount = decimal_value(form.get("margin_value"))
                rounding_increment = decimal_value(form.get("rounding_increment"))
                base_value = (
                    profile.market_trade_value
                    if price_base == "trade"
                    else profile.market_retail_value
                )
                calculated = calculate_selling_price(
                    base_value,
                    margin_mode,
                    margin_amount,
                    rounding_mode,
                    rounding_increment,
                )
                profile.price_base = price_base
                profile.margin_mode = margin_mode
                profile.margin_value = margin_amount
                profile.rounding_mode = rounding_mode
                profile.rounding_increment = rounding_increment
                if calculated is not None:
                    profile.selling_price = calculated
            else:
                continue
            profile.updated_by_id = user_id
            after = _profile_json(profile)
            if before != after:
                changed += 1
                record_audit(
                    db,
                    action=f"vehicle.sale.bulk_{action}",
                    entity_type="vehicle",
                    entity_id=vehicle.id,
                    detail=f"Venda atualizada em lote: {vehicle.plate or vehicle.id}",
                    before_json=before,
                    after_json=after,
                    user_id=user_id,
                )
        db.commit()
    separator = "&" if "?" in return_url else "?"
    return RedirectResponse(f"{return_url}{separator}updated={changed}", status_code=303)


@vehicle_sales_router.get("/v2-clean/fleet/sales/{vehicle_id}", response_class=HTMLResponse)
def vehicle_sale_detail(request: Request, vehicle_id: int, saved: str = "", error: str = ""):
    denied = _sales_access_denied(request)
    if denied:
        return denied
    with base_router.SessionLocal() as db:
        vehicle = db.get(Vehicle, vehicle_id)
        if not vehicle:
            return RedirectResponse("/v2-clean/fleet/sales", status_code=303)
        profile = _get_or_create_profile(db, vehicle)
        snapshot = base_router.latest_vehicle_snapshot(db, vehicle.id)
        manual = base_router.vehicle_manual_values(db, vehicle.id)
        row = _sale_row(
            vehicle,
            snapshot,
            manual,
            profile,
            _active_financial_plan(db, vehicle.id),
        )
        images = db.scalars(
            select(VehicleImage)
            .where(VehicleImage.vehicle_id == vehicle.id, VehicleImage.active.is_(True))
            .order_by(VehicleImage.sort_order.asc(), VehicleImage.id.asc())
        ).all()
        publications = db.scalars(
            select(VehicleSalePublication)
            .where(VehicleSalePublication.vehicle_id == vehicle.id)
            .order_by(VehicleSalePublication.id.desc())
            .limit(20)
        ).all()
        leads = db.scalars(
            select(VehicleSaleLead)
            .where(VehicleSaleLead.vehicle_id == vehicle.id)
            .order_by(VehicleSaleLead.id.desc())
            .limit(100)
        ).all()
        portal_organizations = db.scalars(
            select(PortalOrganization)
            .where(PortalOrganization.status == "active")
            .order_by(PortalOrganization.name.asc())
        ).all()
        public_urls = {
            publication.id: _public_url(request, publication.token) for publication in publications
        }
    return base_router.templates.TemplateResponse(
        request,
        "clean_vehicle_sale_detail.html",
        {
            "vehicle": vehicle,
            "profile": profile,
            "row": row,
            "images": images,
            "publications": publications,
            "public_urls": public_urls,
            "leads": leads,
            "sale_statuses": SALE_STATUSES,
            "price_bases": PRICE_BASES,
            "margin_modes": MARGIN_MODES,
            "rounding_modes": ROUNDING_MODES,
            "image_categories": IMAGE_CATEGORIES,
            "image_category_labels": IMAGE_CATEGORY_LABELS,
            "publication_audiences": PUBLICATION_AUDIENCES,
            "publication_audience_labels": PUBLICATION_AUDIENCE_LABELS,
            "publication_visibilities": PORTAL_VISIBILITIES,
            "publication_visibility_labels": PORTAL_VISIBILITY_LABELS,
            "portal_organizations": portal_organizations,
            "lead_kind_labels": LEAD_KIND_LABELS,
            "lead_statuses": LEAD_STATUSES,
            "lead_status_labels": LEAD_STATUS_LABELS,
            "money": money,
            "saved": saved,
            "error": error,
        },
    )


@vehicle_sales_router.post("/v2-clean/fleet/sales/{vehicle_id}")
def vehicle_sale_update(
    request: Request,
    vehicle_id: int,
    status: str = Form("candidate"),
    market_trade_value: str = Form(""),
    market_retail_value: str = Form(""),
    selling_price: str = Form(""),
    market_value_source: str = Form(""),
    market_valued_on: str = Form(""),
    price_base: str = Form(""),
    margin_mode: str = Form(""),
    margin_value: str = Form(""),
    rounding_mode: str = Form("none"),
    rounding_increment: str = Form(""),
    sale_notes: str = Form(""),
    public_notes: str = Form(""),
):
    denied = _sales_access_denied(request)
    if denied:
        return denied
    user_id = int(base_router.get_web_user_id(request))
    with base_router.SessionLocal() as db:
        vehicle = db.get(Vehicle, vehicle_id)
        if not vehicle:
            return RedirectResponse("/v2-clean/fleet/sales", status_code=303)
        profile = _get_or_create_profile(db, vehicle)
        before = _profile_json(profile)
        normalized_status = status if status in SALE_STATUS_LABELS else "candidate"
        if profile.status != normalized_status:
            profile.status_changed_at = datetime.now(UTC)
            profile.status_changed_by_id = user_id
        profile.status = normalized_status
        profile.market_trade_value = decimal_value(market_trade_value)
        profile.market_retail_value = decimal_value(market_retail_value)
        profile.selling_price = decimal_value(selling_price)
        profile.market_value_source = market_value_source.strip()[:200] or None
        profile.market_valued_on = date_value(market_valued_on)
        profile.price_base = price_base if price_base in PRICE_BASE_LABELS else None
        profile.margin_mode = margin_mode if margin_mode in MARGIN_MODE_LABELS else None
        profile.margin_value = decimal_value(margin_value)
        profile.rounding_mode = rounding_mode if rounding_mode in ROUNDING_MODE_LABELS else "none"
        profile.rounding_increment = decimal_value(rounding_increment)
        profile.sale_notes = sale_notes.strip()[:10000] or None
        profile.public_notes = public_notes.strip()[:5000] or None
        profile.updated_by_id = user_id
        after = _profile_json(profile)
        record_audit(
            db,
            action="vehicle.sale.updated",
            entity_type="vehicle",
            entity_id=vehicle.id,
            detail=f"Ficha de venda atualizada: {vehicle.plate or vehicle.id}",
            before_json=before,
            after_json=after,
            user_id=user_id,
        )
        db.commit()
    return RedirectResponse(f"/v2-clean/fleet/sales/{vehicle_id}?saved=profile", status_code=303)


@vehicle_sales_router.post("/v2-clean/fleet/sales/{vehicle_id}/images")
async def vehicle_sale_image_upload(
    request: Request,
    vehicle_id: int,
    image: UploadFile = File(...),  # noqa: B008
    category: str = Form("other"),
    caption: str = Form(""),
):
    denied = _sales_access_denied(request)
    if denied:
        return denied
    user_id = int(base_router.get_web_user_id(request))
    content = await image.read(VEHICLE_IMAGE_MAX_SIZE + 1)
    if len(content) > VEHICLE_IMAGE_MAX_SIZE:
        return RedirectResponse(
            f"/v2-clean/fleet/sales/{vehicle_id}?error=image_too_large", status_code=303
        )
    detected = _detected_image(content)
    if not detected:
        return RedirectResponse(
            f"/v2-clean/fleet/sales/{vehicle_id}?error=invalid_image", status_code=303
        )
    content_type, suffix = detected
    with base_router.SessionLocal() as db:
        vehicle = db.get(Vehicle, vehicle_id)
        if not vehicle:
            return RedirectResponse("/v2-clean/fleet/sales", status_code=303)
        root = _media_root()
        vehicle_root = (root / str(vehicle.id)).resolve()
        if not vehicle_root.is_relative_to(root):
            return RedirectResponse(
                f"/v2-clean/fleet/sales/{vehicle_id}?error=storage", status_code=303
            )
        vehicle_root.mkdir(parents=True, exist_ok=True)
        stored_name = f"{uuid.uuid4().hex}{suffix}"
        stored_path = vehicle_root / stored_name
        stored_path.write_bytes(content)
        sort_order = (
            db.scalar(
                select(func.max(VehicleImage.sort_order)).where(
                    VehicleImage.vehicle_id == vehicle.id
                )
            )
            or 0
        ) + 1
        record = VehicleImage(
            vehicle_id=vehicle.id,
            original_name=Path(image.filename or "imagem").name[:255],
            storage_path=f"{vehicle.id}/{stored_name}",
            content_type=content_type,
            file_size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            category=category if category in IMAGE_CATEGORY_LABELS else "other",
            caption=caption.strip()[:500] or None,
            sort_order=sort_order,
            active=True,
            uploaded_by_id=user_id,
        )
        db.add(record)
        db.flush()
        record_audit(
            db,
            action="vehicle.image.uploaded",
            entity_type="vehicle_image",
            entity_id=record.id,
            detail=f"Imagem adicionada à viatura {vehicle.plate or vehicle.id}",
            after_json={
                "vehicle_id": vehicle.id,
                "category": record.category,
                "file_size": record.file_size,
                "sha256": record.sha256,
            },
            user_id=user_id,
        )
        db.commit()
    return RedirectResponse(f"/v2-clean/fleet/sales/{vehicle_id}?saved=image", status_code=303)


@vehicle_sales_router.get("/v2-clean/fleet/sales/{vehicle_id}/images/{image_id}")
def vehicle_sale_image_file(request: Request, vehicle_id: int, image_id: int):
    denied = _sales_access_denied(request)
    if denied:
        return denied
    with base_router.SessionLocal() as db:
        image = db.get(VehicleImage, image_id)
        if not image or image.vehicle_id != vehicle_id or not image.active:
            return HTMLResponse("Imagem não encontrada.", status_code=404)
        path = _resolved_image_path(image)
        if not path:
            return HTMLResponse("Ficheiro não encontrado.", status_code=404)
        return FileResponse(
            path,
            media_type=image.content_type,
            headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"},
        )


@vehicle_sales_router.post("/v2-clean/fleet/sales/{vehicle_id}/images/{image_id}/archive")
def vehicle_sale_image_archive(request: Request, vehicle_id: int, image_id: int):
    denied = _sales_access_denied(request)
    if denied:
        return denied
    user_id = int(base_router.get_web_user_id(request))
    with base_router.SessionLocal() as db:
        image = db.get(VehicleImage, image_id)
        if image and image.vehicle_id == vehicle_id and image.active:
            image.active = False
            record_audit(
                db,
                action="vehicle.image.archived",
                entity_type="vehicle_image",
                entity_id=image.id,
                detail=f"Imagem retirada da galeria da viatura {vehicle_id}",
                before_json={"active": True},
                after_json={"active": False},
                user_id=user_id,
            )
            db.commit()
    return RedirectResponse(
        f"/v2-clean/fleet/sales/{vehicle_id}?saved=image_archived", status_code=303
    )


def _public_url(request: Request, token: str) -> str:
    configured = (settings.vehicle_sales_public_base_url or "").strip().rstrip("/")
    base = configured or str(request.base_url).rstrip("/")
    return f"{base}/portal/viaturas/{token}"


def _public_snapshot(
    vehicle: Vehicle,
    profile: VehicleSaleProfile,
    row: dict[str, Any],
    audience: str,
) -> dict[str, Any]:
    price = profile.selling_price
    if price is None:
        price = profile.market_trade_value if audience == "trade" else profile.market_retail_value
    return {
        "schema": "carfast.vehicle-sale-public.v1",
        "vehicle": {
            "reference": f"CF-V-{vehicle.id:05d}",
            "plate": masked_plate(vehicle.plate),
            "brand": vehicle.brand or "-",
            "model": vehicle.model or "-",
            "version": vehicle.version or "-",
            "year": vehicle.year,
            "registration": row["registration"].isoformat() if row["registration"] else None,
            "km": str(row["km"]) if row["km"] is not None else None,
        },
        "sale": {
            "audience": audience,
            "audience_label": PUBLICATION_AUDIENCE_LABELS[audience],
            "availability": profile.status,
            "availability_label": SALE_STATUS_LABELS.get(profile.status, profile.status),
            "price": str(price) if price is not None else None,
            "public_notes": profile.public_notes,
        },
        "published_at": datetime.now(UTC).isoformat(),
    }


@vehicle_sales_router.post("/v2-clean/fleet/sales/{vehicle_id}/publish")
async def vehicle_sale_publish(request: Request, vehicle_id: int):
    denied = _sales_access_denied(request)
    if denied:
        return denied
    user_id = int(base_router.get_web_user_id(request))
    form = await request.form()
    audience = str(form.get("audience") or "retail")
    if audience not in PUBLICATION_AUDIENCE_LABELS:
        audience = "retail"
    visibility = str(form.get("visibility") or "")
    if visibility not in PORTAL_VISIBILITY_LABELS:
        visibility = "authenticated_trade" if audience == "trade" else "public_link"
    expires_on = date_value(form.get("expires_on"))
    selected_ids: set[int] = set()
    for raw_id in form.getlist("image_ids"):
        try:
            selected_ids.add(int(str(raw_id)))
        except ValueError:
            continue
    selected_organization_ids: set[int] = set()
    for raw_id in form.getlist("organization_ids"):
        try:
            selected_organization_ids.add(int(str(raw_id)))
        except ValueError:
            continue
    with base_router.SessionLocal() as db:
        vehicle = db.get(Vehicle, vehicle_id)
        if not vehicle:
            return RedirectResponse("/v2-clean/fleet/sales", status_code=303)
        profile = _get_or_create_profile(db, vehicle)
        snapshot = base_router.latest_vehicle_snapshot(db, vehicle.id)
        manual = base_router.vehicle_manual_values(db, vehicle.id)
        row = _sale_row(
            vehicle,
            snapshot,
            manual,
            profile,
            _active_financial_plan(db, vehicle.id),
        )
        allowed_image_ids = set(
            db.scalars(
                select(VehicleImage.id).where(
                    VehicleImage.vehicle_id == vehicle.id,
                    VehicleImage.active.is_(True),
                    VehicleImage.id.in_(selected_ids or {-1}),
                )
            ).all()
        )
        allowed_organization_ids = set(
            db.scalars(
                select(PortalOrganization.id).where(
                    PortalOrganization.id.in_(
                        selected_organization_ids or {-1}
                    ),
                    PortalOrganization.status == "active",
                )
            ).all()
        )
        if visibility != "selected_organizations":
            allowed_organization_ids = set()
        if visibility == "selected_organizations" and not allowed_organization_ids:
            return RedirectResponse(
                f"/v2-clean/fleet/sales/{vehicle_id}?error=publication_organizations",
                status_code=303,
            )
        publication = VehicleSalePublication(
            vehicle_id=vehicle.id,
            token=secrets.token_urlsafe(18),
            audience=audience,
            visibility=visibility,
            status="published",
            snapshot_json=_public_snapshot(vehicle, profile, row, audience),
            selected_image_ids_json=sorted(allowed_image_ids),
            expires_on=expires_on,
            created_by_id=user_id,
            view_count=0,
        )
        db.add(publication)
        db.flush()
        for organization_id in sorted(allowed_organization_ids):
            db.add(
                PortalPublicationAccess(
                    publication_id=publication.id,
                    organization_id=organization_id,
                    created_by_id=user_id,
                )
            )
        record_audit(
            db,
            action="vehicle.sale.published",
            entity_type="vehicle_sale_publication",
            entity_id=publication.id,
            detail=f"Relatório externo publicado para {vehicle.plate or vehicle.id}",
            after_json={
                "vehicle_id": vehicle.id,
                "audience": audience,
                "visibility": visibility,
                "organization_ids": sorted(allowed_organization_ids),
                "expires_on": expires_on.isoformat() if expires_on else None,
                "image_count": len(allowed_image_ids),
            },
            user_id=user_id,
        )
        db.commit()
    return RedirectResponse(f"/v2-clean/fleet/sales/{vehicle_id}?saved=published", status_code=303)


@vehicle_sales_router.post(
    "/v2-clean/fleet/sales/{vehicle_id}/publications/{publication_id}/revoke"
)
def vehicle_sale_publication_revoke(
    request: Request,
    vehicle_id: int,
    publication_id: int,
):
    denied = _sales_access_denied(request)
    if denied:
        return denied
    user_id = int(base_router.get_web_user_id(request))
    with base_router.SessionLocal() as db:
        publication = db.get(VehicleSalePublication, publication_id)
        if (
            publication
            and publication.vehicle_id == vehicle_id
            and publication.status == "published"
        ):
            publication.status = "revoked"
            publication.revoked_at = datetime.now(UTC)
            record_audit(
                db,
                action="vehicle.sale.publication_revoked",
                entity_type="vehicle_sale_publication",
                entity_id=publication.id,
                detail=f"Link externo revogado para a viatura {vehicle_id}",
                before_json={"status": "published"},
                after_json={"status": "revoked"},
                user_id=user_id,
            )
            db.commit()
    return RedirectResponse(f"/v2-clean/fleet/sales/{vehicle_id}?saved=revoked", status_code=303)


def _publication_is_available(publication: VehicleSalePublication | None) -> bool:
    return bool(
        publication
        and publication.status == "published"
        and (not publication.expires_on or publication.expires_on >= date.today())
    )


def _portal_lead_kinds(context) -> list[tuple[str, str]]:
    if not context:
        return list(LEAD_KINDS)
    permission_by_kind = {
        "question": "vehicles.questions.create",
        "offer": "offers.create",
        "purchase": "purchase_requests.create",
    }
    return [
        (code, label)
        for code, label in LEAD_KINDS
        if context.has(permission_by_kind[code])
    ]


@vehicle_sales_router.get("/portal/viaturas/{token}", response_class=HTMLResponse)
def public_vehicle_sale(
    request: Request,
    token: str,
    sent: str = "",
    ref: str = "",
    error: str = "",
):
    with base_router.SessionLocal() as db:
        publication = db.scalar(
            select(VehicleSalePublication).where(VehicleSalePublication.token == token)
        )
        if not _publication_is_available(publication):
            return base_router.templates.TemplateResponse(
                request,
                "public_vehicle_sale_unavailable.html",
                status_code=410,
            )
        context, allowed = _publication_request_context(request, db, publication)
        if not allowed:
            if not context:
                destination = quote(f"/portal/viaturas/{token}", safe="")
                return RedirectResponse(
                    f"/portal/entrar?next={destination}", status_code=303
                )
            return base_router.templates.TemplateResponse(
                request,
                "portal_forbidden.html",
                {
                    "portal_context": context,
                    "csrf_token": portal_csrf_token(request),
                },
                status_code=403,
            )
        now = datetime.now(UTC)
        publication.view_count = (publication.view_count or 0) + 1
        publication.first_viewed_at = publication.first_viewed_at or now
        publication.last_viewed_at = now
        db.commit()
        if context:
            db.refresh(context.user)
            db.refresh(context.organization)
        selected_ids = [
            int(value)
            for value in (publication.selected_image_ids_json or [])
            if str(value).isdigit()
        ]
        images = (
            db.scalars(
                select(VehicleImage)
                .where(
                    VehicleImage.id.in_(selected_ids),
                    VehicleImage.vehicle_id == publication.vehicle_id,
                )
                .order_by(VehicleImage.sort_order.asc(), VehicleImage.id.asc())
            ).all()
            if selected_ids
            else []
        )
        snapshot = dict(publication.snapshot_json or {})
    error_messages = {
        "required": "Indica o nome, um contacto e a informação necessária para este pedido.",
        "consent": "Confirma que podemos usar os dados enviados para tratar o pedido.",
        "offer": "Indica um valor de proposta válido.",
        "rate_limit": (
            "Foram enviados vários pedidos recentemente. "
            "Tenta novamente dentro de alguns minutos."
        ),
        "spam": "Não foi possível registar o pedido.",
        "forbidden_action": "O seu perfil não permite realizar esta ação.",
        "csrf": "A sessão expirou. Atualiza a página e tenta novamente.",
    }
    return base_router.templates.TemplateResponse(
        request,
        "public_vehicle_sale.html",
        {
            "publication": publication,
            "snapshot": snapshot,
            "images": images,
            "lead_kinds": _portal_lead_kinds(context),
            "portal_context": context,
            "csrf_token": portal_csrf_token(request),
            "sent": sent == "1",
            "reference": ref,
            "error": error_messages.get(error),
            "money": money,
        },
    )


@vehicle_sales_router.get("/portal/viaturas/{token}/imagens/{image_id}")
def public_vehicle_sale_image(request: Request, token: str, image_id: int):
    with base_router.SessionLocal() as db:
        publication = db.scalar(
            select(VehicleSalePublication).where(VehicleSalePublication.token == token)
        )
        if not _publication_is_available(publication):
            return HTMLResponse("Imagem não disponível.", status_code=404)
        _context, allowed = _publication_request_context(request, db, publication)
        if not allowed:
            return HTMLResponse("Imagem não disponível.", status_code=404)
        selected_ids = {
            int(value)
            for value in (publication.selected_image_ids_json or [])
            if str(value).isdigit()
        }
        if image_id not in selected_ids:
            return HTMLResponse("Imagem não disponível.", status_code=404)
        image = db.get(VehicleImage, image_id)
        if not image or image.vehicle_id != publication.vehicle_id:
            return HTMLResponse("Imagem não disponível.", status_code=404)
        path = _resolved_image_path(image)
        if not path:
            return HTMLResponse("Imagem não disponível.", status_code=404)
        return FileResponse(
            path,
            media_type=image.content_type,
            headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"},
        )


def _source_fingerprint(request: Request) -> str:
    client = request.client.host if request.client else ""
    user_agent = request.headers.get("user-agent", "")
    source = f"{client}|{user_agent}|{settings.app_secret_key}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


@vehicle_sales_router.post("/portal/viaturas/{token}/interesse")
def public_vehicle_sale_interest(
    request: Request,
    token: str,
    kind: str = Form("question"),
    name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    buyer_company: str = Form(""),
    offer_value: str = Form(""),
    message: str = Form(""),
    consent: str = Form(""),
    company: str = Form(""),
    csrf_token: str = Form(""),
):
    if company.strip():
        return RedirectResponse(f"/portal/viaturas/{token}?error=spam", status_code=303)
    if not base_router.external_portal_rate_limit_allows(base_router.external_client_key(request)):
        return RedirectResponse(f"/portal/viaturas/{token}?error=rate_limit", status_code=303)
    if not consent:
        return RedirectResponse(f"/portal/viaturas/{token}?error=consent", status_code=303)
    with base_router.SessionLocal() as db:
        publication = db.scalar(
            select(VehicleSalePublication).where(VehicleSalePublication.token == token)
        )
        if not _publication_is_available(publication):
            return RedirectResponse(f"/portal/viaturas/{token}", status_code=303)
        context, allowed = _publication_request_context(request, db, publication)
        if not allowed:
            if not context:
                destination = quote(f"/portal/viaturas/{token}", safe="")
                return RedirectResponse(
                    f"/portal/entrar?next={destination}", status_code=303
                )
            return RedirectResponse(
                f"/portal/viaturas/{token}?error=forbidden_action", status_code=303
            )
        clean_kind = kind if kind in LEAD_KIND_LABELS else "question"
        required_permission = {
            "question": "vehicles.questions.create",
            "offer": "offers.create",
            "purchase": "purchase_requests.create",
        }[clean_kind]
        if context and not context.has(required_permission):
            return RedirectResponse(
                f"/portal/viaturas/{token}?error=forbidden_action", status_code=303
            )
        if context and not valid_portal_csrf(request, csrf_token):
            return RedirectResponse(
                f"/portal/viaturas/{token}?error=csrf", status_code=303
            )
        clean_name = context.user.name if context else name.strip()
        clean_email = context.user.email if context else email.strip().lower()
        clean_phone = phone.strip()
        clean_company = (
            context.organization.name if context else buyer_company.strip()
        )
        clean_message = message.strip()
        parsed_offer = decimal_value(offer_value)
        if not clean_name or not (clean_email or clean_phone):
            return RedirectResponse(
                f"/portal/viaturas/{token}?error=required", status_code=303
            )
        if clean_kind == "question" and not clean_message:
            return RedirectResponse(
                f"/portal/viaturas/{token}?error=required", status_code=303
            )
        if clean_kind == "offer" and (parsed_offer is None or parsed_offer <= 0):
            return RedirectResponse(
                f"/portal/viaturas/{token}?error=offer", status_code=303
            )
        lead = VehicleSaleLead(
            publication_id=publication.id,
            vehicle_id=publication.vehicle_id,
            kind=clean_kind,
            status="new",
            name=clean_name[:200],
            email=clean_email[:255] or None,
            phone=clean_phone[:80] or None,
            company=clean_company[:200] or None,
            offer_value=parsed_offer if clean_kind == "offer" else None,
            message=clean_message[:5000] or None,
            source_fingerprint=_source_fingerprint(request),
            portal_user_id=context.user.id if context else None,
            portal_organization_id=context.organization.id if context else None,
        )
        db.add(lead)
        db.flush()
        record_audit(
            db,
            action="vehicle.sale.lead_created",
            entity_type="vehicle_sale_lead",
            entity_id=lead.id,
            detail=f"{LEAD_KIND_LABELS[clean_kind]} recebida no portal de venda",
            after_json={
                "publication_id": publication.id,
                "vehicle_id": publication.vehicle_id,
                "kind": clean_kind,
                "portal_user_id": context.user.id if context else None,
                "portal_organization_id": context.organization.id if context else None,
            },
            user_id=None,
        )
        db.commit()
        reference = f"CF-VENDA-{lead.id:05d}"
    return RedirectResponse(
        f"/portal/viaturas/{token}?" + urlencode({"sent": "1", "ref": reference}),
        status_code=303,
    )


@vehicle_sales_router.post("/v2-clean/fleet/sales/{vehicle_id}/leads/{lead_id}")
def vehicle_sale_lead_update(
    request: Request,
    vehicle_id: int,
    lead_id: int,
    status: str = Form("in_review"),
):
    denied = _sales_access_denied(request)
    if denied:
        return denied
    user_id = int(base_router.get_web_user_id(request))
    normalized_status = status if status in LEAD_STATUS_LABELS else "in_review"
    with base_router.SessionLocal() as db:
        lead = db.get(VehicleSaleLead, lead_id)
        if lead and lead.vehicle_id == vehicle_id:
            before_status = lead.status
            lead.status = normalized_status
            lead.updated_by_id = user_id
            record_audit(
                db,
                action="vehicle.sale.lead_status_updated",
                entity_type="vehicle_sale_lead",
                entity_id=lead.id,
                detail=(
                    "Estado da oportunidade atualizado para "
                    f"{LEAD_STATUS_LABELS[normalized_status]}"
                ),
                before_json={"status": before_status},
                after_json={"status": normalized_status},
                user_id=user_id,
            )
            db.commit()
    return RedirectResponse(f"/v2-clean/fleet/sales/{vehicle_id}?saved=lead", status_code=303)
