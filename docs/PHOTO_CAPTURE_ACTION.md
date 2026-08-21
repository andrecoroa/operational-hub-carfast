# Ação reutilizável “Tirar fotografia”

## Contrato e integração futura

A implementação fornece o primitivo de domínio e API sem criar um motor de fluxos paralelo. Cada definição publicada é imutável, usa `action_type=take_photo`, `schema_version=1` e guarda apenas configuração declarativa validada. Cada sessão conserva um snapshot dessa configuração, pelo que execuções antigas não mudam quando uma nova versão é publicada.

O Construtor de Fluxos genérico ainda não existe. Quando existir, a ligação necessária é pequena: registar no catálogo do canvas um bloco `take_photo` cujo editor produza o schema v1 já aceite por `PhotoActionDefinition`, e criar uma `PhotoCaptureSession` ao instanciar o passo, associando `task_flow_step_id` e os contextos de tarefa/processo/fase/viatura. A conclusão do passo deve consultar `required_photo_blockers`. Não é necessário alterar o armazenamento nem criar outro executor.

## Armazenamento e metadados

As fotografias reutilizam `Document`/`DocumentLink` e o arquivo privado configurado. O conteúdo é identificado por SHA-256 e um único `PhotoMedia` referencia o objeto físico, mesmo quando ligado a vários contextos. Downloads e thumbnails passam por endpoints autenticados e autorizados.

Só JPEG, PNG e WebP são aceites após validação da assinatura e descodificação real; SVG e HTML não são fotografias válidas. Os nomes de arquivo são gerados pelo servidor. Imagens são normalizadas com Pillow, orientação EXIF aplicada e metadados removidos; a localização só é guardada em colunas próprias mediante consentimento explícito e configuração que a permita. O original recebido não é preservado com EXIF. O thumbnail é gerado separadamente para previews eficientes.

Retenção e remoção seguem a política documental: a remoção operacional é lógica e auditada; o objeto físico não é eliminado enquanto puder estar referenciado. A eliminação definitiva deve ser executada apenas por uma futura rotina de retenção que confirme ausência de referências e autorização `photos.remove`.

## Permissões

- `photos.capture`: criar sessão, capturar e submeter;
- `photos.read`: consultar sessões e ficheiros privados;
- `photos.review`: aprovar, rejeitar e pedir repetição;
- `photos.configure`: publicar versões de configuração;
- `photos.remove`: remover logicamente uma captura segundo a política.

Além da permissão funcional, a API valida no servidor o acesso à tarefa, processo, fase e entidade associada. A UI apenas reflete essas decisões e não constitui a barreira de segurança.
