# Designing templates

[All guides](README.md) · [Project overview](../README.md)

A template is a reusable label design. Create the layout once, then fill in its variable fields—such as a name or description—each time you print. Start with text and a tape width; the advanced controls are optional.

The visual editor supports text, QR codes, linear barcodes, Data Matrix, Aztec
codes, images, rectangles, and lines. Drag,
resize, rotate in 90° steps, or enter dimensions in millimetres. Alignment,
layer ordering, duplication, snapping, and undo/redo are available.

## Arrange your design

Give elements an **Element name** to identify them in the element list, inspector,
and distance-holder selector. Names do not print. Rename, duplicate, and delete
controls are on the first inspector tab: Content for text, codes and images,
or Style for shapes.

## Personalize labels with variable fields

- Define text, number, boolean, or uploaded-image variable fields with defaults
  and sample values. Numbers can have minimum and maximum limits; text fields
  can have minimum and maximum lengths (up to 2,000 Unicode characters).
  Empty optional fields remain allowed. Use `{{name}}` in text or code content;
  bind image inputs through **Template logic**.
- **Preview inputs** stores up to 50 named examples with the template. Add,
  duplicate or delete examples and browse them with the previous/next controls.
  The selected example drives the canvas using current unsaved edits, including
  logic and automatic sizing. Choose **Sample values** to return to the normal
  editor samples. Examples share the template's access and revision history;
  they do not change submission defaults or queue any printing.
- **Template logic** provides connected nodes and an IDE-style **Source** editor
  for conditions, calculations, intermediate variables, and property bindings.
  **Reference** opens searchable documentation and examples. See the
  [template logic guide](TEMPLATE_LOGIC.md) for a conditional layout example.
- **Print resolution** chooses the printer default, Normal, or High. New jobs and
  CSV drafts save that choice; changing it later does not affect them.
- Text supports wrapping, alignment, padding on all four sides, and horizontal
  character and vertical line spacing in mm. Zero adds no extra spacing. Text and
  spacing shrink together to fit the box. Accents and joined characters stay
  together; right-to-left runs retain native shaping and character spacing.
- **Fit text box width to content** adapts width to each value. **Distance holder**
  keeps a fixed gap to another object's bounds. Text widths resolve first, then
  linked positions, then automatic label length. Circular links are rejected.
- **Automatic label length** fits content and margins within 10–300 mm; tape width
  stays fixed. Shorter automatic lengths are extended to 10 mm with a warning,
  which is retained in saved jobs and CSV drafts.
  **Ignore out-of-bounds objects** clips partial objects and omits
  fully outside objects while keeping them editable. New templates enable both;
  existing templates retain their saved settings.
- Individually cut PT-P710BT labels have a 24.5 mm minimum output length,
  including feed, regardless of tape width. Shorter designs need hand trimming
  and produce extra unused tape. New label previews and validated CSV drafts
  show affected copies and estimated extra tape. Activity preserves the output
  plan for each attempt, including interrupted prints. These are estimates,
  separate from normal feed and batch overhead.
- Queue **Details** and Activity **Details** show tape use split into **Design**,
  **Feed**, **Leader**, and **Unused**. Design excludes padding added by the 10 mm
  automatic-length minimum; that padding and any cutting-minimum padding belong
  to Unused. Feed covers both end margins of each label, while Leader is charged
  once per batch. Queue estimates cover remaining copies printed together;
  separate batches each need a leader. Saved attempt breakdowns remain estimates,
  even when a reviewer reports a different total consumed length.
- **Show print pixels** displays the exact 1-bit raster and is enabled by default.
  Turn it off for a smooth design preview. Tape colors change the preview colors,
  not the ink pattern. Rulers, cursor guides, and object outlines do not print.

## Save and reuse a template

Saving creates a template revision. Concurrent edits require a reload. Archiving
hides a template from new submissions; existing jobs and saved drafts retain
their layout, values, assets, dimensions, and resolution.

The editor's **Preview tape** choice and display colors are saved with the template.
Printing may use another compatible tape profile. Template cards load WebP
thumbnails stored under `data/cache/assets/template-previews`, generated on first view
and reused across requests and restarts. Saving a new revision invalidates its
thumbnail; missing or restored assets also refresh it. Retention cleanup purges
derived previews with deleted content. Older templates default to black on white.

## Choose templates and tape

On **New label** and **CSV runs**, **Change template** opens a searchable preview picker with
visibility, tape-width, media and destination-compatibility filters. Results are
paged in groups of 12. The six most recently chosen or submitted templates appear
first, saved per account in that browser; only currently accessible templates are
shown. Closing the picker without a selection preserves the label draft or CSV import.

The template editor, **New label**, and **CSV runs** share a **Change tape profile**
picker with color samples, search, width and media filters. Unavailable profiles
remain visible but cannot be selected. Users with **Manage tape profiles and
cartridges** can mark profiles unavailable or available again on **Tape profiles**.
Unavailable profiles cannot be used for new labels, print requests or CSV runs;
existing queued labels, saved runs and pending requests remain printable.
Existing templates retain their saved profile. Profile availability changes are audited.

## Adjust images

Image controls separate **Keep image proportions** (artwork fitting) from
**Lock box proportions** (linked width/height edits using the box's current ratio).
Selecting or uploading another image, including a replacement through logic,
leaves the box unchanged. **Fit box to image** appears when the ratios differ and
fits the box within its current bounds; dimensions controlled by logic must be
changed in the logic instead. **Image scale** ranges from 0.1 to 1 and centres the
artwork: 0.5 uses half the box's width and height. Logic can also set `image_scale`.
Existing templates render at scale 1 until changed.

## Design limits and scannable codes

Labels support up to 50 elements and 20 variable fields. Invalid layouts, missing
required values, unsupported glyphs, and code modules smaller than two device pixels
are rejected. QR codes have a four-module quiet zone by default. **Scale up to
bounding box** fills the box and allows an explicit **QR margin (mm)**; a blank
margin keeps the automatic quiet zone.

Linear barcodes support **Code 128**, **Code 39**, **EAN-13** and **EAN-8**, with
an optional caption. Code 128 accepts printable ASCII; Code 39 accepts uppercase
letters, digits and its standard punctuation. EAN accepts 12/7 digits and computes
the check digit, or validates a supplied 13/8-digit code. Quiet zones are retained
inside each code's box. Data Matrix and Aztec use square modules fitted inside
their boxes. Content can come from variables or logic. Verify a physical sample
with the intended scanner before relying on a new label design.

Code generation uses `python-barcode` and `zxing-cpp`, installed with the main
server dependencies. Companions continue to receive rendered output.

## Upload fonts and images

Noto Sans is bundled under the SIL Open Font License, with weights from Thin
(100) to Black (900). Text supports named and numeric weights. The **Fonts** page
accepts static and variable TTF/OTF files up to 5 MB and 20,000 glyphs. Variable
fonts use their supported weight range; other variation axes remain at their
defaults. Static uploads retain their actual weight; upload separate faces for
other weights or italics. Color/bitmap fonts, web fonts and collections are
unsupported. Existing Regular/Bold templates retain their appearance.

The **Images** page accepts PNG, JPEG, WebP, BMP, still GIF, and constrained SVG
files up to 5 MB. Bitmaps are limited to 16 megapixels and 8192 pixels per side.
SVG supports paths, basic shapes, and groups; convert text to paths. Scripts,
external resources, styles, embedded images, filters, and animation are rejected.
SVG limits are 200 KB, 1000 elements, and dimensions up to 8192. Export unsupported
SVGs as PNG.

## Share files

Both libraries accept multiple files at once, with individual results and retries
for failed uploads. Choose Personal, Group or Global for the batch; an item's
**Sharing** details can change its visibility afterward. Fonts and images have
separate upload and management permissions, independent of templates. Group
members can use shared items; creating, editing others' items and deleting others'
items each require the corresponding group permission. 

Use **Add image** in the editor or upload directly in its properties panel. Aspect
ratio is preserved by default. Brightness and contrast use 1 for unchanged
artwork. Threshold conversion suits logos; dithering provides tonal shading.
Transparent areas preserve content behind them.

## Hide, delete and restore files

Administrators see each uploaded font and image's owner in the library.
Hiding assets removes them from new selections while keeping saved labels usable.
Images can be renamed without changing their ID. Administrators can delete images,
fonts and templates even when saved work references them. Deletion removes them
from use immediately and retains their data for 30 days. Restore them under
**Administration → Deleted accounts and content** before the deadline; afterward,
maintenance permanently purges the retained data. Global deletion permissions
also permit removing referenced assets in that global library; other users may
delete only unused assets they can manage.

## Replace missing files

Templates that reference deleted assets show a notice and placeholders: a file
with a question mark for images, or **Aa** with a question mark in the top right
for fonts. Replace the missing assets or restore them before printing. Affected
queued jobs are paused; restoration does not automatically release their holds.
