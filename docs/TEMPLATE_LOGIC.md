# Template logic

Open a template and expand **Template logic**. **Nodes** and **Source** edit the
same program; the preview uses the sample values in **Variable fields**.
**Reference** contains searchable entries for every input type, operation,
bindable property, and layout rule, with copyable examples. A selected node's
**Node reference** button and source hover cards open the relevant entry.

## Inputs and intermediate values

| Type | Values | Connector |
| --- | --- | --- |
| Text | Double-quoted strings; empty or whitespace-only text is not filled | Circle |
| Number | Finite numbers, with optional input minimum/maximum limits | Diamond |
| Boolean | `true` or `false`; false is a present value | Square |
| Image | An uploaded image chosen through the image picker | Triangle |

Inputs have names, labels, defaults, samples, and required/optional settings.
Zero and false are valid required values. Missing optional numbers, booleans,
and images are `null`; check presence with `filled(value)`. Images keep their
existing account/group permissions. They cannot be used as text tokens.

Use **Intermediate variable** nodes or `let name = expression;` to name calculated
values. Types are inferred. Declaration order does not matter, but cycles and
undefined references are rejected. All named intermediate declarations are
evaluated; keep a potentially invalid calculation inside a conditional branch
when it should only run in that branch.

## Conditional subtitle example

Create an optional text input named `subtitle` and two text elements with valid
positions and positive widths/heights. Logic assigns element aliases such as
`text1` and `text2`; use the aliases shown in source completion or the node
picker's **Property target** list. Put `{{subtitle}}` in the second element's
content. For aliases `text1` and `text2`, enter this in **Source**:

```text
let hasSubtitle = filled(subtitle);
text1.height = if(hasSubtitle, 12, 14);
text2.height = 2;
text2.visible = hasSubtitle;
```

The title is 12 mm high when a subtitle is filled, and 14 mm otherwise. The second
text element is hidden when empty. Use visibility to hide an element: zero height
is invalid. Hidden elements do not extend automatic label length.

In **Nodes**, connect the Subtitle input to **Filled**, then to an intermediate
named `hasSubtitle`. Connect that value to **If → Condition**, set Then to 12 and
Else to 14, and connect If to a `text1.height` output. Connect `hasSubtitle` to a
`text2.visible` output. Set the second element's height to 2 mm in the inspector
or with a `text2.height` output.

Click two compatible endpoints, in either order, to connect them, or drag between
them. Keyboard users can focus endpoints and press Enter/Space. Escape, a blank
canvas click, or clicking the selected endpoint again cancels. Connector shapes
identify types independently of their colors. The Node picker frames individual
nodes on smaller screens.

Configurable nodes have one **Value type** control above their inputs, with no
per-input type selectors. It sets both If branches or both Equal/Not equal
operands together; If’s condition stays boolean. Set the type before connecting
value inputs; disconnect those inputs to change it. Incompatible
connections are rejected immediately, including changes that would invalidate
later nodes or property outputs. Optional branches and equality checks can still
use `null` to represent an absent value.

## Label length and other properties

Automatic text sizing uses resolved content and typography, including logic bindings.
Positioning logic then reads the measured sizes. After logic, distance holders are
positioned and automatic label length is fitted to the final visible layout,
followed by printable bounds checks. Bindings can change geometry, visibility, content, text style,
image settings, and other properties listed in Reference. Units and allowed
ranges are documented per property.

In Layout and logic, `x` and `y` identify the rotated bounding box's top-left
corner. `width` is its horizontal extent on the label; `height` is its vertical
extent. Resizing one dimension preserves the other and the top-left position.
At 90° and 270°, these dimensions exchange the object's local text axes.
Automatic text sizing protects the dimension along the text: `height` for
quarter-turned text, otherwise `width`.

Lines have **Length**, **Stroke**, and **Direction** controls. They can be added
directly as horizontal or vertical lines. Their bounds follow the actual stroke,
without an empty surrounding rectangle. Logic changes a horizontal line's length
through `width`, or a vertical line's length through `height`; use `stroke` for
thickness. Assigning the cross-axis dimension is rejected.

Existing saved prints retain their stored rendering geometry. Review existing
logic that positioned or resized rotated objects using the old unrotated axes.

Properties can also supply inputs. In **Add node**, choose a **Property target**
and **Property**, then **Read property**. Its typed output connects to operations,
intermediates, and property bindings. In Source, use `target.property` in an
expression:

```text
let halfHeight = text1.height / 2;
text2.height = halfHeight;
text1.height = 12;
```

Here `text2.height` becomes 6 mm, even though the assignment to `text1.height`
appears last. A bound property supplies its logic result; an unbound property
supplies its saved template value. Self-references and indirect cycles through
properties or intermediate variables are rejected.

Reads of automatic dimensions use the resolved text measurements. Automatic
label length is fitted afterward, so moving or hiding objects still changes
the final label length. It is unavailable as an input while automatic length is
enabled. Disable automatic length to read or bind `label.length_mm`. `label.width_mm` and
`label.auto_length` are read-only inputs.

When **Fit text width** or **Automatic label length** is enabled, its assignment
inlet is disabled and source assignments are rejected. Disable the automatic
setting before assigning that dimension. Automatic text width itself is configured
in Layout, not through logic. Its measurement includes bound content, bold text,
font size, spacing, padding and height, as well as intermediate text tokens.
Sizing expressions cannot depend on an unmeasured automatic dimension, including
indirectly through another object's position. Such dependencies are rejected.
Unbound `content` inputs return the stored string, including any `{{tokens}}`.

Named objects appear as **Name (technical identifier)** in property pickers and
source completion; graph nodes include the property in parentheses. Renaming an
object does not change the technical identifiers or rewrite expressions.

For a number input `quantity`, disable **Automatic label length** and assign:

```text
label.length_mm = min(300, max(30, quantity * 12));
```

Automatic sizing and an explicit length binding are mutually exclusive. Switching
to automatic sizing retains the inactive manual-length node for reuse. Automatic
sizing still measures the resolved visible layout. Invalid calculated lengths
produce errors rather than silently switching modes; media constraints still apply.

## Source editing and recovery

The source editor provides line numbers, syntax highlighting, completion with
Ctrl+Space, hover help, search, and inline diagnostics. Every declaration or
assignment ends with a semicolon. `//` starts a line comment. This is a bounded
expression language; it cannot run Python, JavaScript, imports, or network requests.

Source edits preserve comments and formatting. Changing executable logic in Nodes
regenerates canonical source; moving nodes or editing detached anonymous nodes
preserves the source text. Matching nodes keep their positions when source changes.

Invalid source remains a draft, keeps the last valid preview, and blocks saving.
Correct the diagnostic or choose **Revert source changes**. While source is invalid,
node editing is disabled. Invalid node changes similarly require correction or
reversion before editing source. Runtime sample errors can still occur in a
well-typed program, for example division by zero or invalid final geometry.

Ctrl/Cmd+Z undoes typing. The template **Undo** and **Redo** controls restore valid
changes across both editors. Saving creates the usual template revision. Unsaved
and invalid drafts are not persisted by reloading the page.

## Submissions and compatibility

New-label forms preserve numeric and boolean values and accept uploaded images.
CSV imports convert numeric and boolean columns and require explicit cell-to-image
mapping. Every selected row must validate before a run can be saved.

Submissions freeze resolved layout, typed inputs, and asset references. Later
changes to a template or its defaults do not alter queued work or retries. Editor
nodes and source drafts are omitted from printable snapshots.

Existing version 1 templates remain supported. Typed fields or saved logic edits
upgrade a template to version 2; older server versions cannot read that format.
No new database migration is required for template logic itself. Keep a database
backup before rolling back to a server without version 2 support.

Templates using property-input expressions require a server that supports this
feature; earlier version 2 implementations cannot read those expressions.
Automatic text sizing now precedes logic. Review templates that previously relied
on logic changing text or font settings before automatic width measurement.
