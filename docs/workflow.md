# Using routing-guide-parser locally

## From upload to validated scenario

1. Upload an original PDF and wait for **Pages ready**. Text-free pages are retained as images. Fix actual preparation failures before analysis.
2. Open **Connections**, choose Claude or OpenAI, and save a provider API key and exact vision-capable model ID. A saved credential is not a verified connection. Credentials are stored in the Docker documents volume in a mode-0600 file, never returned by the API or added to Git. Blank key fields retain the existing key; Remove clears the override, including environment fallback for that connection.
3. Choose the provider/model and **Analyze guide**. This sends guide text and rendered page images to the selected provider. Every target page gets a coverage result. All extracted document text accompanies each batch for cross-references. Start with 12 pages per batch; request/output limits split batches, never silently omit pages. If even a one-page request cannot fit the full text context, the run stops visibly and must be retried with a larger-context model. Analysis has three bounded attempts for transient failures. Completed batches persist. Cancel stops remaining work after the current provider call returns; it cannot undo incurred provider charges.
4. Alternatively, **Start manual review** to create source-backed rules without a model. Every page starts unresolved and needs a recorded coverage decision. Manual runs are never presented as AI analysis.
5. Enter your reviewer name. Review proposed instructions, scope, exceptions, automatic checks and evidence beside original page images. Edit as needed, then approve or reject each exact revision with a note. Saving an edit clears the approval. Review unresolved page coverage and analysis notes. Text citations must match the cited page after conservative whitespace, case and typography normalization; words, numbers and meaningful punctuation are preserved. Unmatched citations are retained in pending proposals with source-review flags instead of aborting a batch. Flagged proposals cannot be approved until edited to valid evidence, and may be rejected without repairing their evidence. Their page coverage remains unresolved until a separate review decision. No automatic conversion to visual evidence occurs; visual citations require human verification.
6. In **Changes & publish**, give the release an explicit effective date, coverage/scope and publication notes. For each rule in the active release, select retain, replace with a distinct approved candidate, or retire. Retention keeps its old evidence. Replacement preserves stable identity. An unmatched approved candidate becomes a new rule. Absence never implies retirement. The comparison shows content fields and old/new evidence; this is a reviewer-controlled comparison, not an autonomous semantic merge.
7. Preview the effect on saved scenarios and acknowledge coverage and impact. Publish an immutable release. A concurrent change to the draft or active release blocks stale publication. Download structured JSON or Markdown instructions. Restoring an older active release preserves all history; explicit release selection remains available for evaluations.
8. In **Scenarios**, paste canonical JSON or a wholesale order containing `packing_layout`. Save an immutable snapshot. Optional overrides replace named top-level fields and are retained separately. Choose an exact release and run deterministic checks. Results show pass, fail, cannot determine or not applicable for each subject. Prior evaluations stay pinned to their release.
9. To fetch ShipHero data, save an access token in Connections, choose the appropriate retailer, and enter a public wholesale order ID. Fetch & save performs one read-only query and records source/account/time. The import excludes names, email, phone, billing and payment data. It includes postal destination fields needed for rules; snapshots can still contain business-sensitive information. Tokens are refreshed manually. There are no ShipHero mutations.

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
