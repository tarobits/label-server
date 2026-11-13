import { t } from '../shared/i18n'
import {
  logicTargetLabel,
  socketTypeLabel,
  operationDescription,
  type LogicCatalog,
} from './logicGraph'
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
  get x() {
    return t('logicPropertyHelp.x')
  },
  get y() {
    return t('logicPropertyHelp.y')
  },
  get width() {
    return t('logicPropertyHelp.width')
  },
  get height() {
    return t('logicPropertyHelp.height')
  },
  get rotation() {
    return t('logicPropertyHelp.rotation')
  },
  get visible() {
    return t('logicPropertyHelp.visible')
  },
  get length_mm() {
    return t('logicPropertyHelp.lengthMm')
  },
  get width_mm() {
    return t('logicPropertyHelp.widthMm')
  },
  get auto_length() {
    return t('logicPropertyHelp.autoLength')
  },
  get gap_mm() {
    return t('logicPropertyHelp.gapMm')
  },
  get content() {
    return t('logicPropertyHelp.content')
  },
  get font_size() {
    return t('logicPropertyHelp.fontSize')
  },
  get character_spacing() {
    return t('logicPropertyHelp.characterSpacing')
  },
  get line_spacing() {
    return t('logicPropertyHelp.lineSpacing')
  },
  get bold() {
    return t('logicPropertyHelp.bold')
  },
  get wrap() {
    return t('logicPropertyHelp.wrap')
  },
  get auto_width() {
    return t('logicPropertyHelp.autoWidth')
  },
  get align() {
    return t('logicPropertyHelp.align')
  },
  get vertical_align() {
    return t('logicPropertyHelp.verticalAlign')
  },
  get image_asset() {
    return t('logicPropertyHelp.imageAsset')
  },
  get preserve_aspect() {
    return t('logicPropertyHelp.preserveAspect')
  },
  get image_scale() {
    return t('logicPropertyHelp.imageScale')
  },
  get brightness() {
    return t('logicPropertyHelp.brightness')
  },
  get contrast() {
    return t('logicPropertyHelp.contrast')
  },
  get image_threshold() {
    return t('logicPropertyHelp.imageThreshold')
  },
  get image_mode() {
    return t('logicPropertyHelp.imageMode')
  },
  get qr_fill_box() {
    return t('logicPropertyHelp.qrFillBox')
  },
  get barcode_format() {
    return t('logicPropertyHelp.barcodeFormat')
  },
  get barcode_caption() {
    return t('logicPropertyHelp.barcodeCaption')
  },
  get qr_margin_mm() {
    return t('logicPropertyHelp.qrMarginMm')
  },
  get stroke() {
    return t('logicPropertyHelp.stroke')
  },
  get filled() {
    return t('logicPropertyHelp.filled')
  },
  get padding_top() {
    return t('logicPropertyHelp.paddingTop')
  },
  get padding_bottom() {
    return t('logicPropertyHelp.paddingBottom')
  },
  get padding_left() {
    return t('logicPropertyHelp.paddingLeft')
  },
  get padding_right() {
    return t('logicPropertyHelp.paddingRight')
  },
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
      group: t('logicReferenceEntries.typeText.group'),
      title: t('logicReferenceEntries.typeText.title'),
      summary: t('logicReferenceEntries.typeText.summary'),
      details: [
        t('logicReferenceEntries.typeText.detail1'),
        t('logicReferenceEntries.typeText.detail2'),
      ],
      example: 'let caption = "Cable rack";',
    },
    {
      id: 'type:number',
      group: t('logicReferenceEntries.typeNumber.group'),
      title: t('logicReferenceEntries.typeNumber.title'),
      summary: t('logicReferenceEntries.typeNumber.summary'),
      details: [
        t('logicReferenceEntries.typeNumber.detail1'),
        t('logicReferenceEntries.typeNumber.detail2'),
      ],
      example: 'let spacing = 2.5;\nlet total = max(30, spacing * 12);',
    },
    {
      id: 'type:boolean',
      group: t('logicReferenceEntries.typeBoolean.group'),
      title: t('logicReferenceEntries.typeBoolean.title'),
      summary: t('logicReferenceEntries.typeBoolean.summary'),
      details: [
        t('logicReferenceEntries.typeBoolean.detail1'),
        t('logicReferenceEntries.typeBoolean.detail2'),
      ],
      example: 'let enabled = true;\nlet height = if(enabled, 12, 14);',
    },
    {
      id: 'type:image',
      group: t('logicReferenceEntries.typeImage.group'),
      title: t('logicReferenceEntries.typeImage.title'),
      summary: t('logicReferenceEntries.typeImage.summary'),
      details: [
        t('logicReferenceEntries.typeImage.detail1'),
        t('logicReferenceEntries.typeImage.detail2'),
      ],
    },
    {
      id: 'variables',
      group: t('logicReferenceEntries.variables.group'),
      title: t('logicReferenceEntries.variables.title'),
      summary: t('logicReferenceEntries.variables.summary'),
      details: [
        t('logicReferenceEntries.variables.detail1'),
        t('logicReferenceEntries.variables.detail2'),
      ],
      example:
        'let subtitleHeight = if(hasSubtitle, 2, 0);\nlet titleHeight = 14 - subtitleHeight;\nlet hasSubtitle = filled(subtitle);',
    },
    {
      id: 'source',
      group: t('logicReferenceEntries.source.group'),
      title: t('logicReferenceEntries.source.title'),
      summary: t('logicReferenceEntries.source.summary'),
      details: [
        t('logicReferenceEntries.source.detail1'),
        t('logicReferenceEntries.source.detail2'),
        t('logicReferenceEntries.source.detail3'),
        t('logicReferenceEntries.source.detail4'),
      ],
      example: '// A fixed title height\ntext1.height = 12;',
    },
    {
      id: 'property-inputs',
      group: t('logicReferenceEntries.propertyInputs.group'),
      title: t('logicReferenceEntries.propertyInputs.title'),
      summary: t('logicReferenceEntries.propertyInputs.summary'),
      details: [
        t('logicReferenceEntries.propertyInputs.detail1'),
        t('logicReferenceEntries.propertyInputs.detail2'),
        t('logicReferenceEntries.propertyInputs.detail3'),
        t('logicReferenceEntries.propertyInputs.detail4'),
      ],
      example:
        'let titleHeight = text1.height;\ntext2.height = titleHeight / 2;\ntext1.height = 12;',
    },
    {
      id: 'layout',
      group: t('logicReferenceEntries.layout.group'),
      title: t('logicReferenceEntries.layout.title'),
      summary: t('logicReferenceEntries.layout.summary'),
      details: [
        t('logicReferenceEntries.layout.detail1'),
        t('logicReferenceEntries.layout.detail2'),
        t('logicReferenceEntries.layout.detail3'),
        t('logicReferenceEntries.layout.detail4'),
      ],
    },
    {
      id: 'connections',
      group: t('logicReferenceEntries.connections.group'),
      title: t('logicReferenceEntries.connections.title'),
      summary: t('logicReferenceEntries.connections.summary'),
      details: [
        t('logicReferenceEntries.connections.detail1'),
        t('logicReferenceEntries.connections.detail2'),
        t('logicReferenceEntries.connections.detail3'),
        t('logicReferenceEntries.connections.detail4'),
        t('logicReferenceEntries.connections.detail5'),
      ],
    },
    {
      id: 'errors',
      group: t('logicReferenceEntries.errors.group'),
      title: t('logicReferenceEntries.errors.title'),
      summary: t('logicReferenceEntries.errors.summary'),
      details: [
        t('logicReferenceEntries.errors.detail1'),
        t('logicReferenceEntries.errors.detail2'),
        t('logicReferenceEntries.errors.detail3'),
      ],
    },
    {
      id: 'example:conditional',
      group: t('logicReferenceEntries.exampleConditional.group'),
      title: t('logicReferenceEntries.exampleConditional.title'),
      summary: t('logicReferenceEntries.exampleConditional.summary'),
      details: [t('logicReferenceEntries.exampleConditional.detail1')],
      example:
        'let hasSubtitle = filled(subtitle);\ntext1.height = if(hasSubtitle, 12, 14);\ntext2.height = 2;\ntext2.visible = hasSubtitle;',
    },
    {
      id: 'example:length',
      group: t('logicReferenceEntries.exampleLength.group'),
      title: t('logicReferenceEntries.exampleLength.title'),
      summary: t('logicReferenceEntries.exampleLength.summary'),
      details: [t('logicReferenceEntries.exampleLength.detail1')],
      example: 'label.length_mm = min(300, max(30, quantity * 12));',
    },
    {
      id: 'example:guard',
      group: t('logicReferenceEntries.exampleGuard.group'),
      title: t('logicReferenceEntries.exampleGuard.title'),
      summary: t('logicReferenceEntries.exampleGuard.summary'),
      details: [t('logicReferenceEntries.exampleGuard.detail1')],
      example: 'let perItem = if(quantity == 0, 0, 100 / quantity);',
    },
  ]
  for (const operation of catalog.operations)
    entries.push({
      id: `operation:${operation.name}`,
      group: t('logicMessages.operations'),
      title: operation.name,
      summary: operationDescription(operation.name),
      details: [
        t(
          `logicMessages.${operation.signature === 'boolean' ? 'booleanSignature' : operation.signature}`,
          { count: operation.minimum_arguments },
        ),
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
      group: t('logicMessages.properties'),
      title: name,
      summary,
      details: targets.length
        ? [t('logicMessages.targets', { targets: targets.join(', ') })]
        : [t('logicMessages.noTargets')],
    })
  }
  for (const field of document.fields)
    entries.push({
      id: `input:${field.name}`,
      group: t('logicMessages.inputs'),
      title: field.name,
      summary: t(field.required ? 'logicMessages.fieldRequired' : 'logicMessages.fieldOptional', {
        label: field.label,
        type: socketTypeLabel(field.type ?? 'text'),
      }),
      details: [t('logicMessages.defineInputs')],
    })
  return entries
}
