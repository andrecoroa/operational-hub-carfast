WORKSHOP_PROCESS_TYPE_PHASED = "workshop_phased"

WORKSHOP_CREATION_MODES = [
    {"code": "immediate_entry", "label": "Entrada imediata"},
    {"code": "appointment", "label": "Marcacao"},
]

WORKSHOP_SERVICE_OPTIONS = [
    {"code": "revision_maintenance", "label": "Revisao / Manutencao"},
    {"code": "tires", "label": "Pneus"},
    {"code": "brakes", "label": "Travoes"},
    {"code": "dashboard_warning", "label": "Luz / avaria no painel"},
    {"code": "battery", "label": "Bateria"},
    {"code": "mechanics", "label": "Mecanica"},
    {"code": "body_paint", "label": "Chapa / pintura"},
    {"code": "damage", "label": "Danos"},
    {"code": "warranty", "label": "Garantia"},
    {"code": "sale_preparation", "label": "Preparacao para venda"},
    {"code": "other", "label": "Outro"},
]

WORKSHOP_ENTRY_ORIGINS = [
    {"code": "station", "label": "Estacao"},
    {"code": "customer_driver", "label": "Cliente / Condutor"},
    {"code": "rentway_alert", "label": "Alerta Rentway"},
    {"code": "internal_preparation", "label": "Preparacao interna"},
    {"code": "other", "label": "Outro"},
]

WORKSHOP_PRIORITIES = [
    {"code": "normal", "label": "Normal"},
    {"code": "high", "label": "Alta"},
    {"code": "urgent", "label": "Urgente"},
]

WORKSHOP_PHASE_TEMPLATE = [
    {
        "code": "process_creation",
        "name": "Criacao do Processo",
        "sort_order": 1,
        "purpose": "Abrir processo por entrada imediata ou marcacao.",
    },
    {
        "code": "administrative_reception",
        "name": "Entrada em Oficina",
        "sort_order": 2,
        "purpose": "Confirmar entrada, KM, observacao, fotos e alertas sem bloquear.",
    },
    {
        "code": "history_check",
        "name": "Validacao Administrativa",
        "sort_order": 3,
        "purpose": "Confirmar historico interno, Service Box, campanhas e plano de manutencao.",
    },
    {
        "code": "technical_phase",
        "name": "Diagnostico",
        "sort_order": 4,
        "purpose": "Adicionar relatorios tecnicos, leituras de maquina, incidentes e resultado tecnico inicial.",
    },
    {
        "code": "diagnosis_decision",
        "name": "Controlo e Conformidade",
        "sort_order": 5,
        "purpose": "Transformar dados tecnicos em decisao operacional.",
    },
    {
        "code": "budget_approval",
        "name": "Aprovacao da Intervencao",
        "sort_order": 6,
        "purpose": "Fase pendente, sobretudo para reparacao externa.",
        "default_status": "pending_definition",
    },
    {
        "code": "internal_repair_execution",
        "name": "Reparacao",
        "sort_order": 7,
        "purpose": "Registar intervencao, pecas, relatorios finais e foto final do quadrante.",
    },
    {
        "code": "final_closure",
        "name": "Fecho da Intervencao",
        "sort_order": 8,
        "purpose": "Validar evidencias, estado operacional e encerrar o processo.",
    },
]

STELLANTIS_REPORTS = [
    {
        "code": "engine_lubrication",
        "label": "Lubrificacao motor",
        "description": "Oleo, carbono, protecao e intervalo calculado.",
        "fields": [
            {"code": "engine_speed", "label": "Regime motor", "unit": "rpm"},
            {"code": "oil_temperature", "label": "Temperatura oleo", "unit": "C"},
            {"code": "oil_pressure_reference", "label": "Pressao oleo referencia", "unit": "Bar"},
            {"code": "oil_pressure_current", "label": "Pressao oleo atual", "unit": "Bar"},
            {
                "code": "oil_pressure_regulation_opening",
                "label": "Abertura regulacao pressao oleo",
                "unit": "%",
            },
            {"code": "oil_dilution_rate", "label": "Diluicao estimada do oleo", "unit": "%"},
            {"code": "oil_carbon_rate", "label": "Carbono estimado no oleo", "unit": "%"},
            {"code": "anti_dilution_protection", "label": "Protecao anti-diluicao", "unit": None},
            {
                "code": "calculated_interval",
                "label": "Intervalo calculado por perfil",
                "unit": "km",
            },
        ],
    },
    {
        "code": "maintenance_information",
        "label": "Informacoes manutencao",
        "description": "KM, dias, limites e numero de manutencoes.",
        "fields": [
            {
                "code": "km_last_maintenance_reset",
                "label": "Km ultima reposicao manutencao",
                "unit": "Kms",
            },
            {
                "code": "km_before_next_maintenance",
                "label": "Km antes proxima manutencao",
                "unit": "Kms",
            },
            {
                "code": "days_before_next_maintenance",
                "label": "Dias restantes antes manutencao",
                "unit": "Dia(s)",
            },
            {
                "code": "time_limit_exceeded",
                "label": "Limite temporal ultrapassado?",
                "unit": None,
            },
            {
                "code": "km_limit_exceeded",
                "label": "Limite quilometrico ultrapassado?",
                "unit": None,
            },
            {"code": "maintenance_key_display", "label": "Chave de manutencao", "unit": None},
            {
                "code": "days_since_last_reset",
                "label": "Dias desde ultima reposicao",
                "unit": "Dia(s)",
            },
            {"code": "maintenance_count", "label": "N. manutencoes efetuadas", "unit": None},
        ],
    },
    {
        "code": "maintenance_programming",
        "label": "Programacao manutencao",
        "description": "Limiar, duracao, circulacao e primeira manutencao.",
        "fields": [
            {"code": "maintenance_threshold", "label": "Limiar manutencao", "unit": "km"},
            {
                "code": "total_duration_before_maintenance",
                "label": "Duracao total antes manutencao",
                "unit": "meses",
            },
            {
                "code": "first_maintenance_start",
                "label": "Inicio da primeira manutencao",
                "unit": "km",
            },
            {
                "code": "duration_before_first_maintenance",
                "label": "Duracao antes primeira manutencao",
                "unit": "meses",
            },
            {
                "code": "engine_managed_maintenance_type",
                "label": "Tipo de manutencao gerida pela motorizacao",
                "unit": None,
            },
        ],
    },
    {
        "code": "maintenance_plan_validation",
        "label": "Validacao plano manutencao",
        "description": "Comparar solicitacao, plano Service Box e parametrizacao Rentway.",
        "fields": [
            {
                "code": "requested_service",
                "label": "Solicitacao do processo",
                "unit": None,
            },
            {
                "code": "servicebox_plan",
                "label": "Plano Service Box aplicavel",
                "unit": None,
            },
            {
                "code": "servicebox_plan_type",
                "label": "Tipo de plano usado",
                "unit": None,
            },
            {
                "code": "servicebox_interval_km",
                "label": "Intervalo plano normal Service Box",
                "unit": "km",
            },
            {
                "code": "servicebox_interval_months",
                "label": "Intervalo plano normal Service Box",
                "unit": "meses",
            },
            {
                "code": "systematic_checks_km",
                "label": "Verificacoes sistematicas",
                "unit": "km",
            },
            {
                "code": "systematic_checks_months",
                "label": "Verificacoes sistematicas",
                "unit": "meses",
            },
            {
                "code": "engine_oil_change_km",
                "label": "Mudanca oleo motor",
                "unit": "km",
            },
            {
                "code": "engine_oil_change_months",
                "label": "Mudanca oleo motor",
                "unit": "meses",
            },
            {
                "code": "engine_oil_reference_exact",
                "label": "Referencia exata do oleo",
                "unit": None,
            },
            {
                "code": "planned_services",
                "label": "Servicos previstos por km/idade",
                "unit": None,
            },
            {
                "code": "servicebox_due_km",
                "label": "Proxima manutencao Service Box",
                "unit": "km",
            },
            {
                "code": "servicebox_due_date",
                "label": "Data prevista Service Box",
                "unit": None,
            },
            {
                "code": "rentway_plan",
                "label": "Plano parametrizado Rentway",
                "unit": None,
            },
            {
                "code": "rentway_interval_km",
                "label": "Intervalo Rentway",
                "unit": "km",
            },
            {
                "code": "rentway_interval_months",
                "label": "Intervalo Rentway",
                "unit": "meses",
            },
            {
                "code": "request_matches_servicebox_plan",
                "label": "Solicitacao bate certo com plano?",
                "unit": None,
            },
            {
                "code": "rentway_matches_servicebox_plan",
                "label": "Parametrizacao Rentway correta?",
                "unit": None,
            },
            {
                "code": "validation_notes",
                "label": "Notas / decisao",
                "unit": None,
            },
        ],
    },
    {
        "code": "fault_reading",
        "label": "Leitura defeitos",
        "description": "Defeitos, codigos, estado e acao recomendada.",
        "fields": [
            {"code": "faults_found", "label": "Defeitos encontrados?", "unit": None},
            {"code": "faults", "label": "Lista de defeitos", "unit": None, "repeatable": True},
        ],
    },
    {
        "code": "remote_download",
        "label": "Telecarregamento",
        "description": "Software, data e numero de telecarregamentos.",
        "fields": [
            {"code": "software_reference", "label": "Referencia do software", "unit": None},
            {"code": "remote_download_date", "label": "Data de telecarregamento", "unit": None},
            {"code": "remote_download_count", "label": "Numero de telecarregamentos", "unit": None},
        ],
    },
    {
        "code": "other_reading",
        "label": "Outra leitura",
        "description": "Relatorio ainda sem categoria propria.",
        "fields": [
            {"code": "reading_title", "label": "Titulo da leitura", "unit": None},
            {"code": "area_system", "label": "Area / sistema", "unit": None},
            {"code": "parameters", "label": "Parametros", "unit": None, "repeatable": True},
            {"code": "evidence_link", "label": "Evidencia / link", "unit": None},
        ],
    },
]

TECHNICAL_CHECKS = [
    {"code": "levels", "label": "Niveis"},
    {"code": "tires", "label": "Pneus"},
    {"code": "brakes", "label": "Travoes"},
    {"code": "lights", "label": "Luzes"},
    {"code": "battery", "label": "Bateria"},
    {"code": "visible_leaks", "label": "Fugas visiveis"},
    {"code": "abnormal_noises", "label": "Ruidos anormais"},
    {"code": "technical_visual_state", "label": "Estado visual tecnico"},
    {"code": "road_test", "label": "Teste de estrada"},
]


def service_label_by_code(code: str) -> str:
    for service in WORKSHOP_SERVICE_OPTIONS:
        if service["code"] == code:
            return service["label"]
    return code


def build_process_title(service_codes: list[str], manual_title: str | None = None) -> str:
    if "other" in service_codes and manual_title:
        return manual_title
    return " + ".join(service_label_by_code(code) for code in service_codes)
