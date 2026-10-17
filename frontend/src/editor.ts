import { randomUUID } from './uuid'

export interface TemplateField {
  name: string
  label: string
  required: boolean
  default: string
  sample: string
}
export interface Element {
  id: string
  kind: 'text' | 'qr' | 'rectangle' | 'line' | 'image'
  x: number
  y: number
  width: number
  height: number
  rotation: 0 | 90 | 180 | 270
  distance_holder?: { element_id: string; axis: 'horizontal' | 'vertical'; gap_mm: number } | null
  content: string
  font: string
  font_size: number
  character_spacing?: number
  line_spacing?: number
  bold: boolean
  align: 'left' | 'center' | 'right'
  vertical_align?: 'top' | 'center' | 'bottom'
  auto_width?: boolean
  wrap: boolean
  padding_top?: number
  padding_right?: number
  padding_bottom?: number
  padding_left?: number
  stroke: number
  filled: boolean
  image_asset?: string | null
  preserve_aspect?: boolean
  brightness?: number
  contrast?: number
  image_mode?: 'threshold' | 'dither'
  image_threshold?: number
  qr_fill_box?: boolean
  qr_margin_mm?: number | null
}
export interface TemplateDocument {
  version: 1
  width_mm: number
  length_mm: number
  auto_length?: boolean
  out_of_bounds?: 'error' | 'clip'
  print_resolution?: 'printer' | 'normal' | 'high'
  elements: Element[]
  fields: TemplateField[]
}
export interface Preview {
  png: string
  design_png: string
  svg: string
  pixel_width: number
  pixel_height: number
  warnings: string[]
  length_mm: number
  width_mm: number
  resolved_elements: Element[]
}
export function newDocument(): TemplateDocument {
  return {
    version: 1,
    width_mm: 24,
    length_mm: 60,
    auto_length: true,
    out_of_bounds: 'clip',
    print_resolution: 'printer',
    fields: [],
    elements: [],
  }
}
export function newElement(kind: Element['kind']): Element {
  return {
    id: randomUUID(),
    kind,
    x: 2,
    y: 2,
    width: kind === 'qr' ? 20 : 30,
    height: kind === 'line' ? 1 : kind === 'qr' ? 20 : 8,
    rotation: 0,
    content: kind === 'qr' ? 'https://example.org' : kind === 'text' ? 'Your label' : '',
    font: 'Noto Sans',
    font_size: 3,
    character_spacing: 0,
    line_spacing: 0,
    bold: false,
    align: 'left',
    vertical_align: 'top',
    auto_width: false,
    wrap: true,
    padding_top: 0,
    padding_right: 0,
    padding_bottom: 0,
    padding_left: 0,
    stroke: 0.3,
    filled: false,
    image_asset: null,
    preserve_aspect: true,
    brightness: 1,
    contrast: 1,
    image_mode: 'threshold',
    image_threshold: 128,
    qr_fill_box: false,
    qr_margin_mm: 1,
  }
}
