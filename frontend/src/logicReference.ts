import { logicTargetLabel, type LogicCatalog } from './logicGraph'
import type { TemplateDocument } from './editor'
export interface ReferenceEntry {
  id: string
  title: string
  group: string
  summary: string
  details: string[]
  example?: string
}
const propertyHelp: Record<string, string> = {
  x: 'Left edge of the rotated bounding box in millimetres along the label. Lines use the edge of their stroke.',
  y: 'Top edge of the rotated bounding box in millimetres across the tape. Lines use the edge of their stroke.',
  width:
    'Horizontal extent of the rotated object in millimetres. Resizing keeps its top-left position fixed. For a vertical line this is its stroke thickness; assign stroke instead. Automatically measured dimensions cannot be overwritten.',
  height:
    'Vertical extent of the rotated object in millimetres. Resizing keeps its top-left position fixed. For a horizontal line this is its stroke thickness; assign stroke instead. Use visible = false to hide an object.',
  rotation:
    'Rotation in degrees: 0, 90, 180, or 270, keeping the top-left position fixed. Width and height follow the label axes, so quarter turns exchange the unbound extents.',
  visible:
    'Whether this object prints. Hidden objects do not extend automatic label length. Hidden distance-holder anchors have zero extent and no outgoing gap.',
  length_mm:
    'Explicit label length, from 10 to 300 millimetres, subject to the selected media. Disable automatic length before assigning this property. Invalid lengths never silently fall back to automatic sizing.',
  width_mm: 'Label tape width in millimetres. Read-only in logic.',
  auto_length: 'Whether automatic label length is enabled. Read-only in logic.',
  gap_mm:
    'Distance-holder gap in millimetres, from 0 to 300. Available only on objects with a distance holder; the holder resolves position after logic.',
  content:
    'Text or QR content. A bound string is literal: {{tokens}} inside its result are not expanded again. Unbound text can use input and intermediate names in {{name}} tokens.',
  font_size: 'Font size in millimetres, from 1 to 24.',
  character_spacing: 'Extra character spacing in millimetres, from 0 to 20.',
  line_spacing: 'Extra line spacing in millimetres, from 0 to 20.',
  bold: 'Enable or disable bold text.',
  wrap: 'Enable or disable line wrapping within the text box.',
  auto_width:
    'Fit text width to resolved content and typography before positioning logic. Configure this in Layout; it is read-only in logic.',
  align: 'Horizontal text alignment: "left", "center", or "right".',
  vertical_align: 'Vertical text alignment: "top", "center", or "bottom".',
  image_asset:
    'An uploaded image value, or null to clear the image. Use an image input or image("asset-id"). URLs and local file paths are not accepted. Asset permissions still apply.',
  preserve_aspect: 'Preserve the image’s aspect ratio when fitting it into its box.',
  image_scale:
    'Scale artwork inside its box from 0.1 to 1. A value of 0.5 uses half the width and height, centred in the unchanged box.',
  brightness: 'Image brightness multiplier, from 0 to 3; 1 leaves it unchanged.',
  contrast: 'Image contrast multiplier, from 0 to 3; 1 leaves it unchanged.',
  image_threshold: 'Integer threshold for monochrome conversion, from 1 to 255.',
  image_mode: 'Monochrome conversion mode: "threshold" or "dither".',
  qr_fill_box: 'Expand the QR code to fill its box.',
  qr_margin_mm: 'QR margin in millimetres, from 0 to 50. QR boxes must remain square.',
  stroke:
    'Line or rectangle stroke width in millimetres, from 0.1 to 3, no wider than the object’s dimensions.',
  filled: 'Fill a rectangle instead of drawing only its outline.',
  padding_top: 'Top text padding in millimetres, from 0 to 100.',
  padding_bottom: 'Bottom text padding in millimetres, from 0 to 100.',
  padding_left: 'Left text padding in millimetres, from 0 to 1000.',
  padding_right: 'Right text padding in millimetres, from 0 to 1000.',
}
const examples: Record<string, string> = {
  add: '2 + 3',
  subtract: '14 - 2',
  multiply: '3 * 12',
  divide: '24 / 2',
  negate: '-4',
  min: 'min(12, 14)',
  max: 'max(30, 20)',
  abs: 'abs(-2)',
  round: 'round(2.5)',
  less: '2 < 3',
  less_equal: '2 <= 3',
  greater: '3 > 2',
  greater_equal: '3 >= 2',
  equal: '2 == 2',
  not_equal: '2 != 3',
  and: 'true and false',
  or: 'true or false',
  not: 'not false',
  if: 'if(true, 12, 14)',
  filled: 'filled(0)',
}
export function referenceEntries(
  catalog: LogicCatalog,
  document: TemplateDocument,
): ReferenceEntry[] {
  const entries: ReferenceEntry[] = [
    {
      id: 'type:text',
      group: 'Variables',
      title: 'Text · circle',
      summary: 'Text inputs and string values.',
      details: [
        'Strings use double quotes and JSON escapes, up to 2000 characters. Empty or whitespace-only text is not filled. Text inputs keep their original whitespace.',
        'Sample values drive editor previews. Defaults prefill label forms and apply when a value is omitted. Required text must contain non-whitespace content.',
      ],
      example: 'let caption = "Cable rack";',
    },
    {
      id: 'type:number',
      group: 'Variables',
      title: 'Number · diamond',
      summary: 'Numbers for calculations and dimensions.',
      details: [
        'Numbers must be finite and between −1,000,000,000,000 and 1,000,000,000,000. Inputs can add minimum and maximum limits. Zero is a filled value.',
        'Use a decimal point; scientific notation is supported. A number has no implicit unit: dimension properties interpret it as millimetres. Missing optional numbers are null, not zero.',
      ],
      example: 'let spacing = 2.5;\nlet total = max(30, spacing * 12);',
    },
    {
      id: 'type:boolean',
      group: 'Variables',
      title: 'Boolean · square',
      summary: 'True/false values for conditions.',
      details: [
        'Use true and false without quotes. False is a filled value and is valid for required boolean inputs.',
        'Numbers and strings are not converted to booleans. Conditions require a present boolean; an optional boolean can be null. Use filled(value) to check presence.',
      ],
      example: 'let enabled = true;\nlet height = if(enabled, 12, 14);',
    },
    {
      id: 'type:image',
      group: 'Variables',
      title: 'Image · triangle',
      summary: 'Uploaded images used by image properties.',
      details: [
        'Choose or upload an image in the variable sample/default controls or the label form. Bind it to an image object’s image_asset property. Images cannot be interpolated into text.',
        'Source literals use image("64-character asset ID"). IDs identify uploaded assets, not URLs or paths. The current account must be allowed to use the asset. Null clears an image. CSV runs require an explicit cell-to-image mapping.',
      ],
    },
    {
      id: 'variables',
      group: 'Language',
      title: 'Intermediate variables',
      summary: 'Name a reusable calculated value with let.',
      details: [
        'Intermediate types are inferred. Names are case-sensitive, start with a letter, and contain up to 40 letters, numbers, or underscores. Names must not conflict with inputs, targets, or reserved language words.',
        'Declaration order does not matter. References must exist and cannot form a cycle. Intermediate declarations are evaluated even if no output uses them. Keep a potentially invalid expression inside an if branch when it should only run conditionally.',
      ],
      example:
        'let subtitleHeight = if(hasSubtitle, 2, 0);\nlet titleHeight = 14 - subtitleHeight;\nlet hasSubtitle = filled(subtitle);',
    },
    {
      id: 'source',
      group: 'Language',
      title: 'Source syntax',
      summary: 'Assignments, expressions, comments, and literal values.',
      details: [
        'End each declaration or property assignment with a semicolon. Use // for a line comment. Arithmetic, comparisons, and/or/not, parentheses, and the listed functions are supported. This is a small expression language, not JavaScript or Python.',
        'Assign output properties with target.property = expression. Read a property with the same target.property notation inside an expression. References use stable object IDs internally. Each property can be assigned only once.',
        'Code editing preserves comments and formatting when saved. Editing executable logic in Nodes regenerates canonical source; moving nodes or editing disconnected nodes keeps existing source text.',
        'Ctrl/Cmd+Z undoes typing. The template Undo/Redo controls restore committed changes across both editors. Invalid source stays in its draft, leaves the last valid preview intact, and blocks saving. Tab leaves the editor; completion uses Ctrl+Space and Enter.',
      ],
      example: '// A fixed title height\ntext1.height = 12;',
    },
    {
      id: 'property-inputs',
      group: 'Nodes',
      title: 'Property inputs',
      summary: 'Use another property’s logic result as a typed input.',
      details: [
        'Choose a Property target and Property in Add node, then Read property. The read node has a typed output that connects by click, drag, keyboard, or touch. Bind property creates an assignment instead.',
        'A read uses the result of the property’s binding, or its saved template value when unbound. Node and statement order do not matter. Dependencies can pass through intermediate variables; cycles, including self-references, are rejected.',
        'Automatic text widths include bound content and typography. Positioning expressions read those measurements. Unbound content is the saved text, including any {{tokens}}. label.width_mm and label.auto_length are read-only.',
        'Automatic label length is fitted after logic changes positions or visibility and is unavailable as a logic input. Disable automatic length to read or bind label.length_mm.',
      ],
      example:
        'let titleHeight = text1.height;\ntext2.height = titleHeight / 2;\ntext1.height = 12;',
    },
    {
      id: 'layout',
      group: 'Layout',
      title: 'Layout and automatic length',
      summary: 'Resolve text, measure it, position objects, then fit the final label.',
      details: [
        'The renderer resolves text content and typography, including their logic bindings, before measuring automatic widths. Positioning logic and distance holders then use those measurements. Finally it fits automatic label length and checks printable bounds.',
        'Automatic length uses visible objects and obeys media limits. Hidden anchors have zero extent. Geometry still requires positive widths and heights; hide objects with visible = false.',
        'Automatic text width and automatic label length have disabled assignment inlets. Source assignments to them are rejected. Manual node drafts are retained while automatic sizing is enabled. Queued labels keep their resolved layout and values even if the template later changes.',
        'Sizing expressions may use inputs and intermediate values, but cannot depend on unmeasured automatic dimensions, including indirectly through another object’s position.',
      ],
    },
    {
      id: 'connections',
      group: 'Nodes',
      title: 'Connections and navigation',
      summary: 'Connect values by clicking, dragging, or using the keyboard.',
      details: [
        'Click an output and an input, in either order, or drag between them. Focus connectors and press Enter/Space for the same interaction. Escape, a blank-canvas click, or selecting the same connector again cancels.',
        'Text connectors are circles, numbers diamonds, booleans squares, and images triangles. A hexagon represents an untyped absent or generic value; an empty image keeps its triangle. Polymorphic inputs such as Filled accept different types and adopt their connected value’s shape.',
        'Pan on blank canvas; use the wheel or zoom buttons to zoom. Frame nodes shows the graph. The Node picker frames one node, including on touch screens. Focus a node header and use arrow keys to move it; Shift moves farther.',
        'Configurable nodes have one Value type control above their inputs. It applies to both If branches or both Equal/Not equal operands. Disconnect the value inputs before changing it. Wires and type changes that would create incompatible inputs or outputs are rejected; null remains an absent value for optional branches and presence comparisons.',
        'Disconnected sockets use their editable default values. Disconnect removes a wire; Remove node removes that node and its wires. Disconnected anonymous nodes are editor drafts. Named intermediate nodes remain executable declarations.',
      ],
    },
    {
      id: 'errors',
      group: 'Language',
      title: 'Errors and limits',
      summary: 'Invalid types, cycles, missing values, and bounded evaluation.',
      details: [
        'A diagnostic marks the source location when available. Fix incompatible types, undefined names, duplicate outputs, or cyclic dependencies before saving. Unknown functions and arbitrary code are rejected.',
        'Runtime sample errors include missing required values, division by zero, invalid dimensions, and missing assets. Type-correct source can still fail for a particular input; check the preview and sample values.',
        'Limits include 20 inputs, 64 intermediates, 128 bindings, 512 expression nodes, 32 dependency levels, and 16,384 source characters. Shared graph values can expand to more than one expression when compiled.',
      ],
    },
    {
      id: 'example:conditional',
      group: 'Examples',
      title: 'Conditional subtitle',
      summary: 'For a text input subtitle and text elements text1/text2.',
      details: [
        'The title is 12 mm high with a subtitle and 14 mm without one. The subtitle keeps a positive height and is hidden when absent. Replace these names with the inputs and targets in your template.',
      ],
      example:
        'let hasSubtitle = filled(subtitle);\ntext1.height = if(hasSubtitle, 12, 14);\ntext2.height = 2;\ntext2.visible = hasSubtitle;',
    },
    {
      id: 'example:length',
      group: 'Examples',
      title: 'Calculated label length',
      summary: 'For a numeric input quantity, with automatic length disabled.',
      details: [
        'The result is clamped to the supported 10–300 mm range. Printer/media constraints still apply.',
      ],
      example: 'label.length_mm = min(300, max(30, quantity * 12));',
    },
    {
      id: 'example:guard',
      group: 'Examples',
      title: 'Guard a division',
      summary: 'Only evaluate division when the denominator is nonzero.',
      details: [
        'Use a number input quantity with a present value. Both branches must have compatible types, but only the selected branch is evaluated.',
      ],
      example: 'let perItem = if(quantity == 0, 0, 100 / quantity);',
    },
  ]
  for (const operation of catalog.operations)
    entries.push({
      id: `operation:${operation.name}`,
      group: 'Operations',
      title: operation.name,
      summary: operation.description,
      details: [
        `Arguments: ${operation.minimum_arguments}. ${operation.signature === 'numeric' ? 'Accepts present numbers and returns a number.' : operation.signature === 'comparison' ? 'Accepts present numbers and returns a boolean.' : operation.signature === 'boolean' ? 'Accepts present booleans and returns a boolean.' : operation.signature === 'conditional' ? 'Accepts a boolean condition and two compatible values; only the selected branch runs.' : operation.signature === 'equality' ? 'Compares compatible types or tests against null; returns a boolean.' : 'Accepts any value; null and blank text are absent, while zero and false are present.'}`,
      ],
      example: `let result = ${examples[operation.name]};`,
    })
  for (const [name, summary] of Object.entries(propertyHelp)) {
    const targets = Object.entries(catalog.targets)
      .filter(
        ([, target]) =>
          Object.hasOwn(target.properties, name) ||
          Object.hasOwn(target.readable_properties ?? {}, name),
      )
      .map(([alias]) => logicTargetLabel(document, alias))
    entries.push({
      id: `property:${name}`,
      group: 'Properties',
      title: name,
      summary,
      details: targets.length
        ? [`Available targets in this template: ${targets.join(', ')}.`]
        : ['Available on the corresponding element type; add that element to bind this property.'],
    })
  }
  for (const field of document.fields)
    entries.push({
      id: `input:${field.name}`,
      group: 'Template inputs',
      title: field.name,
      summary: `${field.label} · ${field.type ?? 'text'}${field.required ? ' · required' : ' · optional'}`,
      details: [
        'Define samples, defaults, and input limits in Variable fields below the workspace.',
      ],
    })
  return entries
}
