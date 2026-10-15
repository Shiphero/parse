# Using routing-guide-parser locally

## From upload to validated scenario

1. Upload an original PDF and wait for **Pages ready**. Text-free pages are retained as images. Fix actual preparation failures before analysis.
2. Open **Connections**, choose Claude or OpenAI, and save a provider API key and exact vision-capable model ID. A saved credential is not a verified connection. Credentials are stored in the Docker documents volume in a mode-0600 file, never returned by the API or added to Git. Blank key fields retain the existing key; Remove clears the override, including environment fallback for that connection.
3. Choose the provider/model and **Analyze guide**. This sends guide text and rendered page images to the selected provider. Every target page gets a coverage result. All extracted document text accompanies each batch for cross-references. Start with 12 pages per batch; request/output limits split batches, never silently omit pages. If even a one-page request cannot fit the full text context, the run stops visibly and must be retried with a larger-context model. Analysis has three bounded attempts for transient failures. Completed batches persist. Complete structured provider responses are also saved privately before validation, keyed by analysis run and exact page batch; resume reuses a retained response without a model call. Missing warning metadata is recorded as a diagnostic note, while missing rule or coverage fields still fail with field-specific errors. Cancel stops remaining work after the current provider call returns; it cannot undo incurred provider charges.
4. Alternatively, **Start manual review** to create source-backed rules without a model. Every page starts unresolved and needs a recorded coverage decision. Manual runs are never presented as AI analysis.
5. Enter your reviewer name. Review proposed instructions, scope, exceptions, automatic checks and evidence beside original page images. Use rule-type categories to read instructions, applicability and source excerpts together. Select pending rules individually or select the current filtered group, including rules with review warnings, then approve in one batch with an optional note. Each rule records the reviewer, timestamp, exact revision and batch ID. Bulk approval is atomic and rejects stale, foreign or already-decided selections. Bulk and single approvals have optional notes, including flagged rules, and share the same classification, check-mapping and source-evidence requirements. Rejections and corrections require notes. Exceptions, unresolved interpretations, possible duplicate titles and visual evidence remain visible as review warnings; they do not prevent bulk approval or require an approval note. Saving an edit clears the approval and any inherited approval mapping. Review unresolved page coverage and analysis notes. Text citations must match the cited page after conservative whitespace, case and typography normalization; words, numbers and meaningful punctuation are preserved. Unmatched citations are retained in pending proposals with source-review flags instead of aborting a batch. Proposals with invalid source evidence cannot be approved until edited to valid evidence, and may be rejected without repairing their evidence. Their page coverage remains unresolved until a separate review decision. No automatic conversion to visual evidence occurs; visual citations require human verification.
6. In **Changes & publish**, give the release an explicit effective date, coverage/scope and publication notes. For updated guides, Review rules compares the active retailer release. After confirming the same operational scope, carry forward unique exact text matches in one action. All rule fields and text quotes must match; only PDF page movement is ignored and new citations are validated again. Visual evidence, exceptions, ambiguity, duplicate matches and changed rules are excluded. Original review history is preserved alongside the new reviewer, timestamp and revision. In Changes & publish, carried rules are collapsed under Unchanged and preserve stable identity with updated evidence. For the remaining previous rules, select retain, replace with a distinct approved candidate, or retire. Retention keeps its old evidence. Replacement preserves stable identity. An unmatched approved candidate becomes a new rule. Absence never implies retirement. The comparison shows content fields and old/new evidence; this is a reviewer-controlled comparison, not an autonomous semantic merge.
7. Preview the effect on saved scenarios and acknowledge coverage and impact. Publish an immutable release. A concurrent change to the draft or active release blocks stale publication. Download structured JSON or Markdown instructions. Restoring an older active release preserves all history; explicit release selection remains available for evaluations.
8. In **Scenarios**, paste canonical JSON or a wholesale order containing `packing_layout`. Save an immutable snapshot. Optional overrides replace named top-level fields and are retained separately. Choose an exact release and run deterministic checks. Results show pass, fail, cannot determine or not applicable for each subject. Prior evaluations stay pinned to their release.
9. To fetch ShipHero data, save an access token in Connections, choose the appropriate retailer, and enter a public wholesale order ID. Fetch & save performs one read-only query and records source/account/time. The import excludes names, email, phone, billing and payment data. It includes postal destination fields needed for rules; snapshots can still contain business-sensitive information. Tokens are refreshed manually. There are no ShipHero mutations.

## General guidance versus shipment validation

Rule `purpose` is independent of subject, obligation and verification:

- `general_guidance`: onboarding, EDI enablement, account setup and business instructions. Retained in approved instructions and exports, excluded from shipment evaluation items and counts. Responding to an OpenText onboarding invitation belongs here.
- `shipment_validation`: requirements checked against a shipment, including dimensions/weights, cartons/pallets, labels, routing, ASN timing and shipping documents. Human inspection and external evidence still belong here when they concern a shipment; they do not automatically pass.
- `unclassified`: legacy rules without a purpose, or ambiguous proposals. Choose their use before approval/publication. Historical unclassified releases produce Cannot determine rather than silently passing or dropping those rules.

New AI extraction prompts request the purpose explicitly, with contrasting examples for supplier administration versus per-shipment operations. For existing drafts, **Auto-classify remaining rules** runs a focused text-only pass using the analysis provider/model and the already extracted instructions, applicability and source excerpts. It does not resend page images or re-extract the PDF. Classification runs in saved batches, can be stopped or resumed after failure, and records the model, prompt version and a reason per rule. It fills missing classifications and rule types, skipping revisions edited while the model is running. Existing type assignments are preserved. The review UI includes approved draft rules; changed metadata returns those rules to review. Published releases remain unchanged. AI classifications remain draft proposals, not approvals. Existing drafts are not reclassified based on verification method. In Review rules, filter by rule use and select pending rules to classify in groups; classification creates new draft revisions and audit entries, without approving or changing evidence. Use the visible Verification filter to distinguish Automatic, Manual, External confirmation, Not configured and Guidance only. General guidance is excluded from shipment checks regardless of its obligation or verification method. Individual edits can change an approved rule's use and invalidate its approval. Bulk approval is a separate action. Scenario evaluator 1.1 excludes general guidance and reports how many were excluded; prior evaluation records remain unchanged. Rule purpose also participates in exact-match comparison, so a use change cannot inherit the earlier approval.

## Rule expressions

`schema_version: "1.0"` separates instructions, obligation, subject, applicability, exceptions, verification and evidence. Expressions are validated data, never executable code.

- Comparisons: `eq`, `ne`, `lt`, `lte`, `gt`, `gte`, `in`, `exists`.
- Boolean conditions: `all`, `any`, `not`, with bounded nesting and node count.
- Aggregates: `count`, `sum`, `unique_count` plus a comparison operator. Ranges use `all` with two comparisons. Per-carton consistency uses a unique count over its line items.
- Paths use dots and `*` array expansion, e.g. `line_items.*.po_number`. `shipment.*` accesses common shipment facts; `evidence.*` accesses supplemental facts. No arbitrary function invocation, generated code or regex execution.
- Measurements require `{ "value": "50", "unit": "lb" }`. Arithmetic uses Decimal and explicit conversion for oz/lb/g/kg and in/cm/mm. Unspecified or incompatible units yield unknown.
- True always means compliance, including prohibited obligations. Recommendations remain advisory; outcomes do not turn them into mandatory policy.
- Missing fields, incomplete inputs, unknown applicability, unresolved exceptions or questions, and human/external checks yield Cannot determine. A proven false applicability or true exception yields Not applicable. An empty/missing subject collection cannot create a blanket pass.

Illustrative condition, **not a retailer policy**:

```json
{"op":"lte","path":"weight","value":50,"unit":"lb"}
```

The scenario screen has an explicitly synthetic input example. It is never inserted as a rule or release.

## Interpretation and source boundaries

AI output remains a proposal. Coverage means every page was considered, not proof every requirement was discovered. Cross-reference interpretation and possible duplicates/conflicts require review. Human approval does not supply missing order facts. There is no implicit certification of compliance or inference of effective-date applicability: choose the release that applies to the scenario date and scope.

ShipHero mapping preserves raw nested containers, parent identities, CasePack/UOM quantities and distinct store/DC fields. It converts `weight_in_oz` and inch dimensions with their documented units. It does not sum parent/child weights, multiply case weights, infer full-load totals, invent carton PO membership from a single order PO, or infer an actual destination from a store identifier. Unsupported fields remain unknown. Add explicit overrides when additional verified facts are available.

The local reviewer name is self-declared, not authenticated identity. Shared deployment still needs SSO, roles/account scoping, object storage, backup/restore procedures, quotas and perimeter request limits. Dedicated OCR, Word/Excel ingestion, trained classifiers, automatic conflict resolution and calibrated model-quality benchmarking remain future work. Vision analysis handles image-only PDF pages without claiming a separate OCR stage.

## Verification and provenance

`make check` is intended for commit checkpoints: production frontend build, deterministic/backend integration tests, and Git whitespace checks. Database integration tests create isolated records inside rollback-only transactions. Provider responses are mocked in tests; those tests do not establish live provider access or extraction quality. Live Claude/OpenAI and ShipHero acceptance requires user-supplied credentials and representative guides/orders. Use an authentic older/newer guide pair before claiming update-extraction quality.

On October 12, 2026, a live Ulta cover-page request succeeded with `claude-opus-5-5` using automatic tool selection and the existing local rule validation. The model returned page 1 as `no_rules`. This verifies that request path, not extraction quality across the remaining 74 pages. Claude uses automatic tool selection because newer models reject forced tool calls. Responses without the expected extraction tool result remain unaccepted. Only confirmed input-size errors trigger smaller batches; model, billing and request-configuration errors stop with distinct messages and a provider request ID when available. To retry an existing failed AI run, select it in the Analysis menu, then choose Resume saved progress; a manual-review run is separate.

Official integration references consulted:

- [Anthropic vision](https://platform.claude.com/docs/en/build-with-claude/vision)
- [Anthropic structured tool inputs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)
- [OpenAI Responses structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [ShipHero wholesale order query](https://developer.shiphero.com/schema/queries/wholesale-order.html)
- [ShipHero packing layout](https://developer.shiphero.com/flows/export-packing-layout/)

## Operational categories and consumption points

Rule schema 1.1 adds two independent fields:

- `operational_category`: `warehouse_operations`, `transportation_scheduling`, `electronic_documents_edi`, `business_administration`, or `unclassified` for incomplete drafts.
- `consumption_points`: a bounded, unique list of workflows that enforce or present the obligation. Mobile picking/packing, label generation/application, pallet building, staging/loading, transport planning, pickup/delivery scheduling, document generation/delivery, ASN generation, EDI transmission, supplier onboarding/management, product setup, order management, billing, and compliance disputes have distinct identifiers in the API schema.

These fields do not replace `purpose`, `subject`, `obligation`, or `verification`. A per-shipment ASN rule belongs to electronic documents and EDI; it is consumed by ASN generation or EDI transmission. Packing-list delivery by email or portal uses `document_transmission`; sending structured EDI messages uses `edi_transmission`. Capturing carton contents in mobile packing does not make mobile packing a consumer of the ASN rule. A physical instruction to place a packing list on a carton belongs to warehouse operations; document content requirements belong to electronic documents. Classify by the required action, not guide section or department. Extraction should split independent obligations; classification of existing mixed rules flags ambiguity without changing the original text.

Review rules has operational category and consumption-point filters, and both fields are editable. Automatic classification fills missing dimensions and standard types. A newly assigned type uses its catalog category and display-only workflow defaults. Changed approved draft rules return to review; concurrent edits and existing type assignments are preserved. All changes remain audited, revisioned proposals. Rule schema 1.0 records stay readable; absent categories/consumers remain explicitly unclassified, never guessed. New approvals and publications require complete classification. Previously published releases remain immutable. Correcting consumer routing invalidates approval and prevents exact-match carry-forward.

Consumers can request `GET /api/releases/{release_id}/rules?consumption_point=mobile_packing`, optionally adding `operational_category=warehouse_operations`. This reads only an explicitly chosen immutable release and returns matching fully classified rules with evidence, review metadata, retailer ID and effective date. It includes guidance when explicitly assigned to that consumer; the existing scenario evaluator still excludes general guidance. Incomplete legacy rules are excluded with `unclassified_rule_count` and `routing_complete=false`, so an empty response must not be interpreted as complete coverage. This is rule delivery, not an integration with ShipHero mobile or the EDI transmission system, and it does not assess shipment applicability or claim compliance. JSON and Markdown release exports include both fields.

## Building conditional rules with diagrams

Use **Add rule**, **Edit rule**, or **Create variant** in an expanded review row. A variant is a separate pending draft, copying the instruction, classifications, conditions and source references. It never inherits approval or modifies the original. Variants can be created from rules whose evidence belongs to the current guide; cross-guide duplication is disabled to avoid rebinding citations to a different PDF.

The field dropdown offers subject-appropriate dimensions and weight for cartons/pallets, SKU and quantity for items, shipment properties, and a custom dot-separated path. New conditions have no preset field or threshold. Selecting a field sets its value type and suggested unit; values must still be supplied in the scenario, and missing data remains Cannot determine. The visual builder supports scalar comparisons and AND/OR groups, including explicit units and inclusive/exclusive bounds. Choose `carton` as the subject for carton-height conditions; `height` is evaluated separately for each carton. Conditions determine applicability; the automatic-check expression determines compliance. Keep label placement as human inspection unless actual placement facts are available. Complex existing expressions remain intact and can be edited through Advanced JSON, with explicit Apply/Discard before saving. Saving uses the existing revision, audit and source-validation controls.

Each source reference supports **Select diagram / image region**. Drag a rectangle or enter percentage bounds to select the relevant diagram. The saved representation is the existing PDF page plus normalized `region` coordinates; no source pixels are modified. A selected region requires individual visual review and cannot carry approval forward from a text-only match. Review and scenario results show the selected image region with its caption and PDF page. Published JSON and consuming-workflow responses retain these references and `source_guide_id`, allowing consumers to retrieve the page image. Separate uploaded images and standalone cropped-image download endpoints are not implemented.

Use one rule per conditional instruction/image. These rules are evaluated independently: there is no implicit first-match ordering, overlap resolution or fallback. Check exact boundaries and overlaps before approval. For example, headings saying greater than 7 and less than 7 do not establish what happens at exactly 7; less than 4.5 also overlaps less than 7. Missing height remains Cannot determine, and matching a manual rule never produces an automatic pass. Scenario results list the outcome for each carton and hide diagrams only when the rule is definitively not applicable to every subject.


## Shared verification catalog (schema 1.2)

New rules use a standard check selected from `GET /api/check-catalog`. The owned catalog defines a stable ID/version, semantic meaning, allowed subjects, verification method, required data and a strict parameter schema. AI and reviewers select from the same catalog. Unknown IDs, versions, extra parameters, incompatible units, or conflicting assertions are rejected. Availability is derived by the application, never supplied by the model or reviewer. Rule JSON, consuming-workflow responses and exports preserve the binding and parameters. Changing a definition's meaning requires a new version.

Initial entries:

| Check ID (version 1) | Method | Availability |
| --- | --- | --- |
| `package_measurement_limit` | Automatic | Implemented with the existing per-package unit-aware evaluator |
| `po_line_fulfillment` | Automatic | Not implemented |
| `carton_sku_limit` | Automatic | Not implemented |
| `label_placement` | Manual inspection | Human confirmation required |
| `asn_reconciliation` | Automatic | Not implemented |
| `document_confirmation` | External evidence | External confirmation required |

For PO fulfillment, `required_percent` is a positive percentage up to 100, `quantity_basis` is picked/packed/shipped, and `order_basis` is original_order/approved_current_order. Version 1 requires each PO line independently to reach **at least** the percentage. It does not prohibit overfills; that would be a separate requirement. A complete ordered-line set, stable line allocation, verified UOM conversions and authoritative approved revisions are required. Shortage on one line cannot be offset by excess on another. Substitutions cannot receive credit without explicit allocation. These inputs are not currently mapped into an executable fulfillment validator; a published requirement therefore reports Cannot determine, even if a snapshot contains an arbitrary fulfilled=true flag.

New shipment requirements without a matching catalog entry remain `standard_check: null` and `verification: unresolved`, labeled **Needs mapping**, and cannot be approved/published. New check types are added centrally, with versioned schemas and evaluator coverage. Unimplemented automatic checks require individual review; approval records acceptance of the requirement but does not make it executable. Applicable manual/external checks remain Cannot determine until their evidence/confirmation workflow exists. Applicability and exceptions still run before verification.

Schema 1.0/1.1 rules and published releases retain their existing behavior; no automatic semantic migration or approval changes are performed. The builder labels unmapped legacy verification explicitly and lets a reviewer map it through a normal audited edit. Existing custom expression checks stay editable until explicitly mapped. General guidance remains excluded from shipment checks. Catalog bindings may be retained when a rule is reclassified as guidance, but are not executed. Classification preserves schema 1.2 and its check binding.

Extraction prompt 1.6 supplies the catalog and requests schema 1.2. Ambiguous parameters (including whether "filled" means picked, packed or shipped) remain unmapped rather than guessed. Retained older provider responses remain readable through the legacy contract. Live-provider acceptance of the expanded schema requires a separately initiated analysis; local tests use mocked providers.

## Standard rule types and workflow delivery

The additive `rule_type` and `placements` fields normalize requirements across retailers. They are optional on existing schema 1.0–1.2 records; no saved rule, approval or release is silently migrated. The binding has an immutable catalog ID and version (`{"id":"carton.po_mixing","version":1}`), separate from the instance's stable release ID. A changed type meaning requires a new version. The shared verification binding continues to hold typed parameters (for example `carton_po_limit` v1 with `maximum_unique_pos: 1`). That new PO-count check is a contract only; its executor is not yet implemented.

`GET /api/rule-types` supplies labels, meaning, compatible subjects/checks, category, allowed workflow areas and conservative display defaults. The seed catalog covers carton contents, measurements, protection, physical labels/documents, pallet measurements/stacking/wrapping/labels, PO fulfillment, transport scheduling, ASN reconciliation/contents, EDI transmission, document confirmation and back-office requirements. Unsupported requirements remain unmapped. Catalog IDs do not depend on retailer wording. A type's allowed areas describe the workflows that actually use it, not every system providing data.

In **Edit rule → Rule type & workflow placement**, selecting a type supplies its category, default area and permitted checks. An incompatible prior check/custom assertion is cleared explicitly by this action; review the new verification before saving. The compact placement table configures:

- `workflow` and `area`: validated, predefined logical destinations. Multiple different areas are supported; the consuming app owns screen layout.
- `enabled`: includes/omits this placement from the new delivery API. Disabling does not waive, reject, delete or exclude the requirement from scenario checks. Disabled placements remain in the full JSON export and require individual review.
- `behavior`: `display`, `confirm`, `warn` or `block`. Display and confirmation do not imply compliance. Warnings/blocking require a supported automatic check; blocking additionally requires a required/prohibited obligation. Blocking configurations require individual review. Missing facts never imply success.

Instruction-only types with no compatible automatic/check contract can use human inspection or external evidence without inventing a numerical assertion. Such requirements remain `cannot_determine` in automatic scenarios. Types with a check contract still require that check before shipment-rule approval. Category and consuming workflows must agree with the mapping; use the full editor to change them together. All edits use the existing revision, approval invalidation and audit controls. Optional reviewer notes for approval remain unchanged.

New extraction prompt `routing-extraction-1.7` proposes rule types and **display-only** default placements using the same registry. It cannot invent catalog types or areas. The classification job can backfill missing type mappings on completed drafts. A match must support the existing subject and verification, and unmatched requirements stay unmapped. AI mappings still require human review. The catalog is a seed, not a claim of complete retailer coverage.

### Consumer contract

`POST /api/releases/{release_id}/delivery` is a read-only resolver for an explicitly selected immutable release:

```json
{
  "workflow": "mobile_packing",
  "area": "carton_selection",
  "rule_type": "carton.measurement",
  "snapshot": {
    "shipment": {},
    "cartons": [{"id": "c1", "weight": {"value": 51, "unit": "lb"}}]
  }
}
```

Only `workflow` is required. Omit `area`/`rule_type` to include all supported mappings in the workflow. `snapshot` uses canonical scenario facts, not raw ShipHero GraphQL responses. Subject-relative fields, explicit units and `shipment.*`/`evidence.*` retain evaluator semantics. Shipment/document/label/order subjects currently use the shipment context; carton/pallet/item subjects use their corresponding arrays. Missing or malformed subject collections return `needs_information`.

The result includes contract version, exact release ID, retailer, effective date, scope, full source-backed rules, type labels, placements and per-subject decisions. Each decision reports `applicability`, `action`, optional `check_outcome` and reason:

- Known-false conditions or known-true exceptions: `not_applicable` / `none`.
- Unknown conditions/exceptions or unresolved questions: `unknown` / `needs_information`.
- Applicable display/manual-confirmation placement: `display` or `confirm`, without a fabricated check result.
- Applicable automatic placement: failed check produces `warn` or `block`; pass produces `none`; missing/invalid evidence produces `needs_information`.

Consumers must handle `needs_information` explicitly; it is not permission to proceed. Confirmation capture, acknowledgement storage and enforcement inside a warehouse application are not implemented by this resolver. There is no silent winner among overlapping applicable variants; all are returned for the consumer. Conditional image variants keep their own applicability and original page/region evidence.

The response reports release-wide `unmapped_rule_ids` and `routing_complete`, as an unmapped rule's relevance cannot safely be inferred. It also counts disabled placements for the requested selection. An empty result is not evidence of no requirements if routing is incomplete. The existing `/rules?consumption_point=...` endpoint retains its prior classification-only behavior, including disabled placements; adopt `/delivery` to honor the new configuration. Full JSON/Markdown exports preserve both requirements and configuration.

Use **Changes & publish → Release history → Preview delivery** to inspect these decisions with pasted canonical facts. Synthetic examples are explicitly labeled. Previewing does not edit rules, record confirmations, or save a scenario. The local app remains single-user without authentication; IDs select releases, not tenant authorization. Shared deployment still requires authenticated scope enforcement; no production WMS/ShipHero integration was added here.

### General guidance and ignored proposals

Choose **Edit rule → Classification & workflows → Standard rule type → General guidance** for umbrella expectations such as “Shipments must arrive in excellent quality, on time and with proper documentation.” The stable ID is `general.guidance` v1. It sets rule use to general guidance and defaults to Supplier management / General guidance. This type is display only: no automatic checks or confirmation/blocking behavior. Concrete packing, timing and document requirements keep their specific types. Existing drafts are not silently reclassified.

Use **Ignore rule** in an expanded review row to remove a proposal from the pending queue and exclude it from publication. A reviewer name is required; a note is optional. **Status → Ignored → Restore to review** brings it back as pending, never approved, while the draft is unpublished. Ignoring preserves the source, revision and audit history, and does not resolve page coverage problems or retire a requirement in an existing release. Previously published releases remain immutable.

### Reviewing a rule in place

Expanding a row opens the editable review form beside the original evidence. The readiness list names missing fields and jumps directly to their inputs; affected sections open automatically. Review cautions and decision history are separate from approval blockers. The primary action becomes “Complete N items” when input is missing and takes you to the first item rather than appearing disabled without an explanation.

Corrections can be saved as a draft or saved and approved together. Save & approve validates the corrected rule and source in one transaction; failures leave the prior revision and decision intact. The audit note lists changed fields automatically. Approval alone requires no note. Unsaved changes must be saved or discarded before moving to another rule or ignoring/rejecting it. Reject opens a reason field only when needed. The API remains authoritative for full rule-contract and evidence validation.

## Rule verification and workflow visibility

The review list shows verification beside the rule title: Automatic, Manual, External confirmation, Not configured, or Guidance only. An unavailable automatic check is explicitly marked as unable to run. Workflow names wrap and include only enabled placements. Opening a rule shows its verification method, workflow areas and display/confirmation/warning/blocking behavior together, with direct links to edit each. Published instructions use the same summary.

Automatic classification can also fill missing standard rule types on existing completed drafts. It uses the shared type catalog, retains source evidence and existing executable checks, and applies display-only workflow defaults for new type assignments. Unknown or incompatible types remain unmapped with an explanation. Existing type assignments are preserved. The UI includes approved draft rules; changes to their rule metadata clear approval and return them to review. Published releases and incomplete extraction runs are not modified. Concurrent edits win through revision checks, and classifications retain provider/model provenance and audit history.

For Jev, open **Connections → Jev / TypeSafe**, save the API key and model (default `jev-1.14.0`), then choose **Classification provider → Jev / TypeSafe** in Review rules. Classification provider/model are separate from guide extraction. Starting classification sends existing rule text, applicability and source excerpts to the selected provider; saving a connection makes no provider request. Jev does not extract guides or perform scenario/photo verification in this integration, and it preserves existing verification settings.

The Jev adapter uses the [official System One endpoint](https://docs.typesafe.ai/api) and fixed Choice questions for purpose, category, catalog type and each workflow. All dimensions for one rule share a request, with at most four rule requests in flight. `unmapped` and uncertain workflow options avoid forced assignments. Full typed responses, probabilities, actual model and usage are retained with the saved classification batch; summaries describe selected values rather than inventing a model explanation. These probabilities are not treated as measured accuracy or used to auto-approve rules. Invalid/incomplete responses reject the batch. A failed batch can be resumed; no live Jev quality or speed comparison is implied by this integration.
