# Integracao de email com Postmark

Estado: especificacao funcional e tecnica. Este pacote nao implementa a integracao, nao ativa envios e nao altera configuracao de producao.

## Conteudo

- [Plano de integracao](PLANO_INTEGRACAO_EMAIL_POSTMARK.md)
- [Guia de configuracao](GUIA_CONFIGURACAO_ANDRE.md)
- [Checklist de ativacao](CHECKLIST_ATIVACAO.md)
- [Proposta de implementacao e teste](PROPOSTA_IMPLEMENTACAO_TESTE.md)
- [Matriz de enderecos](MATRIZ_ENDERECOS.csv)
- [Exemplo de variaveis de ambiente](VARIAVEIS_AMBIENTE_EXEMPLO.txt)
- [Mockup da caixa e conversa](mockups/carfast-email-inbox-conversa.png)
- [Mockup da pagina Email com quatro enderecos](mockups/pagina-email-4-enderecos.png)
- [Mockup da tarefa ligada ao email](mockups/tarefa-ligada-email.png)

## Principios aprovados

- Email e um modulo independente; uma conversa pode ser tratada sem tarefa.
- Respostas nao criam tarefas automaticamente e usam a timeline existente quando houver tarefa ligada.
- O acesso a uma tarefa nao concede acesso ao email de origem.
- A partilha com tarefas e seletiva para resumo, entidades e anexos.
- Respostas externas usam paginas isoladas por token, sem acesso ao Hub.
- O envio pode seguir um fluxo configuravel de rascunho, aprovacao e envio.
- Qualquer edicao posterior invalida a aprovacao anterior.

## Seguranca

O ficheiro de variaveis contem apenas nomes e placeholders. Tokens, segredos e credenciais reais nunca devem ser guardados no repositorio.
