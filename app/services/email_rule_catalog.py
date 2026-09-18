"""Installation-neutral catalogue for reviewed inbox-rule presets.

Presets are deliberately not inserted by migrations: channel and classification IDs
are installation data. Administrators must map, preview and explicitly activate them.
"""

REVIEWED_EMAIL_RULE_PRESETS: tuple[dict, ...] = (
    {
        "code": "finance_document_intake",
        "channel": "departamento_financeiro",
        "recipient_alias": "faturas@carfast.pt (mapear alias real; não ativado)",
        "subjects": ("Qualquer assunto apenas desse alias",),
        "match_type": "any",
        "auto_task_mode": "none",
        "status_action": "resolved",
        "deterministic": True,
        "notes": "Resolvido significa apenas email fechado após guardar os anexos. Não extrai, classifica ou trata fiscalmente documentos; não cria alerta de desconhecidos nem copia para SharePoint/OneDrive.",
    },
    {
        "code": "support_newsletter_subscriber",
        "channel": "support",
        "subjects": ("Novo Subscritor à Newsletter",),
        "auto_task_mode": "none",
        "status_action": "archived",
        "deterministic": True,
    },
    {
        "code": "vvp_success_notifications",
        "channel": "vvp",
        "subjects": (
            "processamento concluído",
            "autorização",
            "cancelamento de pré-autorização",
            "MERF",
        ),
        "auto_task_mode": "none",
        "status_action": "archived",
        "deterministic": True,
    },
    {
        "code": "reports_rentway",
        "channel": "reports",
        "subjects": (
            "NEW WEBSERVICE RESERVATION",
            "WEBSERVICE RESERVATION CANCELATION",
            "MT Rental Agreement Renewal",
            "Webservices Report Carfast",
            "Express Checkout Reports",
        ),
        "auto_task_mode": "none",
        "status_action": "archived",
        "deterministic": True,
    },
    {
        "code": "controlled_tests",
        "channel": None,
        "subjects": ("CF-E2E", "CF-SCHED", "Teste CarFast 365"),
        "auto_task_mode": "none",
        "status_action": "archived",
        "deterministic": True,
    },
    {
        "code": "support_undeliverable",
        "channel": "support",
        "subjects": ("Undeliverable",),
        "auto_task_mode": "none",
        "status_action": "in_progress",
        "deterministic": True,
    },
    {
        "code": "vvp_token_charge_error",
        "channel": "vvp",
        "subjects": ("Error processing Token charges",),
        "auto_task_mode": "open",
        "status_action": "in_progress",
        "deterministic": True,
    },
    {
        "code": "finance_statements",
        "channel": "finance",
        "subjects": ("extrato de transações", "relatório mensal"),
        "auto_task_mode": "none",
        "status_action": "in_progress",
        "deterministic": False,
        "attachment_document_type": "financial",
    },
)
