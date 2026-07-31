import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PortalOrganization, PortalPublicationAccess, PortalUser

PORTAL_PERMISSION_CATALOG = (
    ("portal.access", "Aceder ao portal"),
    ("vehicles.catalog.view", "Consultar catálogo de viaturas"),
    ("vehicles.trade_price.view", "Ver valor para comércio"),
    ("vehicles.retail_price.view", "Ver valor de cliente final"),
    ("vehicle_reports.download", "Consultar relatórios comerciais"),
    ("vehicles.questions.create", "Colocar questões sobre viaturas"),
    ("offers.create", "Apresentar propostas"),
    ("offers.view_organization", "Ver interações da empresa"),
    ("purchase_requests.create", "Registar pedidos de compra"),
    ("support_requests.create", "Registar pedidos gerais"),
)
PORTAL_PERMISSION_CODES = {code for code, _label in PORTAL_PERMISSION_CATALOG}
DEFAULT_TRADE_PERMISSIONS = {
    "portal.access",
    "vehicles.catalog.view",
    "vehicles.trade_price.view",
    "vehicle_reports.download",
    "vehicles.questions.create",
    "offers.create",
    "offers.view_organization",
    "purchase_requests.create",
    "support_requests.create",
}
PORTAL_VISIBILITIES = (
    ("public_link", "Link público"),
    ("authenticated_trade", "Comerciantes autenticados"),
    ("selected_organizations", "Entidades selecionadas"),
)
PORTAL_VISIBILITY_LABELS = dict(PORTAL_VISIBILITIES)


@dataclass(frozen=True)
class PortalContext:
    user: PortalUser
    organization: PortalOrganization
    permissions: frozenset[str]

    def has(self, *codes: str) -> bool:
        return bool(self.permissions.intersection(codes))


def normalize_portal_permissions(values) -> list[str]:
    return sorted({str(value) for value in values if str(value) in PORTAL_PERMISSION_CODES})


def invitation_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_invitation_token() -> str:
    return secrets.token_urlsafe(32)


def portal_csrf_token(request: Request) -> str:
    current = str(request.session.get("portal_csrf_token") or "")
    if current:
        return current
    current = secrets.token_urlsafe(24)
    request.session["portal_csrf_token"] = current
    return current


def valid_portal_csrf(request: Request, submitted: str) -> bool:
    expected = str(request.session.get("portal_csrf_token") or "")
    return bool(expected and submitted and hmac.compare_digest(expected, submitted))


def portal_context(request: Request, db: Session) -> PortalContext | None:
    raw_user_id = request.session.get("portal_user_id")
    raw_organization_id = request.session.get("portal_organization_id")
    if not raw_user_id or not raw_organization_id:
        return None
    try:
        user_id = int(raw_user_id)
        organization_id = int(raw_organization_id)
    except (TypeError, ValueError):
        clear_portal_session(request)
        return None
    user = db.get(PortalUser, user_id)
    organization = db.get(PortalOrganization, organization_id)
    if (
        not user
        or not user.active
        or not organization
        or organization.status != "active"
        or user.organization_id != organization.id
    ):
        clear_portal_session(request)
        return None
    permissions = frozenset(normalize_portal_permissions(user.permissions_json or []))
    if "portal.access" not in permissions:
        clear_portal_session(request)
        return None
    return PortalContext(user=user, organization=organization, permissions=permissions)


def clear_portal_session(request: Request) -> None:
    request.session.pop("portal_user_id", None)
    request.session.pop("portal_organization_id", None)


def publication_allowed_for_portal(
    db: Session,
    publication,
    context: PortalContext | None,
) -> bool:
    visibility = str(getattr(publication, "visibility", None) or "public_link")
    if visibility == "public_link":
        return True
    if not context or not context.has("vehicles.catalog.view"):
        return False
    if visibility == "authenticated_trade":
        return True
    if visibility != "selected_organizations":
        return False
    return (
        db.scalar(
            select(PortalPublicationAccess.id).where(
                PortalPublicationAccess.publication_id == publication.id,
                PortalPublicationAccess.organization_id == context.organization.id,
            )
        )
        is not None
    )


def utc_datetime(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)
