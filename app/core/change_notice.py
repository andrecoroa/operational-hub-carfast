CHANGE_NOTICE_SESSION_KEY = "change_notice_ack"
CHANGE_NOTICE_VERSION = "2026-05-workshop-alerts-practices"

CHANGE_NOTICE_TITLE = "Novidades e boas práticas"
CHANGE_NOTICE_SECTIONS = [
    {
        "title": "Oficina: processo mais leve",
        "items": [
            "O processo de oficina passa a funcionar por pontos de controlo, evitando formulários longos e mantendo registos importantes para auditoria.",
            "Os passos do fluxo devem ser preenchidos apenas quando existe informação real: receção, histórico, Service Box, BSI, verificações, decisão e fecho.",
            "Evidências, incidentes, documentos e notas continuam disponíveis como ações complementares, sem misturar tudo no fluxo principal.",
            "A entrada documental do processo mostra o caminho sugerido de arquivo e permite guardar o link da pasta 365.",
        ],
    },
    {
        "title": "Alertas automáticos",
        "items": [
            "Cada processo de oficina passa a mostrar alertas automáticos no topo do detalhe.",
            "Os alertas avisam sobre receção incompleta, histórico por verificar, Service Box em falta, BSI em falta, verificações pendentes, documentos em falta e incidentes abertos.",
            "Os alertas não bloqueiam o trabalho. Servem para chamar a atenção antes de avançar ou fechar o processo.",
            "Se o alerta não se aplicar, regista uma nota curta ou conclui o passo correspondente para deixar rasto.",
        ],
    },
    {
        "title": "Boas práticas para amanhã",
        "items": [
            "Abrir processo apenas quando existir motivo real ligado a uma viatura.",
            "Na receção, confirmar sempre data, KM e motivo/serviço principal.",
            "Antes de decidir, verificar histórico; em viaturas Stellantis, verificar também Service Box quando aplicável.",
            "Registar evidência sempre que existir situação anormal: dano, ruído, fuga, luz no painel, desgaste ou dúvida relevante.",
            "Associar documentos por link. Não carregar ficheiros binários para a base de dados.",
            "Fechar tecnicamente apenas quando a intervenção estiver validada; fechar administrativamente apenas quando documentos e arquivo estiverem coerentes.",
        ],
    },
]
