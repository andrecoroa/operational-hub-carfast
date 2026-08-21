import importlib.util
from io import StringIO
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models.admin import Permission, Role, RolePermission
from app.models.email import EmailChannel, EmailMessage, EmailTemplate
from app.models.stock import StockArticleSupplierRef, StockSupplier
from app.models.suppliers import SupplierType, SupplierTypeAssignment
from app.services.supplier_email_templates import (
    email_template_snapshot,
    ranked_supplier_email_templates,
)
from app.services.users import create_user


def test_stock_supplier_is_the_transversal_entity_without_copying_relations(db_session):
    supplier = StockSupplier(name="Peças Seguras", tax_id="PT509000001", active=True)
    db_session.add(supplier)
    db_session.flush()
    stock_type = db_session.scalar(select(SupplierType).where(SupplierType.code == "stock"))
    workshop_type = db_session.scalar(select(SupplierType).where(SupplierType.code == "workshop"))
    assert stock_type is not None and workshop_type is not None
    db_session.add_all(
        [
            SupplierTypeAssignment(
                supplier_id=supplier.id, supplier_type_id=stock_type.id
            ),
            SupplierTypeAssignment(
                supplier_id=supplier.id, supplier_type_id=workshop_type.id
            ),
        ]
    )
    db_session.commit()

    assert db_session.get(StockSupplier, supplier.id).tax_id == "PT509000001"
    assert {
        item.supplier_type_id
        for item in db_session.scalars(
            select(SupplierTypeAssignment).where(
                SupplierTypeAssignment.supplier_id == supplier.id
            )
        )
    } == {stock_type.id, workshop_type.id}
    assert (
        next(iter(StockArticleSupplierRef.__table__.c.supplier_id.foreign_keys)).target_fullname
        == "stock_suppliers.id"
    )


def test_supplier_template_fallback_prefers_supplier_then_type_then_module(db_session):
    supplier = StockSupplier(name="Oficina Externa", email="oficina@example.pt", active=True)
    db_session.add(supplier)
    db_session.flush()
    workshop_type = db_session.scalar(select(SupplierType).where(SupplierType.code == "workshop"))
    stock_type = db_session.scalar(select(SupplierType).where(SupplierType.code == "stock"))
    assert workshop_type is not None and stock_type is not None
    templates = [
        EmailTemplate(code="global", name="Global", body_template="G", version=1, active=True),
        EmailTemplate(code="module", name="Módulo", body_template="M", version=1, active=True, module_code="workshop"),
        EmailTemplate(code="type", name="Tipo", body_template="T", version=1, active=True, supplier_type_id=workshop_type.id),
        EmailTemplate(code="supplier", name="Fornecedor", body_template="F", version=1, active=True, supplier_id=supplier.id),
        EmailTemplate(code="wrong_type", name="Stock", body_template="S", version=1, active=True, supplier_type_id=stock_type.id),
        EmailTemplate(code="inactive", name="Inativo", body_template="I", version=1, active=False, supplier_id=supplier.id),
    ]
    db_session.add_all(templates)
    db_session.commit()

    ranked = ranked_supplier_email_templates(
        db_session,
        supplier_id=supplier.id,
        supplier_type_ids={workshop_type.id},
        module_code="workshop",
    )
    assert [item.code for item in ranked] == ["supplier", "type", "module", "global"]


def test_email_snapshot_keeps_full_template_even_after_template_changes(db_session):
    template = EmailTemplate(
        code="quote",
        name="Pedido de orçamento",
        subject_template="Orçamento {{subject}}",
        body_template="Boa tarde",
        version=3,
        allowed_variables_json=["subject"],
        module_code="workshop",
        context_code="quote_request",
        active=True,
    )
    db_session.add(template)
    db_session.flush()
    snapshot = email_template_snapshot(
        template,
        rendered_subject="Orçamento travões",
        rendered_body="Boa tarde",
    )
    message = EmailMessage(
        thread_id=1,
        direction="outbound",
        state="draft",
        sender="oficina@carfast.pt",
        subject="Orçamento travões",
        text_body="Boa tarde",
        template_id=template.id,
        template_version=template.version,
        template_snapshot_json=snapshot,
    )
    template.body_template = "Conteúdo alterado"
    template.version = 4

    assert message.template_snapshot_json["body_template"] == "Boa tarde"
    assert message.template_snapshot_json["version"] == 3
    assert message.template_snapshot_json["rendered_subject"] == "Orçamento travões"


def test_supplier_pages_and_separate_read_write_permissions(client, db_session):
    read_permission = db_session.scalar(
        select(Permission).where(Permission.code == "suppliers.read")
    )
    role = Role(code="supplier_reader", name="Consulta de fornecedores", active=True)
    db_session.add(role)
    db_session.flush()
    db_session.add(RolePermission(role_id=role.id, permission_id=read_permission.id))
    user = create_user(
        db_session,
        name="Leitor de fornecedores",
        email="supplier.reader@carfast.local",
        password="Secret123!",
        role_codes=[role.code],
    )
    db_session.commit()
    login = client.post(
        "/login",
        data={"email": user.email, "password": "Secret123!"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    client.post("/change-notice", data={"next_url": "/v2-clean/suppliers"})

    page = client.get("/v2-clean/suppliers")
    assert page.status_code == 200
    assert "Entidade transversal" in page.text
    assert "Novo fornecedor" not in page.text
    denied = client.post(
        "/v2-clean/suppliers", data={"name": "Não autorizado"}, follow_redirects=False
    )
    assert denied.status_code == 303
    assert denied.headers["location"] == "/v2-clean?error=forbidden"


def test_inactive_supplier_type_assignment_survives_supplier_edit(
    authenticated_client, db_session
):
    supplier_type = SupplierType(
        code="legacy_subtype",
        name="Subtipo legado",
        module_code="workshop",
        active=False,
        sort_order=200,
    )
    supplier = StockSupplier(name="Fornecedor legado", active=True)
    db_session.add_all([supplier_type, supplier])
    db_session.flush()
    db_session.add(
        SupplierTypeAssignment(
            supplier_id=supplier.id, supplier_type_id=supplier_type.id
        )
    )
    db_session.commit()

    response = authenticated_client.post(
        f"/v2-clean/suppliers/{supplier.id}",
        data={"name": supplier.name, "active": "on", "country_code": "PT"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert db_session.scalar(
        select(SupplierTypeAssignment).where(
            SupplierTypeAssignment.supplier_id == supplier.id,
            SupplierTypeAssignment.supplier_type_id == supplier_type.id,
        )
    ) is not None


def test_admin_can_create_and_render_general_supplier(authenticated_client, db_session):
    workshop_type = db_session.scalar(select(SupplierType).where(SupplierType.code == "workshop"))
    response = authenticated_client.post(
        "/v2-clean/suppliers",
        data={
            "name": "Rede Oficina",
            "legal_name": "Rede Oficina, Lda.",
            "tax_id": "PT509000099",
            "email": "rede@example.pt",
            "phone": "+351 210 000 000",
            "type_ids": [str(workshop_type.id)],
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    supplier = db_session.scalar(
        select(StockSupplier).where(StockSupplier.tax_id == "PT509000099")
    )
    assert supplier is not None
    detail = authenticated_client.get(f"/v2-clean/suppliers/{supplier.id}")
    assert detail.status_code == 200
    assert "Histórico preservado" in detail.text
    assert "Oficina" in detail.text
    admin = authenticated_client.get("/v2-clean/admin/suppliers")
    assert admin.status_code == 200
    assert "Tipos e modelos de email" in admin.text


def test_supplier_compose_uses_existing_email_permissions_and_persists_snapshot(
    authenticated_client, db_session, monkeypatch
):
    import app.web.email as email_web

    testing_session = sessionmaker(bind=db_session.bind, autoflush=False, autocommit=False)
    monkeypatch.setattr(email_web, "SessionLocal", testing_session)
    supplier = StockSupplier(
        name="Fornecedor Email",
        email="fornecedor@example.pt",
        active=True,
    )
    workshop_type = db_session.scalar(
        select(SupplierType).where(SupplierType.code == "workshop")
    )
    channel = db_session.scalar(select(EmailChannel).where(EmailChannel.active.is_(True)))
    db_session.add(supplier)
    db_session.flush()
    db_session.add(
        SupplierTypeAssignment(
            supplier_id=supplier.id, supplier_type_id=workshop_type.id
        )
    )
    template = EmailTemplate(
        code="supplier_quote",
        name="Pedido específico",
        subject_template="Pedido de orçamento",
        body_template="Solicitamos orçamento.",
        version=2,
        allowed_variables_json=[],
        supplier_id=supplier.id,
        module_code="workshop",
        active=True,
    )
    db_session.add(template)
    db_session.commit()

    compose = authenticated_client.get(
        f"/v2-clean/email?supplier_id={supplier.id}&module_code=workshop&compose=1"
    )
    assert compose.status_code == 200
    assert "Fornecedor Email" in compose.text
    assert "Pedido específico · fornecedor" in compose.text

    response = authenticated_client.post(
        "/v2-clean/email/new",
        data={
            "channel_id": str(channel.id),
            "recipients": supplier.email,
            "cc": "compras@carfast.pt",
            "subject": "Pedido revisto pelo utilizador",
            "body": "Corpo revisto antes de guardar.",
            "template_id": str(template.id),
            "supplier_id": str(supplier.id),
            "supplier_type_id": str(workshop_type.id),
            "module_code": "workshop",
            "context_code": "",
            "submit": "draft",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    db_session.expire_all()
    message = db_session.scalar(
        select(EmailMessage)
        .where(EmailMessage.supplier_id == supplier.id)
        .order_by(EmailMessage.id.desc())
    )
    assert message is not None
    assert message.state == "draft"
    assert message.cc_json == [{"Email": "compras@carfast.pt"}]
    assert message.subject == "Pedido revisto pelo utilizador"
    assert message.text_body == "Corpo revisto antes de guardar."
    assert message.template_snapshot_json["body_template"] == "Solicitamos orçamento."
    assert message.template_snapshot_json["rendered_body"] == "Corpo revisto antes de guardar."
    assert message.context_module == "workshop"


def test_supplier_migration_is_additive_and_single_head():
    migration = Path(
        "migrations/versions/fff26e7f8a9c_add_transversal_suppliers_and_email_templates.py"
    ).read_text(encoding="utf-8")
    assert 'down_revision: str | Sequence[str] | None = "fff15d6e7f8b"' in migration
    assert 'op.add_column("stock_suppliers"' in migration
    assert "DROP TABLE stock_suppliers" not in migration.upper()
    assert "supplier_type_assignments" in migration
    assert "template_snapshot_json" not in migration  # existing history column is preserved


def test_supplier_migration_upgrade_compiles_for_postgresql():
    path = Path(
        "migrations/versions/fff26e7f8a9c_add_transversal_suppliers_and_email_templates.py"
    )
    spec = importlib.util.spec_from_file_location("supplier_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    module.op = Operations(context)
    module.upgrade()
    sql = output.getvalue()

    assert "CREATE TABLE supplier_types" in sql
    assert "ALTER TABLE stock_suppliers ADD COLUMN" in sql
    assert "INSERT INTO supplier_type_assignments" in sql
    assert "DROP TABLE stock_suppliers" not in sql
