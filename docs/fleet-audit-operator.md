# Operador IA — auditoria de frota (primeira versão)

O operador fica no detalhe de cada processo **Auditoria a fornecedores**. O utilizador
autenticado pede uma análise; o servidor reúne apenas os campos do processo, viatura,
intervenientes, tarefas que o utilizador pode ver e metadados de documentos ligados
(quando tem permissão documental). Não lê o conteúdo dos anexos nesta versão.

O resultado separa factos, hipóteses, provas em falta e próximas ações, e propõe
uma comunicação. A proposta é temporária. O utilizador revê e, se quiser, guarda
um rascunho no processo; não existe envio automático, fecho automático ou alteração
de conclusões pelo operador. O pedido fica assinalado na auditoria, sem guardar o
texto submetido nem a resposta do modelo.

## Ativação

Por omissão, está desligado. Após aprovação do tratamento externo destes dados,
configurar no ambiente do servidor:

- `FLEET_AUDIT_OPERATOR_ENABLED=true`
- `FLEET_AUDIT_OPERATOR_MODEL=<modelo aprovado>`
- `OPENAI_API_KEY=<segredo do servidor>`

Nunca incluir a chave no repositório ou no browser. A chamada à API usa `store=false`.
O botão informa o utilizador de que os dados apresentados são transmitidos ao
serviço de IA configurado. A ativação em produção requer decisão explícita e teste
com dados de teste.

## Limites a resolver antes de expansão

- Não é ainda um chat persistente nem faz pesquisa transversal por toda a frota.
- A análise dos PDFs, OR e diagnósticos exige extração fiável, permissões por
  documento e apresentação da fonte exata, não apenas do nome do ficheiro.
- Rever acesso aos processos, consentimento/privacidade, custos e quotas antes de
  abrir a outros utilizadores.
- Testar qualidade e citações com casos de teste, especialmente situações com dois
  fornecedores e divergências entre manutenção real e contadores eletrónicos.
