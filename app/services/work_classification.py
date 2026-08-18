from __future__ import annotations

CONTENT_TYPES = {
    "message": "Mensagem / informação",
    "document": "Documento para tratar",
    "request": "Pedido",
    "complaint": "Reclamação",
    "incident": "Anomalia / incidente",
    "other": "Outro",
}

WORK_NATURES = {
    "operational": "Operacional",
    "stock": "Stock",
    "financial": "Financeira",
    "workshop": "Oficina",
    "fleet": "Frota",
    "audit": "Auditoria",
    "administration": "Administração",
    "other": "Outra",
}

DOCUMENT_TYPES = {
    "invoice": "Fatura",
    "credit_note": "Nota de crédito",
    "quote": "Orçamento",
    "work_order": "Folha de obra",
    "contract": "Contrato",
    "receipt": "Recibo / comprovativo",
    "report": "Relatório",
    "vehicle_document": "Documento de viatura",
    "other": "Outro documento",
}

ATTACHMENT_STATUSES = {
    "pending": "Por tratar",
    "classified": "Classificado",
    "routed": "Encaminhado",
    "associated": "Associado",
    "ignored": "Sem tratamento",
}

TASK_DESTINATION = {
    "operational": ("operational_task", "operations"),
    "stock": ("operational_task", "stock"),
    "financial": ("administration_task", "finance"),
    "workshop": ("workshop_task", "workshop"),
    "fleet": ("operational_task", "fleet"),
    "audit": ("audit_task", "documents"),
    "administration": ("administration_task", "administration"),
    "other": ("operational_task", "other"),
}


def task_classification(nature: str | None) -> tuple[str, str]:
    return TASK_DESTINATION.get(nature or "", TASK_DESTINATION["operational"])


def thread_reference(thread) -> str:
    year = (
        (thread.created_at or thread.last_message_at).year
        if (thread.created_at or thread.last_message_at)
        else 0
    )
    return f"EM-{year:04d}-{thread.id:06d}"


def message_reference(thread, position: int) -> str:
    return f"{thread_reference(thread)}.{position:02d}"


def attachment_reference(thread, message_position: int, attachment_position: int) -> str:
    return f"{message_reference(thread, message_position)}-A{attachment_position:02d}"
