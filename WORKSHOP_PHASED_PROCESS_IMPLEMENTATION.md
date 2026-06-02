# Processo Oficina por Fases - Implementacao

## Estado

Implementado como novo tipo de processo, sem substituir processos antigos.

## Paginas

- `/workshop/new-process`
- `/workshop/processes-ui`
- `/workshop/processes-ui/{process_id}`
- `/workshop/processes-ui/{process_id}/manage`

## APIs

- `GET /workshop/process-config`
- `GET /workshop/processes`
- `POST /workshop/processes/phased`
- `GET /workshop/processes/{process_id}`
- `POST /workshop/processes/{process_id}/reception`
- `POST /workshop/processes/{process_id}/history-check`
- `POST /workshop/processes/{process_id}/technical-reports`
- `POST /workshop/technical-reports/{report_id}/validate`
- `POST /workshop/processes/{process_id}/technical-checks`
- `POST /workshop/processes/{process_id}/incidents`
- `POST /workshop/processes/{process_id}/diagnosis-decision`
- `POST /workshop/processes/{process_id}/internal-repair`
- `POST /workshop/processes/{process_id}/close`

## Fases

1. Criacao do Processo
2. Rececao Administrativa
3. Verificacao de Historico
4. Fase Tecnica
5. Diagnostico e Decisao
6. Orcamento / Aprovacao
7. Reparacao Interna / Execucao
8. Fecho Definitivo

## Notas de produto

- Orcamento / Aprovacao fica pendente e orientado a reparacao externa.
- Relatorios Stellantis iniciais e finais ja existem como estrutura.
- Autel fica preparado como origem, mas ainda sem parser/detalhe proprio.
- Mecanico adiciona relatorio; rececao valida apenas se os campos foram lidos corretamente.
- Verificacoes tecnicas podem gerar tarefas e sinalizar potencial cobranca ao cliente.
- Fecho definitivo atualiza o estado operacional da viatura quando a viatura esta ligada ao processo.

## Validacao feita

- `python -m compileall app scripts`
- `python -m ruff check` nos ficheiros alterados
- Testes com `TestClient`
- Servidor local em `http://127.0.0.1:8001`
