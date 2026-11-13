import { t } from '../shared/i18n'
import type { SettingExplanation } from '../components/SettingHelp.vue'

export const editorHelp = {
  autoLength: {
    get title() {
      return t('templateEditor.automaticLabelLength')
    },
    get text() {
      return t('editorHelp.autoLength.text')
    },
    get related() {
      return t('editorHelp.autoLength.related')
    },
  },
  autoWidth: {
    get title() {
      return t('editorHelp.autoWidth.title')
    },
    get text() {
      return t('editorHelp.autoWidth.text')
    },
    get related() {
      return t('editorHelp.autoWidth.related')
    },
  },
  length: {
    get title() {
      return t('templateEditor.labelLengthMm')
    },
    get text() {
      return t('editorHelp.length.text')
    },
    get related() {
      return t('editorHelp.length.related')
    },
  },
  resolution: {
    get title() {
      return t('templateEditor.printResolution')
    },
    get text() {
      return t('editorHelp.resolution.text')
    },
    get related() {
      return t('editorHelp.resolution.related')
    },
  },
  profile: {
    get title() {
      return t('common.tapeProfile')
    },
    get text() {
      return t('editorHelp.profile.text')
    },
    get related() {
      return t('editorHelp.profile.related')
    },
  },
  destination: {
    get title() {
      return t('templateEditor.designDestination')
    },
    get text() {
      return t('editorHelp.destination.text')
    },
    get related() {
      return t('editorHelp.destination.related')
    },
  },
  visibility: {
    get title() {
      return t('common.templateVisibility')
    },
    get text() {
      return t('editorHelp.visibility.text')
    },
    get related() {
      return t('editorHelp.visibility.related')
    },
  },
  clipping: {
    get title() {
      return t('templateEditor.ignoreOutOfBoundsObjects')
    },
    get text() {
      return t('editorHelp.clipping.text')
    },
    get related() {
      return t('editorHelp.clipping.related')
    },
  },
  pixels: {
    get title() {
      return t('common.showPrintPixels')
    },
    get text() {
      return t('editorHelp.pixels.text')
    },
  },
  snap: {
    get title() {
      return t('common.snap05Mm')
    },
    get text() {
      return t('editorHelp.snap.text')
    },
  },
  bounds: {
    get title() {
      return t('templateEditor.objectBoundaries')
    },
    get text() {
      return t('editorHelp.bounds.text')
    },
  },
  fontSize: {
    get title() {
      return t('templateEditor.fontSizeMm')
    },
    get text() {
      return t('editorHelp.fontSize.text')
    },
    get related() {
      return t('editorHelp.fontSize.related')
    },
  },
  wrap: {
    get title() {
      return t('common.wrapText')
    },
    get text() {
      return t('editorHelp.wrap.text')
    },
    get related() {
      return t('editorHelp.wrap.related')
    },
  },
  characterSpacing: {
    get title() {
      return t('editorHelp.characterSpacing.title')
    },
    get text() {
      return t('editorHelp.characterSpacing.text')
    },
    get related() {
      return t('editorHelp.characterSpacing.related')
    },
  },
  lineSpacing: {
    get title() {
      return t('editorHelp.lineSpacing.title')
    },
    get text() {
      return t('editorHelp.lineSpacing.text')
    },
    get related() {
      return t('editorHelp.lineSpacing.related')
    },
  },
  padding: {
    get title() {
      return t('editorHelp.padding.title')
    },
    get text() {
      return t('editorHelp.padding.text')
    },
    get related() {
      return t('editorHelp.padding.related')
    },
  },
  imageProportions: {
    get title() {
      return t('templateEditor.keepImageProportions')
    },
    get text() {
      return t('editorHelp.imageProportions.text')
    },
    get related() {
      return t('editorHelp.imageProportions.related')
    },
  },
  boxProportions: {
    get title() {
      return t('templateEditor.lockBoxProportions')
    },
    get text() {
      return t('editorHelp.boxProportions.text')
    },
    get related() {
      return t('editorHelp.boxProportions.related')
    },
  },
  imageScale: {
    get title() {
      return t('templateEditor.imageScale')
    },
    get text() {
      return t('editorHelp.imageScale.text')
    },
    get related() {
      return t('editorHelp.imageScale.related')
    },
  },
  brightness: {
    get title() {
      return t('templateEditor.brightness')
    },
    get text() {
      return t('editorHelp.brightness.text')
    },
    get related() {
      return t('editorHelp.brightness.related')
    },
  },
  contrast: {
    get title() {
      return t('templateEditor.contrast')
    },
    get text() {
      return t('editorHelp.contrast.text')
    },
    get related() {
      return t('editorHelp.contrast.related')
    },
  },
  conversion: {
    get title() {
      return t('templateEditor.imageConversion')
    },
    get text() {
      return t('editorHelp.conversion.text')
    },
    get related() {
      return t('editorHelp.conversion.related')
    },
  },
  threshold: {
    get title() {
      return t('common.threshold')
    },
    get text() {
      return t('editorHelp.threshold.text')
    },
    get related() {
      return t('editorHelp.threshold.related')
    },
  },
  barcode: {
    get title() {
      return t('templateEditor.barcodeFormat')
    },
    get text() {
      return t('editorHelp.barcode.text')
    },
    get related() {
      return t('editorHelp.barcode.related')
    },
  },
  caption: {
    get title() {
      return t('common.showCaption')
    },
    get text() {
      return t('editorHelp.caption.text')
    },
    get related() {
      return t('editorHelp.caption.related')
    },
  },
  qrFill: {
    get title() {
      return t('common.scaleUpToBoundingBox')
    },
    get text() {
      return t('editorHelp.qrFill.text')
    },
    get related() {
      return t('editorHelp.qrFill.related')
    },
  },
  qrMargin: {
    get title() {
      return t('templateEditor.qrMarginMm')
    },
    get text() {
      return t('editorHelp.qrMargin.text')
    },
    get related() {
      return t('editorHelp.qrMargin.related')
    },
  },
  follow: {
    get title() {
      return t('templateEditor.followElement')
    },
    get text() {
      return t('editorHelp.follow.text')
    },
    get related() {
      return t('editorHelp.follow.related')
    },
  },
  gap: {
    get title() {
      return t('templateEditor.gapMm')
    },
    get text() {
      return t('editorHelp.gap.text')
    },
    get related() {
      return t('editorHelp.gap.related')
    },
  },
  variables: {
    get title() {
      return t('common.variableFields')
    },
    get text() {
      return t('editorHelp.variables.text')
    },
    get related() {
      return t('editorHelp.variables.related')
    },
  },
  minimumLength: {
    get title() {
      return t('templateEditor.minimumLength')
    },
    get text() {
      return t('editorHelp.minimumLength.text')
    },
    get related() {
      return t('editorHelp.minimumLength.related')
    },
  },
  maximumLength: {
    get title() {
      return t('templateEditor.maximumLength')
    },
    get text() {
      return t('editorHelp.maximumLength.text')
    },
    get related() {
      return t('editorHelp.maximumLength.related')
    },
  },
} satisfies Record<string, SettingExplanation>
