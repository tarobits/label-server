# Template logic implementation plan

Status: language, backend integration, typed input forms, the visual node workspace,
IDE-style source editing, and searchable reference are implemented. Version 1
remains supported; typed variables or saved node edits upgrade a template to
version 2. Automated regression checks are complete. Physical phone/tablet and
printer verification remain; no release is prepared.

## Agreed scope

- Text, number, boolean, and uploaded-image inputs, with defaults, samples, and
  required/optional settings. Numbers support minimum and maximum values.
- Named, reusable intermediate variables with inferred types.
- A Blender-style node workspace and an IDE-style source editor backed by the same
  validated program. Editing either representation preserves the other.
- Bindings for element properties, visibility, and explicit label length. Automatic
  label length remains available and runs after conditional layout is resolved.
- Live preview with sample inputs, undo/redo, and actionable diagnostics.
- Searchable, openable reference documentation and contextual node/function help.
- Equivalent behavior in previews, direct submissions, CSV runs, approval requests,
  saved queue entries, and retries.

## Language and document design

Version 1 documents continue to render unchanged. Version 2 will introduce typed
inputs and a data-only expression tree: literals, references, and whitelisted
operations. Intermediate variables form a directed acyclic dependency graph.
Property bindings are outputs; they cannot read other output properties. Duplicate
outputs, undefined references, circular dependencies, and incompatible types are
errors. Branches must have compatible types; conditions must be booleans.

Example source:

```text
let hasSubtitle = filled(variable1);
let subtitleHeight = if(hasSubtitle, 2, 0);
let titleHeight = 14 - subtitleHeight;

text1.height = titleHeight;
text2.height = 2;
text2.visible = hasSubtitle;
label.length_mm = max(30, itemCount * 12);
```

Element aliases such as `text1` are unique editor identifiers, separate from display
names. Compiled output bindings reference stable element IDs. Renaming an alias
must preserve those IDs and update source references. Graph positions and selection
are editor metadata, separate from executable logic. Source formatting round-trips
through the same expression tree; graph node identity/layout reconciliation belongs
to editor integration, not runtime evaluation.

Initial operations: arithmetic, numeric comparisons, equality, boolean operations,
`if`, `filled`, `min`, `max`, `abs`, and `round`. Optional inputs use `null` for an
absent number/image; `0` and `false` are present values. Text containing only
whitespace is empty. Evaluation is bounded and uses no Python/JavaScript execution,
loops, imports, network access, or file access. Errors include source positions
when available. The operation catalog supplies editor completion and help metadata.

Image values are structured asset references, not URLs or file paths. Uploading uses
the existing asset service. Asset authorization, reference retention, and deletion
checks must cover input defaults/samples, literals, and submitted values before the
renderer receives them. CSV image columns use explicit mappings to uploaded assets;
there is no automatic downloading of URLs or reading filesystem paths.

## Layout semantics

1. Validate and resolve typed inputs.
2. Evaluate intermediate values and property bindings.
3. Validate final element properties and applicable geometry constraints.
4. Resolve text sizing and distance holders.
5. Compute automatic label length, when selected, from visible elements.
6. Apply printable-area checks and render.

Visibility is explicit: hidden elements do not print or extend automatic length.
Zero dimensions remain invalid for visible elements. Hidden anchors collapse to
their resolved origin, with no extent or outgoing spacing; chains retain their
dependency order. Cover this behavior with layout examples before exposing it in
the editor.

Explicit label-length bindings and automatic sizing are mutually exclusive modes.
Switching modes preserves the inactive binding in editor draft state, but executable
documents must have one unambiguous mode. Invalid explicit lengths produce errors;
they do not silently activate automatic sizing. Existing media limits still apply.

Submission freezes resolved geometry, typed input values, and asset references.
Queued work and retries must never reevaluate against an edited template or new
defaults. Existing ownership, approval attribution, and usage accounting remain intact.

## Editor interactions and accessibility

- Pan/zoom, search-to-add, typed sockets, reusable named-value references, live values.
- Drag connections or click one socket and then a compatible socket. Escape,
  clicking blank canvas, or clicking the selected socket again cancels.
- Keyboard focus plus Enter/Space supports the same connection workflow. Announce
  selection, compatibility, connections, and errors to assistive technology.
- Text sockets: circles; numbers: diamonds; booleans: squares; images: triangles.
  Colors supplement shapes. Inputs are on the left; outputs on the right. Outlines,
  labels, and symbols communicate state without relying on color.
- Source editing includes line numbers, syntax highlighting, autocomplete, hover
  information, inline diagnostics, and help links. Invalid source stays in a draft;
  it must not overwrite the last valid graph or become printable.
- Keep the label preview alongside the workspace on desktop/tablet. Provide an
  expanded editing view on smaller screens. Reuse project transitions and dialogs.
- Reference entries cover every input type, node/function, bindable property,
  layout rule, error, and interaction, with copyable examples.

## Implementation milestones

1. **Language foundation — complete.** Standalone typed input models, bounded
   parser, serializable expression tree, dependency/type validation, evaluator,
   source formatter, operation catalog, and focused regression tests. No HTTP
   endpoints or template-format changes until integration is ready.
2. **Rendering and persistence — complete.** Introduce version 2 alongside version 1; resolve
   visibility/layout and label length; freeze submissions; validate image access;
   cover direct, image, CSV, and approval submission paths. Preserve legacy retries.
3. **Typed variable forms — complete.** Definition/sample editors, number/boolean/image inputs,
   CSV conversions with row-level errors, and existing image-upload/library controls.
4. **Node workspace — complete.** Shared program representation, stable IDs, canvas, node search,
   click/drag/keyboard connections, connector shapes, undo/redo, preview inspection.
5. **Source workspace and reference — complete.** IDE editor, completions, diagnostics,
   bidirectional graph/source synchronization, searchable and contextual help.
6. **End-to-end validation — automated checks complete.** Cross-editor equivalence,
   simulated narrow-screen/touch interactions, keyboard access, ownership/asset
   boundaries, saved jobs/retries, and user documentation are checked. Physical
   phone/tablet editing and representative printed labels still need verification.
   Prepare release notes and logical commits, and publish, only when requested.

## Acceptance checks

- The conditional subtitle example produces matching layouts with empty and filled
  inputs, in both editors, previews, CSV rows, approved submissions, and print jobs.
- Shared intermediate values evaluate consistently regardless of declaration order;
  cycles and undefined names give useful errors.
- Zero/false, missing values, Unicode text, image inputs, and invalid numeric values
  have explicit, tested behavior. Both branches are type-checked; evaluation of `if`,
  `and`, and `or` short-circuits at runtime.
- Invalid types, division by zero, excessive nesting/size, unknown operations, and
  unsupported syntax cannot execute code or cause unbounded work.
- Graph/source round trips preserve semantics. Failed edits retain the last valid
  graph and remain recoverable. Layout metadata survives unrelated source edits.
- Explicit and automatic lengths respect printer/media limits and conditional
  visibility. Hidden distance-holder chains have deterministic placement.
- Image references cannot bypass account permissions or disappear from retention
  checks. An uploaded image is not made globally visible by using it in a label.
- Template changes after submission do not change printing or reprinting. Historical
  version 1 templates and jobs retain their existing rendering behavior.

## Progress log

- 2026-11-04: Recorded the agreed scope and implementation sequence. Started the
  standalone language foundation; renderer and editor integration are pending.
- 2026-11-04: Completed the initial language core in `app/logic_schema.py`,
  `app/logic_engine.py`, and `app/logic_source.py`. The operation catalog, typed
  input resolution, serializable program, parser/formatter, type inference,
  lazy conditionals, stable target IDs, and source/node diagnostics are implemented.
  Dependency limits are independent of declaration order; graph programs must
  also fit the source editor's size budget. All 105 focused regression tests,
  strict type checks, and lint checks pass. This is not yet connected to the
  renderer, submission APIs, or editor UI. Milestone 2 is next.
- 2026-11-04: Completed renderer and submission integration. Version 2 resolves
  typed inputs, intermediate variables, element bindings, visibility, and label
  length before layout. Queued snapshots contain literal content and resolved
  geometry with the original program removed; normalized inputs are preserved.
  Direct submissions, CSV runs, approval requests, and retries use these snapshots.
  Image input references are authorized before rendering, rechecked before saving,
  and included in saved-document access and retention checks. CSV parsing supports
  typed numbers/booleans and explicit uploaded-image mappings with row-level errors.
  Added 18 integration tests; existing rendering/layout/access regressions and the
  105 core tests pass. Strict mypy checks pass; Pyright reports no errors in the
  new logic/template modules. Milestone 3 is next. No database migration is needed
  for this milestone because template documents and job payloads already use JSON.

- 2026-11-04: Added typed variable definitions, sample/default controls, numeric
  limits, and image upload/library selection in the template editor. Non-text
  types upgrade legacy documents with unique element aliases; undo restores the
  previous format and values. Renames update text tokens and logic references;
  duplication/removal maintains output bindings. Submission forms preserve zero,
  false, and absent optional values. CSV runs map distinct image cells to uploaded
  assets and display typed values in saved drafts. The production frontend build
  and targeted browser regressions pass; desktop/mobile screenshots and opening/
  closing numeric-limit disclosures were checked. Milestone 4 is next. Logic
  binding authoring still requires the API until the node/source workspaces land.

- 2026-11-04: Added the collapsible node workspace with pan/zoom, expandable view,
  searchable operations/constants, named intermediate nodes, property outputs,
  and a label preview. Connections support clicks, dragging, Enter/Space, and
  touch; incompatible sockets and cycles are rejected. Connector shapes identify
  text, number, boolean, and image values independently of color. A node picker
  frames individual nodes on narrow screens. Graph edits share template undo/redo;
  invalid drafts block saving and retain the last valid preview. Bounded editor
  metadata preserves node positions and unfinished nodes independently of the
  executable program and is removed from queued snapshots. Anonymous expressions
  remain inline, preserving short-circuit evaluation. Automatic sizing keeps an
  inactive manual-length output for reuse. Server inspection supplies operation
  and property metadata and enforces image access, including detached image nodes.
  Production build, type/lint checks, targeted browser workflows, and 137 backend
  logic/integration/access tests pass. Milestone 5 is next.

- 2026-11-04: Completed the source workspace with lazy-loaded CodeMirror, line
  numbers, syntax highlighting, completions, hover help, search, and diagnostics.
  Source compilation reuses stable node IDs and preserves matching positions,
  detached draft nodes, and inactive manual length. Invalid source blocks saving
  and retains the last valid graph/preview. Source and node edits share template
  undo/redo; comments survive source saves and non-executable graph changes.
  Added searchable reference entries, contextual help, copyable examples, and a
  [user guide](TEMPLATE_LOGIC.md). Desktop previews sit beside source; narrow
  screens wrap code and stack the preview. Opening/closing reference and editor
  disclosures, completion insertion, error focus, and save/reload are covered by
  browser tests. All 1,121 backend tests pass, including source diagnostics and
  image-authorization checks; frontend build, strict Python checks, and lint pass.
  All 55 targeted browser tests pass across source/node/typed-input workflows,
  existing editor/history/permission behavior, motion, and keyboard accessibility.
  The checks caught and fixed submission-error focus being lost while typed fields
  were disabled; the account tab-order test now waits for asynchronously loaded
  controls and includes the existing push settings. Desktop/mobile screenshots
  were reviewed. Physical device/print verification remains before release.

## Implemented version 2 API contract

- Set `document.version` to `2`. Each element has a unique `logic_name`, separate
  from its stable `id`; `label` is reserved. Version 1 remains the default.
- Fields accept `type`: `text`, `number`, `boolean`, or `image`. `default` and
  `sample` use that type; missing optional values are `null`. Number limits are
  `minimum` and `maximum`. Plain legacy text-field definitions are also accepted
  in version 2, subject to the logic language's reserved names.
- `document.logic` stores the validated `Program` expression tree. Binding targets
  are stable element IDs, or `label` with property `length_mm`. The parser and
  formatter translate source aliases to/from those IDs. `/api/logic/inspect`
  validates a document and returns the operation/target catalog, inferred variable
  types, sample values/errors, and source text. `/api/logic/compile` accepts
  `{document, source}` and returns either `{valid: true, program, formatted,
  catalog, diagnostics: []}` or `{valid: false, diagnostics}`. Diagnostics include
  UTF-16 `from`/`to` offsets and one-based line/column positions. Both endpoints
  require authentication, enforce image access, and do not save a template.
- Submission and preview `data` contains JSON strings, numbers, booleans, `null`,
  or image values shaped as `{"image_asset": "<uploaded asset ID>"}`. Numbers and
  booleans are not silently converted from strings outside CSV processing.
- CSV numbers use a decimal point; booleans accept `true`, `false`, `1`, or `0`
  (case insensitive). Blank non-text cells mean absent values. Unmapped fields
  use their defaults. `image_mapping` maps variable names to CSV cell values and
  structured image references, for example
  `{"photo": {"portrait.png": {"image_asset": "<uploaded asset ID>"}}}`.
- Submitted version 2 documents have `logic: null` and literal element content.
  Automatic sizing and distance holders are resolved before saving. The
  `literal_content` marker ensures user text containing `{{...}}` is not interpreted
  again during retries. Input values are retained separately for history.
- Binding results still obey element and media constraints. Visibility hides an
  element without requiring zero dimensions; dimensions retain their existing
  positive-value constraints. Hidden anchors have zero extent and no outgoing gap.
- Template library dimensions report input-dependent lengths when logic can affect
  label length. Typed values in saved-job details have human-readable text, with
  image inputs represented as uploaded images.

- Optional `logic_editor` metadata contains a versioned, bounded node graph and
  viewport, plus optional source text. Source is reused only when it compiles to
  the saved program; comments and formatting survive source edits and node moves.
  Changes to executable node logic regenerate canonical source. Only `logic`
  executes; metadata is excluded from rendering and queued
  snapshots. Browser loading checks graph/program equivalence before reusing it.
  Literal image references in metadata still require asset authorization.
