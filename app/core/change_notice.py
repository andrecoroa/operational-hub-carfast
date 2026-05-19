CHANGE_NOTICE_SESSION_KEY = "change_notice_ack"
CHANGE_NOTICE_VERSION = "2026-05-tasks-workshop"

CHANGE_NOTICE_TITLE = "Atualizações importantes"
CHANGE_NOTICE_SECTIONS = [
    {
        "title": "Centro de tarefas",
        "items": [
            "A listagem passa a mostrar primeiro as tarefas mais recentes.",
            "O campo Natureza foi removido na criação de tarefas operacionais.",
            "O responsável passa a ser sempre uma pessoa. A execução pode ser delegada a pessoa ou equipa.",
            "Os estados foram simplificados: Em execução, Execução delegada, A aguardar, Execução concluída, Pronta para validação, Fechada, Cancelada e Sem ação necessária.",
            "Ao colocar uma tarefa a aguardar é obrigatório indicar o motivo. Em Outro motivo deve ser preenchido o detalhe.",
            "Aguardar por decisão deve incluir comentário com a sugestão de resolução.",
        ],
    },
    {
        "title": "Oficina",
        "items": [
            "O processo de oficina passa a seguir a lógica de cockpit: entrada, diagnóstico, decisão, execução, validação e fecho.",
            "Durante o processo podem ser registadas evidências, documentos e incidentes associados.",
            "No diagnóstico devem ser registados os dados disponíveis, incluindo dados BSI quando aplicável.",
            "O relatório do processo pode ser consultado e impresso em qualquer momento.",
        ],
    },
]
