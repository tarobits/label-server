import type { TemplateDimensions } from '../shared/types'
import { t, number } from '../shared/i18n'

export function templateLength(dimensions: TemplateDimensions): string {
  if (dimensions.variable_length) return t('uiRemainder.variableLength')
  return dimensions.length_mm != null
    ? t('uiRemainder.length', { length: number(dimensions.length_mm) })
    : t('uiRemainder.noLength')
}
