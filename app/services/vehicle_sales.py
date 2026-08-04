import re
from datetime import date, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation

SALE_STATUSES = [
    ("candidate", "Candidata"),
    ("for_sale", "Para venda"),
    ("do_not_sell", "Não vender"),
    ("reserved", "Reservada"),
    ("sold", "Vendida"),
    ("delivered", "Entregue"),
]
SALE_STATUS_LABELS = dict(SALE_STATUSES)

VEHICLE_SALE_STATES = [
    ("free", "Livre"),
    ("impro", "IMPRO"),
    ("contract", "Contrato"),
]
VEHICLE_SALE_STATE_LABELS = dict(VEHICLE_SALE_STATES)

IMAGE_CATEGORIES = [
    ("exterior", "Exterior"),
    ("interior", "Interior"),
    ("damage", "Danos"),
    ("equipment", "Equipamento"),
    ("other", "Outras"),
]
IMAGE_CATEGORY_LABELS = dict(IMAGE_CATEGORIES)

PUBLICATION_AUDIENCES = [
    ("trade", "Comércio"),
    ("retail", "Cliente final"),
]
PUBLICATION_AUDIENCE_LABELS = dict(PUBLICATION_AUDIENCES)

LEAD_KINDS = [
    ("question", "Questão"),
    ("offer", "Proposta"),
    ("purchase", "Pedido de compra"),
]
LEAD_KIND_LABELS = dict(LEAD_KINDS)

LEAD_STATUSES = [
    ("new", "Nova"),
    ("in_review", "Em análise"),
    ("contacted", "Contactado"),
    ("counter_offer", "Contraproposta"),
    ("accepted", "Aceite"),
    ("rejected", "Recusada"),
    ("completed", "Concluída"),
]
LEAD_STATUS_LABELS = dict(LEAD_STATUSES)

PRICE_BASES = [
    ("cost", "Valor de custo"),
    ("trade", "Valor comércio"),
    ("retail", "Valor cliente final"),
]
PRICE_BASE_LABELS = dict(PRICE_BASES)

MARGIN_MODES = [
    ("value", "Valor"),
    ("percentage", "Percentagem"),
]
MARGIN_MODE_LABELS = dict(MARGIN_MODES)

ROUNDING_MODES = [
    ("none", "Sem arredondamento"),
    ("nearest", "Ao múltiplo mais próximo"),
    ("up", "Para cima"),
    ("down", "Para baixo"),
]
ROUNDING_MODE_LABELS = dict(ROUNDING_MODES)


def decimal_value(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).strip().replace(" ", "").replace("\u00a0", "")
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    text = re.sub(r"[^0-9.\-]", "", text)
    if not text:
        return None
    try:
        return Decimal(text).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def date_value(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def money(value: object) -> str:
    parsed = decimal_value(value)
    if parsed is None:
        return "-"
    return f"{parsed:,.2f} €".replace(",", " ").replace(".", ",")


def margin(
    cost: object, comparison: object, *, comparison_minus_cost: bool = False
) -> Decimal | None:
    parsed_cost = decimal_value(cost)
    parsed_comparison = decimal_value(comparison)
    if parsed_cost is None or parsed_comparison is None:
        return None
    result = (
        parsed_comparison - parsed_cost
        if comparison_minus_cost
        else parsed_cost - parsed_comparison
    )
    return result.quantize(Decimal("0.01"))


def calculate_selling_price(
    base_value: object,
    margin_mode: str,
    margin_value: object,
    rounding_mode: str = "none",
    rounding_increment: object = None,
) -> Decimal | None:
    base = decimal_value(base_value)
    adjustment = decimal_value(margin_value)
    if base is None or adjustment is None:
        return None
    if margin_mode == "percentage":
        calculated = base * (Decimal("1") + adjustment / Decimal("100"))
    else:
        calculated = base + adjustment
    increment = decimal_value(rounding_increment)
    if rounding_mode != "none" and increment and increment > 0:
        quotient = calculated / increment
        rounding = {
            "up": ROUND_CEILING,
            "down": ROUND_FLOOR,
            "nearest": ROUND_HALF_UP,
        }.get(rounding_mode, ROUND_HALF_UP)
        calculated = quotient.quantize(Decimal("1"), rounding=rounding) * increment
    return max(Decimal("0"), calculated).quantize(Decimal("0.01"))


def masked_plate(value: str | None) -> str:
    compact = re.sub(r"[^A-Za-z0-9]", "", value or "").upper()
    if len(compact) < 5:
        return compact or "-"
    return f"{compact[:2]}-**-{compact[-2:]}"
