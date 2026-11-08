import { randomUUID } from './uuid'
import type { CostEstimate, PrintPlan } from './types'

export type ValueType = 'text' | 'number' | 'boolean' | 'image'
export interface ImageValue {
  image_asset: string
}
export type VariableValue = string | number | boolean | ImageValue | null
export type Expression = (
  | { kind: 'literal'; value: VariableValue }
  | { kind: 'reference'; name: string }
  | { kind: 'property'; target: string; property: string }
  | { kind: 'call'; operation: string; arguments: Expression[] }
) & { node_id?: string | null; span?: { start: number; end: number } | null }
export interface LogicProgram {
  version: 1
  variables: Record<string, Expression>
  bindings: { target: string; property: string; expression: Expression }[]
}
export interface LogicNode {
  id: string
  kind: 'input' | 'property' | 'literal' | 'call' | 'variable' | 'output'
  x: number
  y: number
  type: ValueType
  name?: string | null
  operation?: string | null
  value?: VariableValue
  target?: string | null
  property?: string | null
  inputs: (string | null)[]
  defaults: VariableValue[]
}
export interface LogicEditorState {
  version: 1
  source?: string | null
  nodes: LogicNode[]
  x: number
  y: number
  zoom: number
}
export interface TemplateField {
  name: string
  label: string
  required: boolean
  type?: ValueType
  default: VariableValue
  sample: VariableValue
  minimum?: number | null
  maximum?: number | null
}
export interface Element {
  id: string
  name?: string
  logic_name?: string | null
  visible?: boolean
  literal_content?: boolean
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
  media?: import('./media').MediaProperties
  version: 1 | 2
  logic?: LogicProgram | null
  logic_editor?: LogicEditorState | null
  width_mm: number
  length_mm: number
  auto_length?: boolean
  out_of_bounds?: 'error' | 'clip'
  print_resolution?: 'printer' | 'normal' | 'high'
  preview_tape?: { id: string; name: string; foreground: string; background: string } | null
  elements: Element[]
  fields: TemplateField[]
}
export interface Preview {
  cost_estimate?: CostEstimate | null
  print_plan?: PrintPlan | null
  printable?: boolean
  missing_assets?: Record<string, 'image' | 'font'>
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
export function elementGeometry(element: Element) {
  const quarterTurn = element.rotation % 180 !== 0
  const thickness = element.kind === 'line' ? element.stroke : element.height
  const width = quarterTurn ? thickness : element.width
  const height = quarterTurn ? element.width : thickness
  const clean = (value: number) => Math.round(value * 1e9) / 1e9
  return {
    x: clean(element.x + (element.width - width) / 2),
    y: clean(element.y + (element.height - height) / 2),
    width,
    height,
  }
}
export function setElementGeometry(element: Element, geometry: ReturnType<typeof elementGeometry>) {
  const quarterTurn = element.rotation % 180 !== 0
  const width = quarterTurn ? geometry.height : geometry.width
  const height = quarterTurn ? geometry.width : geometry.height
  element.x = geometry.x + (geometry.width - width) / 2
  element.y = geometry.y + (geometry.height - height) / 2
  element.width = width
  element.height = height
}
export function automaticDimension(element: Element): 'width' | 'height' | undefined {
  return element.kind === 'text' && element.auto_width
    ? element.rotation % 180
      ? 'height'
      : 'width'
    : undefined
}
export function newDocument(): TemplateDocument {
  return {
    version: 1,
    width_mm: 24,
    length_mm: 60,
    auto_length: true,
    out_of_bounds: 'clip',
    print_resolution: 'printer',
    preview_tape: null,
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
    height: kind === 'line' ? 0.3 : kind === 'qr' ? 20 : 8,
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
