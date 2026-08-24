# CarFast — runbook convencional de migração por VM UE

> **SUPERSEDED (2026-08-24):** o bundle integral numa única janela foi abandonado.
> O único percurso vigente é `STORAGE_PRESEED_DELTA_MIGRATION_RUNBOOK.md`. Este
> documento permanece apenas como histórico de topologia e preços; não é executável.

Estado: **desenho offline; não autoriza provisionamento, acesso a dados reais nem
alterações Blue/Green**. O transporte customizado Render está encerrado e não faz
parte deste percurso.

Versão documental: 2026-08-24. Origem fixada: Blue `58a150c7`, 162 tabelas de
aplicação. Destino: release modular a fixar no gate, 166 relações após Alembic
`ffae1f2a3b4c -> fff37f8a9b0d`. Footprint medido: BD ~208 MiB, storage ~0,97 GiB,
total ~1,17 GiB.

## 1. Decisão e topologia

Usar uma única VM temporária Hetzner Cloud em Nuremberga (`nbg1`) ou Falkenstein
(`fsn1`), Alemanha, com Ubuntu 24.04, arquitetura x86-64, **CX33 (4 vCPU, 8 GB RAM,
80 GB SSD)**, Primary IPv4, firewall Hetzner e um Volume de 20 GB montado
manualmente com LUKS2. O volume guarda exclusivamente artefactos cifrados e a
instância PostgreSQL 17 de validação; `/run/carfast-migration` é `tmpfs`. Swap fica
desativado. Backups e snapshots Hetzner ficam desativados.

O CX33 dá margem para PostgreSQL 17, `pg_dump`/`pg_restore`, Alembic e hashing sem
usar swap. O Volume de 20 GB comporta os ~1,17 GiB cifrados, staging PostgreSQL,
manifests e margem superior a 4x. Hetzner replica Volumes em três servidores, mas
não fornece snapshots/backups de Volumes; a confidencialidade é fornecida por LUKS2,
não presumida do block storage do fornecedor.

Fluxo:

```text
Blue running instance --SSH command--> age ciphertext --> VM/LUKS
       | pg_dump custom             db.dump.age
       ` tar deterministic          storage.tar.age

VM/LUKS -> decrypt to pipes -> local PG17 + storage staging
         -> 162 reconcile -> Alembic -> 166 reconcile -> PASS/NO-GO

PASS only: same ciphertext -> decrypt to pipes -> Green DB/storage staging
           -> repeat reconciliation -> Green available for acceptance
```

Não existe endpoint de ingestão, proxy, listener ou protocolo próprio. Só são usados
OpenSSH/SFTP, `pg_dump`, `pg_restore`, `psql`, `tar`, `sha256sum`, `age`, LUKS2 e
ferramentas do repositório pinned.

## 2. Base oficial e escolhas

- Render suporta SSH em Web Services pagos e recomenda SCP com `-s` (SFTP) para
  discos persistentes. O disco só é acessível pela instância à qual está ligado;
  não está disponível em builds, pre-deploy ou one-off jobs:
  [SSH](https://render.com/docs/ssh) e [Persistent Disks](https://render.com/docs/disks).
- A chave host oficial Frankfurt é publicada pela Render. Fixar no `known_hosts` a
  entrada oficial `ssh.frankfurt.render.com ssh-ed25519
  AAAAC3NzaC1lZDI1NTE5AAAAILg6kMvQOQjMREehk1wvBKsfe1I3+acRuS8cVSdLjinK` e exigir
  fingerprint `SHA256:dBRrCEA0tBkvaYLzzDw/mzaANw6nUJO961Zx806spZs`.
- Render suporta `pg_dump` pela external URL e `pg_restore` para uma BD vazia. Uma
  exportação lógica Render fica retida sete dias; por isso **não é usada**, pois
  viola a retenção máxima deste runbook:
  [Postgres backups](https://render.com/docs/postgresql-backups).
- A external URL PostgreSQL pode ser limitada por CIDR; a aplicação deve continuar
  a usar o hostname completo por causa de SNI/TLS:
  [Postgres connectivity](https://render.com/docs/postgresql-creating-connecting).
- Hetzner Firewalls são stateful. Inbound tem deny implícito; outbound só passa a
  deny implícito quando existe pelo menos uma regra outbound:
  [Firewall FAQ](https://docs.hetzner.com/cloud/firewalls/faq/).
- Hetzner Alemanha disponibiliza Cloud Servers, Firewalls e Volumes; Primary IPv4
  custa €0,50/mês sem IVA e IPv6 é gratuito:
  [server overview](https://docs.hetzner.com/cloud/servers/overview/).
- Volumes são faturados à hora, mínimo 10 GB, e custam €0,044/GB/mês:
  [Volume overview](https://docs.hetzner.com/cloud/volumes/overview/) e
  [block storage](https://www.hetzner.com/cloud/block-storage/).
- Preço novo do CX33 Alemanha desde 15-06-2026: €0,0136/h, máximo €8,49/mês, sem
  IVA e sem IPv4:
  [price adjustment](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/).
- Para cliente português sem VAT ID válido aplica-se IVA 23%; com VAT ID UE válido,
  reverse charge:
  [VAT](https://docs.hetzner.com/general/billing-and-account-management/billing-at-hetzner/value-added-tax/).

### `pg_dump` direto versus export Render

| Critério | `pg_dump` no Blue via SSH | Export lógico Render |
|---|---|---|
| Cutoff comum BD+storage | Sim; ambos sob a mesma janela read-only | Não garante o mesmo cutoff do storage |
| Credencial Blue fora do runtime | Não; `$DATABASE_URL` só é consumida no Blue | Download exige acesso ao artefacto Render |
| Retenção controlável | Ciphertext existe só na VM e é destruído no prazo | Render retém o export sete dias |
| Formato/restauro | `pg_dump -Fc` / `pg_restore`, PG17 | arquivo `.dir.tar.gz`, também lógico |
| Decisão | **Escolhido** | **Excluído** pela retenção e cutoff |

## 3. Matriz de dados, segredos, residência e retenção

| Item | Conteúdo | Onde existe | Proteção | Retenção máxima | Destruição/prova |
|---|---|---|---|---|---|
| Dados Blue em claro | 162 tabelas | memória/pipes Blue; local PG17 no LUKS | read-only; SSH; LUKS2 | até 48 h após captura | drop cluster + `cryptsetup luksErase` + delete Volume/VM |
| Storage em claro | ficheiros/paths | pipe Blue; staging no LUKS | SSH; LUKS2; sem swap | até 48 h | unlink staging, LUKS erase, delete resources |
| `db.dump.age` | dump PG custom cifrado | Volume LUKS VM | age + LUKS2 | até PASS Green ou 48 h, o primeiro | SHA-256, unlink, erase Volume |
| `storage.tar.age` | tar determinístico cifrado | Volume LUKS VM | age + LUKS2 | igual | SHA-256, unlink, erase Volume |
| Manifests | nomes técnicos, tamanhos, hashes, contagens | Volume e relatório sanitizado | LUKS; relatório sem PII | relatório técnico durável; manifesto cru <=48 h | remover manifesto cru |
| Chave privada age | identidade de decrypt | offline escrow + tmpfs VM | nunca junto dos artefactos; 0600 | duração do ensaio | zero/unlink tmpfs; destruir escrow após Green PASS |
| Recipient age | chave pública | Blue `/tmp`, VM | não secreta; fingerprint pinned | duração | remover de Blue/VM |
| Chave SSH VM | login `migration` | operador/Render account e `authorized_keys` VM | Ed25519, única, sem agent forwarding | duração | revogar Render; remover local e VM |
| Chave host VM | identidade da VM | VM | fingerprint confirmado pela Console e pinned | vida da VM | delete VM; remover `known_hosts` dedicado |
| URLs PostgreSQL | credenciais Blue/Green | apenas env Blue ou tmpfs VM no respetivo passo | 0600/tmpfs; nunca logs/argv | minutos | unset/zero; fechar allowlist |
| Logs | etapas, rc, duração, hashes agregados | journal técnico | sem URLs, SQL, paths reais ou payload | conforme auditoria CarFast | revisão/redação |

Residência: VM, Volume e processamento em Alemanha; Render Blue/Green em Frankfurt.
Nenhum object storage, snapshot, backup Hetzner ou export lógico Render é criado.

## 4. Gate 1 — provisionar VM vazia e validar

Este gate **não permite dados/segredos Blue/Green**.

### Autorização requerida

“Autorizo criar por até 48 horas uma VM Hetzner CX33 em `nbg1`/`fsn1`, Primary
IPv4, Firewall e Volume 20 GB, apenas com fixtures sintéticas, ao custo máximo
indicado neste runbook, e autorizo a sua destruição integral.”

Estado: satisfeito pelo pacote contínuo aprovado por André em 2026-08-24, sujeito
ao read-back de preço/capacidade e a qualquer confirmação action-time da interface.

### Provisionamento fixo

1. Criar projeto Hetzner dedicado, sem backups. Gerar uma chave Ed25519 efémera e
   adicioná-la na criação; nunca aceitar password enviado por email.
2. Cloud-init cria utilizador `migration`, shell `/bin/bash`, grupos mínimos, SSH
   public-key only; define `PermitRootLogin no`, `PasswordAuthentication no`,
   `KbdInteractiveAuthentication no`, `AllowUsers migration`; desativa e mascara
   swap; ativa atualizações de segurança e `umask 077`.
3. Criar Volume 20 GB manual, **sem filesystem automático**. Executar
   `cryptsetup luksFormat --type luks2`, abrir como `carfast_crypt`, criar ext4 e
   montar `/srv/carfast-migration` com `nodev,nosuid,noexec`; chave LUKS em tmpfs,
   separada do Volume.
4. Firewall inbound: TCP/22 apenas de `<OPERATOR_IPV4>/32`; nenhuma outra regra.
   Outbound inicial: DNS/NTP e HTTPS apenas para instalação. Após instalar Ubuntu
   patches, `postgresql-client-17`, servidor PostgreSQL 17, `age`, `cryptsetup`, Git
   e dependências pinned, substituir por allowlist exata: DNS/NTP necessários,
   `ssh.frankfurt.render.com:22` nos IPs resolvidos/pinned e, apenas para a carga
   Green do Gate 2, IPs `/32` atuais do hostname PostgreSQL Green na porta 5432.
5. Confirmar via Console a fingerprint host da VM por canal separado; criar
   `known_hosts` dedicado e usar sempre `StrictHostKeyChecking=yes`,
   `IdentitiesOnly=yes`, `PasswordAuthentication=no`, `ForwardAgent=no`.
6. Clonar o repositório sem credenciais persistidas, checkout ao SHA aprovado,
   remover remote/token, criar venv e provar uma única cabeça Alembic.

### Provas sintéticas obrigatórias

- `swapon --show` vazio; `/proc/swaps` sem entradas; core dumps desativados.
- `lsblk`, `findmnt` e `cryptsetup status` provam que PostgreSQL, artefactos e
  staging estão no mapper LUKS; `/run/carfast-migration` é tmpfs.
- Firewall read-back prova deny-by-default nas duas direções e apenas CIDRs/portas
  fixadas; scan externo vê somente 22 a partir do IP autorizado.
- Utilizador `migration` não é root, não tem password, não aceita chaves alternativas
  e `sudo` fica limitado a comandos de serviço/mount predefinidos.
- PG17 real: dump custom de fixtures 162, restore vazio, reconciliação 162, Alembic
  até 166, sequences/FKs/ownership, reconciliação final e storage sintético com
  paths/tamanhos/SHA-256.
- Pipeline `tar | age | ssh` com fixtures, truncamento, hash errado, disco cheio,
  host key errada e chave age errada; todos falham fechados e deixam zero plaintext.
- Reboot prova: Volume não abre sem chave separada, swap continua off, serviços de
  migração não arrancam automaticamente e nenhum listener além de SSH aparece.

Gate 1 PASS só se todas as células tiverem evidência sanitizada e zero diferença.

## 5. Gate 2 — captura real Blue read-only

Gate lógico independente: só inicia após Gate 1 PASS. O pacote contínuo aprovado por
André em 2026-08-24 já autoriza a continuação condicional; não elimina nenhum
preflight, stopping condition ou confirmação action-time imposta pela interface.

### Autorização requerida

“Autorizo uma única captura real Blue para a VM Hetzner validada, com Blue read-only
por no máximo 20 minutos, `pg_dump` e storage completos cifrados na origem, validação
162→166 e posterior carga Green apenas após PASS, sem cutover, DNS ou integrações.”

Estado: satisfeito condicionalmente pelo mesmo pacote contínuo; executar uma única
vez e apenas depois de toda a evidência sintética verde.

### Preflights antes de read-only

1. Reconfirmar IDs Blue/Green, SHA Blue `58a150c7`, SHA modular, 162/166, espaço
   >=10 GiB livre no LUKS, PG client/server 17, relógio UTC e custo/TTL.
2. Reconfirmar Blue/Green em Frankfurt, integrações/email/jobs/webhooks/portais OFF
   no Green e que nenhum segredo Green/Blue cru está em disco/log/argv.
3. Criar chave SSH Ed25519 exclusiva na VM e adicionar somente a chave pública à
   conta Render pelo tempo da operação. Fixar a host key Frankfurt oficial. Não usar
   agent forwarding.
4. Transferir para `/tmp/carfast-migration-bin` no Blue apenas binário `age` x86-64
   oficial com SHA-256 previamente pinned e recipient público. `/tmp` apenas;
   `chmod 0500`; nenhuma chave privada Blue.
5. Não abrir acesso PostgreSQL externo no Blue. Todo o dump corre **dentro da
   instância Blue** e só ciphertext sai pelo SSH. Resolver apenas o hostname externo
   Green para o passo posterior a PASS; permitir os seus IPs `/32` no firewall VM e
   o IPv4 VM `/32` na allowlist Green apenas no instante da carga, sempre ligando pelo
   hostname completo/TLS.
6. Criar no Blue role efémero `carfast_vm_export_<nonce>` com LOGIN, sem
   CREATEDB/CREATEROLE/REPLICATION/BYPASSRLS, CONNECT à BD, USAGE no schema e SELECT
   apenas nas 162 tabelas congeladas; sem sequences, DDL, default privileges ou
   escrita. Provar SELECT e negações INSERT/UPDATE/DELETE/DDL. Guardar a password
   apenas num `PGSERVICEFILE`/`PGPASSFILE` 0600 em tmpfs Blue; nunca a transmitir à
   VM. O dump usa `--data-only` e uma lista `--table` explícita das 162 tabelas, pelo
   que não necessita de sequence values; schema/constraints são criados no staging
   pela migration baseline pinned e comparados ao metadata read-only Blue.
7. Provar acesso SSH ao exato instance slug que monta o disco Blue. Preparar sessão
   administrativa PostgreSQL persistente e caminho de recuperação
   out-of-band. Não abrir read-only se não for possível restaurar writes mesmo após
   perda da sessão SSH.

### Janela comum e captura

Usar um `BUNDLE_ID`, `CUTOFF_UTC` e release únicos. Cronometrar desde o primeiro
bloqueio de escrita.

1. Na sessão administrativa, fixar `default_transaction_read_only=on` para a BD,
   terminar as outras sessões da aplicação e provar que INSERT/UPDATE/DELETE falham
   enquanto SELECT continua. A sessão administrativa aberta antes da alteração fica
   reservada para rollback; o runbook de ação deve ter o comando inverso já preparado.
2. Obter DB cifrada diretamente da instância Blue, sem ficheiro plaintext:

```bash
ssh ${RENDER_BLUE_TARGET} -- \
  'set -euo pipefail; export PGSERVICEFILE=/run/carfast-export/pg_service.conf; \
   export PGPASSFILE=/run/carfast-export/pgpass; \
   mapfile -t TABLES </run/carfast-export/tables-162.txt; TABLE_ARGS=(); \
   for T in "${TABLES[@]}"; do TABLE_ARGS+=("--table=$T"); done; \
   pg_dump --format=custom --data-only --no-owner --no-acl \
   "${TABLE_ARGS[@]}" --dbname=service=carfast_export | \
   /tmp/carfast-migration-bin/age -R /tmp/carfast-age-recipient.txt' \
  >"${CRYPT_ROOT}/incoming/db.dump.age.partial"
mv "${CRYPT_ROOT}/incoming/db.dump.age.partial" \
   "${CRYPT_ROOT}/incoming/db.dump.age"
```

3. Obter storage do mesmo instance slug, determinístico e cifrado antes de sair:

```bash
ssh ${RENDER_BLUE_TARGET} -- \
  'set -euo pipefail; cd "$STORAGE_ROOT"; \
   find . -xdev -type f -print0 | sort -z | \
   tar --null --files-from=- --no-recursion --numeric-owner -cf - | \
   /tmp/carfast-migration-bin/age -R /tmp/carfast-age-recipient.txt' \
  >"${CRYPT_ROOT}/incoming/storage.tar.age.partial"
mv "${CRYPT_ROOT}/incoming/storage.tar.age.partial" \
   "${CRYPT_ROOT}/incoming/storage.tar.age"
```

4. Gerar tamanhos e SHA-256 dos dois ciphertexts e manifesto técnico ligado a
   `BUNDLE_ID/CUTOFF_UTC/releases`. Só depois de ambos estarem completos e não
   `.partial`, restaurar imediatamente writes, terminar o cronómetro e provar uma
   escrita controlada da aplicação. Limite absoluto: 20 minutos; timeout provoca
   rollback de writes, NO-GO e remoção de parciais.
5. Remover binário/recipient de `/tmp` Blue e a chave SSH Render no primeiro momento
   em que o acesso ao disco Blue deixa de ser necessário.

Os comandos finais devem ser gerados por script revisto com variáveis obrigatórias;
os placeholders acima nunca recebem secrets em argumentos ou logs.

## 6. Validação na VM: 162 → 166

1. Verificar hashes/tamanhos cifrados antes de decrypt. Decrypt apenas para pipes ou
   destinos LUKS; nunca para root disk ou `/tmp` persistente.
2. Criar cluster/BD PG17 vazios no LUKS, owner temporário sem privilégios externos;
   checkout ao SHA Blue/baseline e executar migrations até `ffae1f2a3b4c` para criar
   deterministicamente o schema 162 vazio.
3. `age -d ... | pg_restore --exit-on-error --data-only --no-owner --no-acl
   --dbname=<STAGING>`. Sem `--clean`. Capturar somente etapa, rc, duração e
   fingerprint de stderr.
4. **Fase A:** conjunto/schema/PK/FK/contagens/digests/órfãos e sequences das 162
   contra o manifesto Blue, tolerância zero.
5. Checkout à release pinned; `alembic upgrade ffae1f2a3b4c`, confirmar baseline;
   `alembic upgrade fff37f8a9b0d`; validar as quatro relações aditivas por contrato,
   sem dados operacionais inventados.
6. Reset/validação de sequences, owners, grants, search_path, constraints, índices,
   FKs e órfãos; manifesto 166 e comparação tolerância zero.
7. `age -d storage.tar.age | tar -xf - -C <LUKS_STAGING>` após listar/verificar que
   nenhum path é absoluto, `..`, symlink, device ou FIFO. Comparar conjunto exato,
   path normalizado, tamanho e SHA-256 com o manifesto Blue.
8. Testes focados da release com integrações OFF. Três repetições lógicas de
   manifests/hashes devem produzir o mesmo resultado.

Qualquer diferença inexplicada é NO-GO. Não há correção manual de dados.

## 7. Carga Green após PASS, sem cutover

1. Reconfirmar Green exato, vazio/não promovido, BD/storage próprios, efeitos OFF e
   rollback limpo por migrations+seeds. Bloquear acesso de utilizadores durante carga.
2. Abrir allowlist da BD Green apenas ao IPv4 VM `/32`; usar external URL completa
   com TLS. Restaurar em BD/schema vazio:

O preflight cria em tmpfs um `PGSERVICEFILE` e `PGPASSFILE` 0600 a partir do segredo
injetado sem o imprimir; os processos PG recebem `PGSERVICE=green` e a password só
por `PGPASSFILE`, nunca URL/password em argv. O restore é:

```bash
age -d -i "${AGE_IDENTITY_TMPFS}" "${CRYPT_ROOT}/incoming/db.dump.age" | \
  pg_restore --exit-on-error --no-owner --no-acl --dbname=service=green
```

3. Repetir Fase A 162, Alembic 166, sequences/ownership/grants e reconciliação zero.
4. Pelo SSH/SFTP oficial Render, carregar storage para subdiretório staging do disco
   Green, nunca diretamente sobre live:

```bash
age -d -i "${AGE_IDENTITY_TMPFS}" "${CRYPT_ROOT}/incoming/storage.tar.age" | \
  ssh ${RENDER_GREEN_TARGET} -- \
    'set -euo pipefail; mkdir -p "$GREEN_STORAGE_STAGING"; \
     tar -xf - -C "$GREEN_STORAGE_STAGING"'
```

5. Reconciliar paths/tamanhos/SHA-256 no Green. Só com PASS promover o diretório por
   rename atómico e disponibilizar Green para aceitação; isto não muda DNS/domínio e
   não ativa integrações. Fechar imediatamente allowlist DB e revogar chave SSH.
6. Se a BD Green não permitir staging/recriação vazia de forma reversível, parar:
   não usar `pg_restore --clean`, não sobrepor dados e pedir gate de topologia.

## 8. Rollback, cleanup e destruição certificada

Em qualquer falha: restaurar writes Blue primeiro; fechar sessões/allowlists; matar
subprocessos; remover `.partial`; não promover Green. Green incompleto é reconstruído
de migrations/seeds por ser vazio, nunca por limpeza de Blue.

Cleanup máximo: imediatamente após PASS/NO-GO e nunca depois de 48 h da captura.

1. Revogar/drop do role Blue temporário e destruir a password/PG service files;
   revogar chave SSH Render e chave de login VM; remover allowlists Blue/Green.
2. Apagar recipient/binário `/tmp` Blue, identity age tmpfs, URLs e known_hosts
   dedicado; provar processos/sessões ausentes.
3. Parar PG17 local, remover staging/plaintext; `shred` não é alegado como prova em
   SSD. Executar `cryptsetup luksErase`/destruir material de chave e desmontar.
4. Eliminar Volume Hetzner, depois VM, Primary IPv4, Firewall, SSH key e projeto
   temporário. Hetzner declara que a imagem do Cloud Server é apagada quando o cliente
   remove o servidor; a garantia operacional é crypto-erasure + delete read-back:
   [TOMs](https://docs.hetzner.com/general/security-and-identify/technical-and-organizational-measures/).
5. Confirmar por API/Console ausência de todos os IDs e ausência de backups/snapshots;
   guardar apenas relatório sanitizado, recibo de eliminação, tempos e custos.

## 9. Custos oficiais estimados

Base conservadora após 15-06-2026, sem backups/snapshots e sem tráfego excedente:

| Recurso | Preço líquido | 24 h | 48 h |
|---|---:|---:|---:|
| CX33 Alemanha | €0,0136/h | €0,3264 | €0,6528 |
| Volume 20 GB (€0,044/GB/mês, 720 h) | ~€0,00122/h | ~€0,0293 | ~€0,0587 |
| Primary IPv4 (€0,50/mês, 720 h) | ~€0,00069/h | ~€0,0167 | ~€0,0333 |
| **Total sem IVA** |  | **~€0,3724** | **~€0,7448** |
| **Com IVA PT 23%** |  | **~€0,4581** | **~€0,9161** |

Com VAT ID UE válido aplica-se reverse charge. Reservar teto operacional de **€1,25
com IVA para 48 h**, cobrindo arredondamentos; tráfego UE incluído (20 TB) excede
largamente 1,17 GiB. Confirmar quote na Console no instante do Gate 1.

## 10. Ameaças, riscos e stopping conditions

| Ameaça/risco | Controlo | Stop imediato |
|---|---|---|
| SSH MITM | host keys Render oficiais e VM confirmada out-of-band; strict checking | fingerprint diferente/ausente |
| Exposição pública VM | firewall inbound 22 só `/32`, outbound allowlist; sshd key-only | qualquer porta/origem extra |
| Roubo de artefactos | age antes de sair Blue + LUKS2 + chave separada + swap off | plaintext fora LUKS/tmpfs |
| Credencial Blue fora da origem | `pg_dump` no Blue com internal env; receiver só ciphertext | URL em VM/log/argv |
| Chave Render ampla | chave efémera única, sem forwarding, revogada cedo | chave preexistente/reutilizada |
| Cutoff inconsistente | writes bloqueadas até DB+storage cifrados e manifestados | timeout >20m ou write observado |
| Path traversal/storage hostil | listagem e rejeição de path/type antes de extract | absoluto, `..`, link/device/FIFO |
| Restore destrutivo | BD vazia, sem `--clean`, IDs/owners verificados | alvo não vazio/ambíguo |
| Drift 162/166 | manifests e Alembic pinned, tolerância zero | falta/sobra/digest/FK diferente |
| Residência/retention drift | Alemanha, sem backups/exports, TTL 48 h | recurso fora UE ou snapshot/export |
| Falha cleanup | crypto-erase, delete e read-back de todos IDs | qualquer recurso/allowlist/chave residual |

Stopping conditions adicionais: SHA/release/instance slug errado; `age`/PG não PG17;
espaço <10 GiB; swap/core dump ativo; LUKS não montado; clock drift; external DB CIDR
mais amplo que VM `/32`; integrações Green ON; Blue não volta writable; custo previsto
acima do gate; ou qualquer pedido de cutover/DNS/produção não autorizado.

## 11. Checklist action-time

### Gate 1

- [ ] Aprovação literal, quote e TTL registados.
- [ ] Conta/DPA/IVA e projeto dedicado confirmados.
- [ ] VM/IPv4/Firewall/Volume IDs e região Alemanha read-back.
- [ ] SSH key-only, host key pinned, root/password/agent forwarding OFF.
- [ ] Firewall default-deny inbound/outbound; scan e egress negatives.
- [ ] LUKS2/tmpfs/swap/core dumps/permissions comprovados.
- [ ] PG17/repo/SHA/Alembic/tools pinned.
- [ ] Fixture 162→166 + storage + adversariais PASS.
- [ ] Nenhum Blue/Green ID, URL, segredo ou dado presente.

### Gate 2

- [ ] Aprovação literal e janela de até 20 min.
- [ ] Todos os preflights, rollback de writes e cleanup ensaiados.
- [ ] Chaves age/SSH separadas, host keys e allowlists `/32` confirmadas.
- [ ] Blue read-only início/fim cronometrados; negações e restauração provadas.
- [ ] DB+storage ciphertexts completos, hashes e cutoff comum.
- [ ] VM Phase A 162, Alembic 166, sequences/FKs/owners/storage PASS.
- [ ] Green load/reconcile PASS sem DNS/cutover/integrações, ou NO-GO limpo.
- [ ] Allowlist/chaves/artefactos/VM/Volume/IPv4/Firewall/projeto destruídos.
- [ ] Custos, IDs ausentes e relatório sanitizado entregues.
