import type { TemplateDimensions } from './types'

export function templateLength(dimensions: TemplateDimensions): string {
  if (dimensions.variable_length) return 'Variable length'
  return dimensions.length_mm != null ? `${dimensions.length_mm} mm long` : 'Length unavailable'
}
