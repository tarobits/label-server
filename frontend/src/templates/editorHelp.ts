import { t } from '../shared/i18n'
import type { SettingExplanation } from '../components/SettingHelp.vue'

export const editorHelp = {
  autoLength: {
    get title() {
      return t('templateEditor.automaticLabelLength')
    },
    text: 'Changes how much tape the whole label uses to fit its visible objects, from 10 to 300 mm. It does not resize text boxes. Fixed-size labels cannot use this option.',
    related:
      'To make a text box grow with its text, select the text and open Layout → Fit text box width to content (height when rotated). Both settings can be used together.',
  },
  autoWidth: {
    title: 'Fit text box to content',
    text: 'Grows or shrinks this text box to fit its current text, including variable values and logic. Text does not wrap in this mode. For rotated text, the fitted dimension is height.',
    related:
      'Automatic label length adjusts the entire label. Font size controls the maximum letter size; text can still shrink to fit the box’s other dimension.',
  },
  length: {
    get title() {
      return t('templateEditor.labelLengthMm')
    },
    text: 'The physical length of the whole printed label along the tape. This is calculated when automatic length or a logic binding controls it, and fixed by the media for fixed-size labels.',
    related: 'An object’s Width and Height only change its own bounding box.',
  },
  resolution: {
    get title() {
      return t('templateEditor.printResolution')
    },
    text: 'Chooses the printer raster resolution used to render this template. Printer default follows the design destination’s default; Normal or High selects a supported mode explicitly.',
    related:
      'Zoom only magnifies the editing canvas. Show print pixels lets you inspect the raster at the selected resolution.',
  },
  profile: {
    get title() {
      return t('common.tapeProfile')
    },
    text: 'Sets the design’s tape width, preview colors and media compatibility. Fixed-label profiles also set the exact label length.',
    related:
      'This does not install a cartridge. The cartridge used for printing must match the design’s media requirements.',
  },
  destination: {
    get title() {
      return t('templateEditor.designDestination')
    },
    text: 'Chooses the printer or printer group whose capabilities and printable area are used while designing.',
    related: 'The print destination is chosen separately when submitting labels.',
  },
  visibility: {
    get title() {
      return t('common.templateVisibility')
    },
    text: 'Personal templates belong to your account; User group shares with the selected group; Global makes the template available across the installation, subject to permissions. Sharing includes saved revisions.',
    related: 'Visibility does not grant permission to edit the template or use a printer.',
  },
  clipping: {
    get title() {
      return t('templateEditor.ignoreOutOfBoundsObjects')
    },
    text: 'Allows rendering when objects extend beyond the printable guides. The parts outside are cut off in the printed result.',
    related:
      'This does not move or shrink objects to make them fit. Turn it off to catch out-of-bounds errors.',
  },
  pixels: {
    get title() {
      return t('common.showPrintPixels')
    },
    text: 'Shows the device raster instead of the smooth design preview, so you can inspect pixel edges and image dithering. It does not change the print.',
  },
  snap: {
    get title() {
      return t('common.snap05Mm')
    },
    text: 'Snaps canvas dragging and resizing to half-millimetre steps. Use the numeric position and size fields for finer control.',
  },
  bounds: {
    get title() {
      return t('templateEditor.objectBoundaries')
    },
    text: 'Shows the bounding boxes of unselected objects on the canvas. These guides are not printed.',
  },
  fontSize: {
    get title() {
      return t('templateEditor.fontSizeMm')
    },
    text: 'The maximum size of the text. The renderer reduces it when needed to fit inside the text box.',
    related:
      'Fit text box to content changes the box’s size instead. Wrap text allows multiple lines within a fixed box.',
  },
  wrap: {
    get title() {
      return t('common.wrapText')
    },
    text: 'Allows text to continue on another line when it reaches the box’s width.',
    related:
      'Fit text box to content disables wrapping and fits the box to the text instead. Explicit line breaks in the content are still respected.',
  },
  characterSpacing: {
    title: 'Character spacing',
    text: 'Adds space between letters. Zero uses the font’s normal spacing; added gaps shrink when the text shrinks to fit.',
    related: 'Padding adds space at the edges of the text box instead of between letters.',
  },
  lineSpacing: {
    title: 'Line spacing',
    text: 'Adds space between lines of text. Zero uses normal line spacing; added gaps shrink with the text.',
    related: 'Padding reserves space between the text and the box’s edges.',
  },
  padding: {
    title: 'Text padding',
    text: 'Reserves space inside the text box at each edge. Less room remains for text; automatic text width includes the left and right padding.',
    related:
      'Character and line spacing change the gaps within the text. Distance holders set gaps between separate objects.',
  },
  imageProportions: {
    get title() {
      return t('templateEditor.keepImageProportions')
    },
    text: 'Fits the image inside its box without stretching it. Unused space may remain. Turn this off to stretch the image to the box’s shape.',
    related:
      'Lock box proportions controls resizing the box itself. Swapping an image, including through logic, does not resize the box.',
  },
  boxProportions: {
    get title() {
      return t('templateEditor.lockBoxProportions')
    },
    text: 'Keeps the box’s current width-to-height ratio when you resize it in the editor. It does not force the box to match the selected image.',
    related:
      'Keep image proportions prevents stretching the artwork. Fit box to image resets the box to the image’s ratio.',
  },
  imageScale: {
    get title() {
      return t('templateEditor.imageScale')
    },
    text: 'Scales the image inside its unchanged box. 1 uses the full available width and height; 0.5 uses half of each dimension, centered in the box.',
    related:
      'Keep image proportions still applies. This changes the artwork size, not the box size or its distance-holder spacing.',
  },
  brightness: {
    get title() {
      return t('templateEditor.brightness')
    },
    text: 'Adjusts image brightness before black-and-white conversion. 1 leaves it unchanged; lower values darken and higher values lighten it.',
    related:
      'Contrast changes the difference between light and dark areas. Threshold decides which tones print as ink.',
  },
  contrast: {
    get title() {
      return t('templateEditor.contrast')
    },
    text: 'Adjusts the difference between light and dark areas before conversion. 1 leaves it unchanged; lower values flatten and higher values strengthen contrast.',
    related:
      'Brightness shifts overall lightness. Dithering represents remaining shades with dots.',
  },
  conversion: {
    get title() {
      return t('templateEditor.imageConversion')
    },
    text: 'Threshold converts tones directly to black or white. Dithered shading uses patterns of ink dots to represent intermediate shades.',
    related:
      'Brightness and contrast apply before conversion. Show print pixels displays the resulting raster.',
  },
  threshold: {
    get title() {
      return t('common.threshold')
    },
    text: 'The cutoff from 1 to 255 for black-and-white conversion. Darker tones print as ink; increasing the cutoff makes more of the image black.',
    related: 'This cutoff is not used for dithered shading.',
  },
  barcode: {
    get title() {
      return t('templateEditor.barcodeFormat')
    },
    text: 'Code 128 encodes general text and IDs. EAN-13 and EAN-8 are numeric retail codes with a check digit. Code 39 uses a restricted set of uppercase letters, numbers and symbols.',
    related:
      'Choose the format your scanner or receiving system expects. Invalid content produces a preview error.',
  },
  caption: {
    get title() {
      return t('common.showCaption')
    },
    text: 'Prints the barcode’s human-readable value beneath the bars, including the calculated check digit for EAN codes.',
    related: 'Caption size changes the letters beneath the code, not the encoded value.',
  },
  qrFill: {
    get title() {
      return t('common.scaleUpToBoundingBox')
    },
    text: 'Enlarges the QR code to use the available box area. When off, QR modules use whole printer pixels and may leave additional space.',
    related:
      'QR margin reserves clear space inside the box. The minimum scannable module size is still enforced.',
  },
  qrMargin: {
    get title() {
      return t('templateEditor.qrMarginMm')
    },
    text: 'Reserves clear space on each side of the QR code. Blank adds a four-module border; 0 removes that built-in border.',
    related:
      'A QR code still needs clear space around it to scan reliably. Box size and margin together determine the code’s available area.',
  },
  follow: {
    get title() {
      return t('templateEditor.followElement')
    },
    text: 'Keeps this object a set distance to the right of or below another object as that object moves or changes size. Deleting the followed object leaves this one at its current position.',
    related:
      'The gap is measured between bounding boxes, including rotation and padding. Logic can also control positions; a controlled position cannot be dragged freely.',
  },
  gap: {
    get title() {
      return t('templateEditor.gapMm')
    },
    text: 'The space between this object’s bounding box and the followed object’s bounding box, along the chosen placement direction.',
    related:
      'Text padding and image scale affect artwork inside a box; this gap is measured between the boxes themselves.',
  },
  variables: {
    get title() {
      return t('common.variableFields')
    },
    text: 'Define inputs people fill in when making labels. Variable name is the identifier used in content and logic; Field label is the name shown on the form.',
    related:
      'Sample values preview the design in the editor. Default values prefill new-label forms. Saved preview input sets override samples only for that preview.',
  },
  minimumLength: {
    get title() {
      return t('templateEditor.minimumLength')
    },
    text: 'The minimum number of characters in a nonempty text input. Leave blank for no minimum.',
    related:
      'Required controls whether the input may be empty. This does not set a text box’s size or the physical label length.',
  },
  maximumLength: {
    get title() {
      return t('templateEditor.maximumLength')
    },
    text: 'The maximum number of characters allowed in a text input, up to the application limit of 2,000. Leave blank to use that limit.',
    related:
      'This limits input text, not the physical width of the text box or label. Font size and automatic sizing control the printed layout.',
  },
} satisfies Record<string, SettingExplanation>
