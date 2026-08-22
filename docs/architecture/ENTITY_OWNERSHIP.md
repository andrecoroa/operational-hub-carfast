# Entity ownership and dependency map

## 1. Rules

Ownership means one module defines lifecycle, invariants, writes and canonical contracts. Physical table location does not by itself define ownership during transition. Another module may hold a foreign/reference ID but cannot mutate the owner table.

Legacy class codes:

- **C** — canonical or intended canonical.
- **A** — compatibility adapter/dual-read-write transition.
- **H** — historical read-only target.
- **R?** — candidate for retirement only after evidence and approval.

No **R?** item may be removed based on this document alone.

## 2. Current table ownership proposal

### Core platform

| Current tables | Proposed owner | Class/notes |
|---|---|---|
| `users`, `roles`, `permissions`, `user_roles`, `role_permissions` | Core Identity/Access | C; permission codes need compatibility mapping |
| `organizational_units`, `user_organizational_units`, `teams`, `team_members` | Core Organization | C; remove CarFast-specific seeds from clean path |
| `settings_catalogs`, `settings_values` | Core Settings | A; add owner/schema/secret/environment metadata |
| `audit_log` | Core Audit | C; immutable envelope/correlation expansion |
| `evolution_records`, comments/history/documents | Core product feedback or Service Desk | HYPOTHESIS: keep as Core governance until functional owner approved |
| `pilot_feedback` | Core product feedback | R? after evidence/retention decision |

New Core-owned tables are required for installation, module catalogue/state, event outbox, notification registry, search provider state and job execution. Their creation is not authorized in Phase 1.

### Service Desk

| Current tables | Capability | Class/notes |
|---|---|---|
| `tasks`, comments, history, assignment/SLA events, participants, help requests, notifications | Tasks/Tickets | C |
| `task_guided_flow_runs`, step runs | Processes/Tasks bridge | A; decide canonical process orchestration owner |
| `task_recurrence_templates`, occurrences | Tasks | C; old recurrence columns on `tasks` are A |
| `quick_records` | Tasks intake | A; candidate to become command/intake record |
| `task_email_origins` | Email↔Tasks link | A; contract-owned link, no Email table mutation |
| `work_queues`, departments, categories, subcategories | Service Desk classification | C for Service Desk; generic naming currently obscures owner |
| `service_desk_ticket_types`, category policies/supervisors/executors | Service Desk | C |
| `role_work_scopes`, `work_source_defaults` | Service Desk access/config | A; scope engine integrates with Core authorization |
| `email_channels`, aliases, rules | Email/Communications configuration | C, installation-specific |
| `email_threads`, messages, attachments, webhook events, deliveries, audit events | Email/Communications | C |
| `email_channel_users`, roles, executor eligibilities, templates, thread links | Email/Communications | C; access decisions delegated to Core policy |
| `email_intakes`, `email_intake_attachments` | Email legacy intake | A/H; reconcile with canonical email records |
| `management_process_types`, processes, associations, rules, actions, evidences, history | Processes | A; characterize current management centre flows |
| `claim_incidents`, `claim_rentway_ars`, `claim_refstro_lines` | Processes or Automotive incidents | HYPOTHESIS; decide by lifecycle, not screen location |

### Document Management

| Current tables | Proposed owner | Class/notes |
|---|---|---|
| `documents`, `document_events`, `document_workflow_states` | Documents | C; generic `status` becomes A during transition |
| `document_links` | Documents | C contract link |
| `diagnostic_documents`, `diagnostic_extractions` | Documents with Automotive document profile | C; Automotive supplies interpretation contract |
| `vehicle_document_records`, tags, alerts, pending actions, audit fields | Documents or Automotive/Fleet | A; split generic document ownership from vehicle operational projections |
| `task_documents` | Documents↔Service Desk association | A; replace direct shared-table assumption with link contract |
| `import_batches`, files, raw rows, errors, mappings | Core technical import framework or owning module | HYPOTHESIS: framework metadata Core, import definition/results owned by module |
| `photo_action_definitions` | owning module configuration | A; manifest contribution |
| `photo_media`, capture sessions/items | Documents/media service | A; binary ownership and business workflow must separate |

### Automotive & Fleet

| Current tables | Capability | Class/notes |
|---|---|---|
| `vehicles`, identifiers, lifecycle/status events | Vehicle core | C |
| `vehicle_manual_fields`, external snapshots | Fleet integration | A; typed canonical fields plus source snapshots |
| `vehicle_financial_plans`, installments | Fleet | C |
| `vehicle_history_audits` and documents/readings/services/issues/truths/rules | Fleet audit | C/H depending record type; preserve all evidence |
| `workshop_phased_processes`, phases, alerts, services, reports, checks, incidents, closure checks | Workshop | C target |
| `workshop_templates`, versions, diagnostic catalogue/suggestions, counters | Workshop configuration | C; installation/reference classification required |
| `workshop_material_needs` | Workshop | C request; Stock fulfils through contract |
| `workshop_processes`, notes, evidences, services, readings | Workshop legacy | A/H until every active/historical process reconciles |
| `incidents`, evidences, events | Automotive shared incident capability or Workshop | HYPOTHESIS based on actual flows |
| `vehicle_sale_profiles`, images, publications, leads, proposals, proposal lines | Vehicle Sales | C |
| `portal_organizations`, users, invitations, publication access | Vehicle Sales external access adapter | A; hypothetical future portal is not designed here |

### Stock & Purchasing

| Current tables | Proposed owner | Class/notes |
|---|---|---|
| `stock_locations`, categories, articles, supplier refs, minimums | Stock | C |
| `stock_movements` | Stock ledger | C; immutable |
| `stock_invoice_imports`, lines | Purchasing/Stock intake | C, Documents referenced by contract |
| `stock_receipts`, invoice links, receipt lines | Purchasing | C |
| `stock_inventory_sessions`, counts | Stock | C |
| `stock_purchase_orders`, lines | Purchasing | C |
| `stock_delivery_documents`, discrepancies | Purchasing | C |
| `stock_article_vehicle_compatibilities` | Stock catalogue projection | C; Automotive reference only |

### Partners & Suppliers

| Current tables | Proposed owner | Class/notes |
|---|---|---|
| `stock_suppliers` | Partners | A: physical legacy name; canonical partner identity target |
| `supplier_types`, assignments | Partners | C; module-role vocabulary must be installation-safe |
| `supplier_contacts`, addresses | Partners | C |

## 3. Exact table coverage appendix

**FACT:** the baseline declares 162 SQLAlchemy table names. **RECOMMENDATION:** the following is the exact provisional owner index; grouped tables in the earlier sections are expanded here so no current table is left implicit.

| Owner | Exact current tables |
|---|---|
| Core Identity/Access | `users`, `roles`, `permissions`, `user_roles`, `role_permissions` |
| Core Organization | `organizational_units`, `user_organizational_units`, `teams`, `team_members` |
| Core Settings/Audit | `settings_catalogs`, `settings_values`, `audit_log` |
| Core product governance (provisional) | `evolution_records`, `evolution_record_comments`, `evolution_record_history`, `evolution_record_documents`, `pilot_feedback` |
| Core/module import framework (ownership split pending) | `import_batches`, `import_files`, `import_raw_rows`, `import_errors`, `import_mappings` |
| Service Desk — Tasks | `tasks`, `task_comments`, `task_documents`, `task_history`, `task_assignment_events`, `task_sla_events`, `task_participants`, `task_email_origins`, `task_help_requests`, `task_notifications`, `task_guided_flow_runs`, `task_guided_flow_step_runs`, `task_recurrence_templates`, `task_recurrence_occurrences`, `quick_records` |
| Service Desk — classification/access | `work_queues`, `work_departments`, `work_categories`, `work_subcategories`, `service_desk_ticket_types`, `service_desk_category_policies`, `service_desk_category_supervisors`, `service_desk_category_executors`, `role_work_scopes`, `work_source_defaults`, `classification_sequences`, `classification_proposals`, `classification_proposal_usages`, `classification_proposal_audits` |
| Service Desk — Email | `email_channels`, `email_channel_aliases`, `email_inbox_rules`, `email_threads`, `email_messages`, `email_attachments`, `email_webhook_events`, `email_message_deliveries`, `email_audit_events`, `email_channel_users`, `email_channel_roles`, `email_executor_eligibilities`, `email_templates`, `email_thread_links`, `email_intakes`, `email_intake_attachments` |
| Service Desk — Processes | `management_process_types`, `management_processes`, `management_process_associations`, `management_rules`, `management_actions`, `management_evidences`, `management_history`, `claim_incidents`, `claim_rentway_ars`, `claim_refstro_lines` |
| Document Management | `documents`, `document_links`, `document_events`, `document_workflow_states`, `diagnostic_documents`, `diagnostic_extractions`, `vehicle_document_records`, `vehicle_document_record_tags`, `vehicle_document_alerts`, `vehicle_document_pending_actions`, `vehicle_document_audit_fields`, `photo_action_definitions`, `photo_media`, `photo_capture_sessions`, `photo_capture_items` |
| Automotive — Vehicle/Fleet | `vehicles`, `vehicle_identifiers`, `vehicle_lifecycle_events`, `vehicle_operational_status_events`, `vehicle_manual_fields`, `vehicle_external_snapshots`, `vehicle_financial_plans`, `vehicle_financial_plan_installments`, `vehicle_history_audits`, `vehicle_history_audit_documents`, `vehicle_history_audit_readings`, `vehicle_history_audit_services`, `vehicle_history_audit_issues`, `vehicle_history_audit_truths`, `vehicle_history_audit_rules` |
| Automotive — incidents (placement pending) | `incidents`, `incident_evidences`, `incident_events` |
| Automotive — Workshop legacy | `workshop_processes`, `workshop_process_notes`, `workshop_process_evidences`, `workshop_process_services`, `workshop_technical_readings` |
| Automotive — Workshop target | `workshop_phased_processes`, `workshop_public_counters`, `workshop_templates`, `workshop_template_versions`, `workshop_diagnostic_catalog_items`, `workshop_diagnostic_suggestions`, `workshop_material_needs`, `workshop_phased_process_services`, `workshop_phased_process_phases`, `workshop_phased_process_alerts`, `workshop_phased_technical_reports`, `workshop_phased_technical_checks`, `workshop_phased_technical_incidents`, `workshop_phased_closure_checks` |
| Automotive — Sales/portal adapter | `vehicle_sale_profiles`, `vehicle_images`, `vehicle_sale_publications`, `vehicle_sale_leads`, `vehicle_sale_proposals`, `vehicle_sale_proposal_lines`, `portal_organizations`, `portal_users`, `portal_invitations`, `portal_publication_access` |
| Stock & Purchasing | `stock_locations`, `stock_categories`, `stock_articles`, `stock_article_supplier_refs`, `stock_minimums`, `stock_invoice_imports`, `stock_invoice_lines`, `stock_receipts`, `stock_receipt_invoice_links`, `stock_receipt_lines`, `stock_movements`, `stock_article_vehicle_compatibilities`, `stock_inventory_sessions`, `stock_inventory_counts`, `stock_purchase_orders`, `stock_purchase_order_lines`, `stock_delivery_documents`, `stock_discrepancies` |
| Partners & Suppliers | `stock_suppliers`, `supplier_types`, `supplier_type_assignments`, `supplier_contacts`, `supplier_addresses` |

`task_documents` remains physically in Service Desk during compatibility but its association lifecycle must be mediated by the Document contract. Portal tables are current Sales adapters; this specification does not define a future standalone portal module.

## 4. Current versus permitted dependency matrix

Legend: `D` direct/current, `C` contract permitted, `E` event permitted, `R` stable reference permitted, `—` no dependency.

### Current dominant dependencies

| From \ To | Core | Service Desk | Documents | Automotive | Stock | Partners |
|---|---:|---:|---:|---:|---:|---:|
| Core/Admin shell | D | D | D | D | D | D |
| Service Desk | D | — | D | D/string refs | D via supplier | D |
| Documents | D | D | — | D | — | D/string |
| Automotive | D | D | D | — | D | D |
| Stock | D | — | D | D | — | D |
| Partners | D | D/email | D | D | D | — |

### Target permitted dependencies

| From \ To | Core | Service Desk | Documents | Automotive | Stock | Partners |
|---|---:|---:|---:|---:|---:|---:|
| Core | — | — | — | — | — | — |
| Service Desk | C | — | C/E/R | C/E/R | — | C/R |
| Documents | C | E/R | — | E/R | E/R | R |
| Automotive | C | C/E/R | C/E/R | — | C/E/R | C/R |
| Stock | C | — | C/E/R | R | — | C/R |
| Partners | C | E | C/E | E | E | — |

The target contains no mandatory operational-module dependency except a declared capability dependency approved in the catalogue. All modules depend on Core contracts.

## 5. Improper coupling inventory

| Current coupling | Risk | Target treatment |
|---|---|---|
| `app/web/router.py` imports most models/services | change collision and hidden ownership | strangler routes into module web packages |
| `clean_admin.py` imports every domain | inactive module breaks Admin | manifest-provided Admin contributions |
| Email imports `StockSupplier` | Email requires Stock implementation | Partners query/reference contract |
| Stock imports Workshop processes/material needs | Stock cannot stand alone | Workshop request/Stock fulfilment contracts |
| Stock/Suppliers/Vehicles import functions/templates from base router | presentation circularity | shared UI contract + module-owned view models |
| Documents hold direct FKs to task/vehicle/old Workshop plus generic links | removal/disable friction | keep compatible FKs initially; converge writes on reference contract |
| Workshop directly creates/reads Task and Document | cross-owner writes | application commands/events |
| `Supplier = StockSupplier` alias | conceptual owner remains Stock | Partners facade then non-destructive storage migration |
| router inclusion and model imports are unconditional | no true activation | manifest registry and composition gates |
| permissions split across navigation, middleware, handlers and scopes | divergent access | single policy decision with adapters |
| fixed redirects coexist with `return_url` | lost workflow context | transversal ReturnContext |

## 6. Legacy register and evidence required

| Candidate | Provisional class | Required evidence before change |
|---|---|---|
| old Workshop tables | A/H | active count, link count, route/job usage, document coverage |
| task text classification fields | A | null/mismatch counts against normalized hierarchy, integration consumers |
| task recurrence columns | A | scheduler reads/writes and outstanding recurrence count |
| `QuickRecord` duplicate fields | A | intake sources, unconverted count, audit/retention requirement |
| `Document.status` | A | mapping completeness to multidimensional workflow state |
| direct Document FKs | A | all consumers and orphan/reference reconciliation |
| email intake tables | A/H | comparison with canonical email messages and attachment hashes |
| management centre/claims models | HYPOTHESIS | real flows, owners, open records and statutory retention |
| pilot feedback | R? | row count, usage, retention and owner approval |
| duplicate API route surfaces | A | client/access log usage and compatibility commitments |

Evidence must include code references, PostgreSQL counts, relationship/orphan checks, authorized telemetry and functional sign-off. Absence from a visible flow is not proof of obsolescence.
