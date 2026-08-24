# CarFast — runbook fechado de preseed do storage + delta final

Estado: **readiness offline**. Este documento não autoriza dados reais, read-only,
recursos, chaves ou alterações Blue/Green. Substitui o transporte integral numa
única janela. O transporte customizado Render e o relay single-stream estão
retirados do percurso.

Origem congelada: Blue `58a150c7`, 162 tabelas. Destino: release modular imutável a
fixar no gate, 166 relações após Alembic `ffae1f2a3b4c -> fff37f8a9b0d`. Footprint
observado: BD ~208 MiB, storage ~0,97 GiB, total ~1,17 GiB.

## 1. Contrato fechado

Cada execução possui `BUNDLE_ID`, `SOURCE_SHA`, `TARGET_SHA`, `PRESEED_MANIFEST_ID`,
`FINAL_MANIFEST_ID` e `CUTOFF_UTC`. Um manifesto é JSON canónico ordenado por path;
cada entrada contém somente path relativo UTF-8 normalizado, tamanho e SHA-256.
O digest SHA-256 do manifesto liga estes claims e a lista completa.

Regras invariantes:

- Só ficheiros regulares sob a raiz de storage e no mesmo filesystem são aceites.
  Symlinks, hardlinks com contagem inesperada, sockets, devices, FIFOs, paths
  absolutos, `..`, nomes duplicados/case-collisions e cruzamento de mount causam
  NO-GO antes de transmitir.
- Um ficheiro é estável apenas se `(device,inode,size,mtime_ns)` for igual antes e
  depois do hash/cópia e o byte count igualar `size`. Durante preseed há três
  retries com backoff do orquestrador; persistindo instável, o scan é descartado e
  um novo manifesto de preseed é construído sem esse path, que obrigatoriamente
  reaparece no manifesto/delta final.
  Na janela read-only nenhuma instabilidade é permitida.
- Rename nunca é inferido: é `remove(old)+copy(new)`. Um object store temporário
  content-addressed pode reutilizar ciphertext com o mesmo SHA, mas o destino só
  aceita o novo path após decrypt e verificação integral.
- Cada objecto é cifrado na origem com `age` para um recipient efémero. A private
  identity existe apenas em memória/tmpfs 0600 no destino e nunca junto dos
  artefactos. SFTP/SSH usa host key pinned, `IdentitiesOnly=yes`, sem agent/port
  forwarding. `.partial` só se torna `<sha256>.age` por rename depois de tamanho,
  exit codes e hash ciphertext passarem.
- Retries são idempotentes: um objecto existente é saltado apenas após verificação
  de tamanho e SHA-256 plaintext. Parcial, hash divergente ou autenticação falhada é
  apagado. Nenhuma compatibilização manual é permitida.
- O destino materializa sempre uma árvore staging no mesmo filesystem do storage
  Green. Cópias usam ficheiro parcial 0600, `fsync`, verificação e `rename`; deletes
  são aplicados só no staging. O storage ativo nunca é alterado incrementalmente.

Implementação de referência **apenas para fixtures sintéticas** de
manifests/delta/retoma: `app.platform.storage_preseed_delta`. As funções de scan e
sync recusam execução sem `synthetic_only=True`; isto impede uso acidental em dados
reais. A prova offline é `python -m scripts.rehearse_storage_preseed_delta`.
O scanner/aplicador Linux real é um artefacto obrigatório do gate seguinte: deve
operar por `dirfd/openat`, `O_NOFOLLOW` em cada componente, `fstat` no descriptor e
`renameat/unlinkat`, eliminando check-then-use por pathname.

## 2. A — preseed cifrado com Blue writable

1. Reconfirmar IDs/paths, SHA, capacidade e integrações Green OFF. Criar recipient
   age e chave SSH exclusivos; fixar host keys. Nenhuma credencial de BD é usada.
2. Fazer scan estável Blue e fechar `preseed-manifest.json`. Objectos instáveis após
   retries são registados apenas por contagem sanitizada, não entram no manifesto.
3. Para cada SHA ainda ausente no destino temporário, executar na origem um pipe
   parametrizado e sem payload em logs:

   ```text
   open regular file -> verify pre-stat -> age -R RECIPIENT -> ssh/sftp .partial
                     -> verify post-stat/bytes/rc -> atomic object commit
   ```

4. Interrupção, timeout ou perda SSH cancela o objecto atual; na retoma, reler o
   manifesto fechado, provar claims e saltar apenas objectos já verificados. No fim,
   decrypt/hash para staging e reconciliar exatamente o preseed. Blue permanece
   writable e não há prazo operacional nesta fase.
5. Capacidade antes de começar: `free >= 2 * final_storage + encrypted_objects +
   max_object + 20%`. O volume de 10 GB Green é suficiente para ~0,97 GiB atual,
   mas o read-back real decide; abaixo da fórmula é NO-GO.

## 3. B — cutoff e delta final, Blue read-only <20 minutos

Todos os passos seguintes ficam preparados e testados antes de bloquear writes.
O orçamento operacional é **15 minutos**, deixando cinco minutos de margem ao hard
stop de 20. Aos 15 minutos restauram-se writes e o resultado é NO-GO.

Preflights não consumidores: fingerprints/claims iguais nas pontas; clock UTC;
espaço/inodes; PG17 `pg_dump/pg_restore`; lista exata 162; role SELECT-only pronta
mas ainda ausente; sessões de recuperação; manifests/recipient/host key; throughput
p95 medido; nenhum `.partial`; Green offline e integrações OFF.

Sequência cronometrada:

1. Ativar read-only na BD Blue, drenar writers e provar SELECT disponível e
   INSERT/UPDATE/DELETE/DDL negados. Bloquear também jobs e qualquer writer de
   filesystem. A sessão administrativa de rollback permanece aberta.
2. Fixar `CUTOFF_UTC` **depois** de todos os writers estarem quiescentes. Fazer
   `pg_dump -Fc --no-owner --no-acl` das 162 tabelas via role efémero; nenhuma
   credencial sai do emissor.
3. Construir duas vezes o manifesto final completo do storage. Os dois digests têm
   de ser iguais. Calcular `delta = final - preseed`: novos/alterados são copies;
   ausentes são deletes. Transmitir somente SHAs ainda não verificados.
4. O ACK autenticado `BUNDLE_CAPTURED` só existe quando dump, manifesto final,
   todos os objectos delta e deletion list estão completos, ligados ao mesmo
   bundle/cutoff/releases e verificados. Só então restaurar writes, remover role e
   provar uma escrita controlada. Não esperar por restore/Alembic.

O cutoff é comum porque BD e filesystem ficam sem writers antes do marcador e
permanecem imóveis até ao ACK. Qualquer alteração entre os dois manifests finais,
writer residual, stream incompleto ou deadline restaura writes imediatamente e
descarta o bundle.

## 4. C — restore 162→166 e promoção conjunta lógica

Com Blue novamente writable:

1. Restaurar `pg_dump` numa BD/schema staging vazio com PG17 e flags/ownership/
   grants/search_path congelados. Phase A compara tolerância zero as 162 relações:
   schema, PK/FK, contagens, digests e órfãos.
2. Executar Alembic exatamente `ffae1f2a3b4c -> fff37f8a9b0d`. Confirmar preservação
   das 162, quatro relações aditivas pelo contrato explícito, sequences, ownership,
   grants, índices e zero dados operacionais inventados.
3. Clonar/materializar o preseed em `storage.next.<bundle>`, aplicar copies por
   temp+fsync+rename e deletes somente nessa árvore, depois comparar o manifesto
   completo path/tamanho/SHA-256 ao final. Não seguir symlinks nem promover parcial.
4. Green permanece indisponível durante validação. A promoção conjunta lógica é um
   único start/config pinned que referencia simultaneamente a BD reconciliada e a
   árvore `storage.next.<bundle>` promovida por rename atómico no mesmo filesystem.
   Antes do start, gravar um marker técnico assinado com os dois manifest digests.
   Não há DNS, domínio, cutover ou integrações.
5. Smoke tests técnicos read-only confirmam release, migrations, autenticação local,
   166 relações e storage. Qualquer diferença é NO-GO; não se corrige dado à mão.

## 5. D — rollback, retenção e cleanup

- Antes de promoção: apagar BD/schema staging, storage staging, parciais e bundle;
  Blue nunca deixou de ser produção. Green vazio/intacto.
- Falha no start Green: parar Green, reverter em conjunto o pointer/config da BD e
  rename do storage para o estado Green anterior vazio; nunca expor combinação
  híbrida. Blue continua disponível.
- Em PASS ou NO-GO: revogar/drop role; zerar/remover age identity, SSH keys,
  credentials e env; remover ciphertext/manifests crus e relay/VM/Codespace, se
  usados; provar ausência e custo. Retenção máxima: 48 h ou conclusão, o primeiro.
- Cleanup é idempotente e corre em `finally`; falha de cleanup mantém NO-GO e escala
  imediatamente, sem nova tentativa automática.

## 6. Prova sintética e critério temporal

A prova offline obrigatória cria objectos determinísticos, interrompe após o primeiro
objecto, retoma, altera um ficheiro, adiciona outro, remove outro e renomeia um quarto.
Ela prova hashes/manifests, delete+copy, exact reconciliation e ausência de `.partial`.
Os testes locais cobrem retoma idempotente, path traversal, symlink de origem e de
parent destino, source/hash divergente, manifests duplicados/malformados e aplicação
exata. Special/cross-mount, retries com backoff do orquestrador, falhas de fsync e o
transporte cifrado pertencem obrigatoriamente à prova Linux standard externa.

Antes de dados reais, uma prova sintética externa com a topologia standard escolhida
deve usar volume >= footprint observado e cifragem age real. Deve medir separadamente
scan final, dump PG17, bytes delta, transferência e ACK. PASS temporal exige:

```text
p95(scan_final + pg_dump + delta_transfer + ACK) <= 15 min
projected_delta_bytes >= worst observed mutation burst
3/3 execuções verdes; uma com interrupção/retoma do preseed
```

O teste local dá correção funcional, não autoriza extrapolar rede/IO para a janela.

## 7. FMEA e stopping conditions

| Falha | Prevenção/deteção | Resposta |
|---|---|---|
| Ficheiro muda no preseed | stat antes/depois + hash | retry; excluir para delta |
| Writer após cutoff | drain + negações + manifests duplos | writes ON, NO-GO |
| Delete/rename perdido | diff por path; rename=delete+copy | exact manifest ou NO-GO |
| Symlink/special/traversal | `lstat`, same-root, path parser | abortar antes do pipe |
| Parent trocado entre check/use | dirfd/openat + O_NOFOLLOW; nunca pathname | abortar; nenhum real sem prova Linux |
| Ciphertext truncado/tampered | age auth, bytes, rc, SHA | apagar parcial, NO-GO |
| Retoma mistura bundles | claims/fingerprint fechados | rejeitar e limpar |
| Disco/inodes insuficientes | fórmula e read-back | não iniciar |
| Delta excede janela | benchmark p95 + hard 15 min | writes ON, NO-GO |
| DB 162 diverge | Phase A zero-tolerance | não executar Alembic |
| 162→166 diverge | contrato aditivo/manifests/FK/sequences | não promover |
| Promoção híbrida | Green parado + marker conjunto | rollback dos dois pointers |
| Cleanup incompleto | inventário/read-back final | NO-GO e escalamento |

Stopping conditions adicionais: release/config drift, role demasiado amplo, efeito
externo, credencial em log/argv, host key diferente, custo/TTL excedido, relógio
inválido, qualquer diferença inexplicada ou incapacidade de restaurar writes.

## 8. Gate único seguinte

Antes do gate devem existir: scanner/aplicador Linux dirfd auditado; testes/CI
verdes; revisão independente; inventário
162/166 fechado; release imutável; resultado 3/3 da prova sintética standard em
volume real e previsão p95 <=15 min; topologia/custo/cleanup fixados.

Frase única requerida:

> Autorizo uma única migração real pelo runbook de preseed cifrado + delta final na
> release imutável indicada, incluindo preseed com Blue writable, janela read-only
> máxima de 20 minutos, restore 162→166 e carga técnica Green, sob stopping
> conditions, custo e cleanup documentados, sem cutover, DNS ou integrações.
