<script setup lang="ts">
import { t } from '../shared/i18n'

import { logicTargetLabel } from '../templates/logicGraph'
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import {
  ChevronDownIcon,
  ArrowsPointingOutIcon,
  MinusIcon,
  PlusIcon,
  TrashIcon,
} from '@heroicons/vue/24/outline'
import ExpandableContent from './ExpandableContent.vue'
import MotionSurface from './MotionSurface.vue'
import MotionTrack from './MotionTrack.vue'
import LogicReference from './LogicReference.vue'
const LogicSourceEditor = defineAsyncComponent(() => import('./LogicSourceEditor.vue'))
import LogicSocket from './LogicSocket.vue'
import VariableInput from './VariableInput.vue'
import { api, errorMessage } from '../shared/api'
import { upgradeDocument, displayValue } from '../templates/variableInputs'
import type {
  LogicEditorState,
  LogicNode,
  TemplateDocument,
  ValueType,
  VariableValue,
} from '../templates/editor'
import {
  canConnect,
  compileGraph,
  defaultValue,
  inputType,
  automaticOutput,
  loadGraph,
  makeNode,
  nodeType,
  pairedInputs,
  pairedType,
  validateGraphTypes,
  semanticProgram,
  socketLabel,
  title,
  valueType,
  valueTypes,
  type LogicCatalog,
  type SocketType,
  type SourceDiagnostic,
  type CompileResult,
} from '../templates/logicGraph'

const props = defineProps<{
  document: TemplateDocument
  destinationId?: string
  disabled?: boolean
  preview?: string
  previewLengthMm?: number
  previewWidthMm?: number
  previewError?: string
}>()
const previewGeometry = computed(() => ({
  '--label-ratio':
    (props.previewLengthMm ?? props.document.length_mm) /
    (props.previewWidthMm ?? props.document.width_mm),
}))
const logicEndpoint = (name: string) =>
  `/logic/${name}${props.destinationId ? `?destination_id=${encodeURIComponent(props.destinationId)}` : ''}`
const emit = defineEmits<{ apply: [document: TemplateDocument]; blocked: [blocked: boolean] }>()
const mode = ref<'nodes' | 'source'>('nodes'),
  sourceMounted = ref(false),
  referenceOpen = ref(false),
  referenceEntry = ref('source'),
  referenceRequest = ref(0)
const sourceText = ref(''),
  sourceDirty = ref(false),
  sourceBusy = ref(false),
  sourceDiagnostics = ref<SourceDiagnostic[]>([])
const graphLocked = computed(() => props.disabled || sourceDirty.value)
let sourceSequence = 0,
  sourceTimer: ReturnType<typeof setTimeout> | undefined
const open = ref(false),
  expanded = ref(false),
  palette = ref(false),
  search = ref('')
const state = ref<LogicEditorState>({ version: 1, nodes: [], x: 24, y: 24, zoom: 1 })
const catalog = ref<LogicCatalog | null>(null),
  error = ref(''),
  announcement = ref(''),
  loading = ref(false),
  pending = ref(false)
const selectedId = ref(''),
  canvas = ref<HTMLElement | null>(null)
const selected = computed(() => state.value.nodes.find((node) => node.id === selectedId.value))
const valueTypeInputs = computed(() => {
  const node = selected.value
  if (!node || !catalog.value) return []
  return node.inputs.flatMap((_, index) =>
    pairedInputs(node).includes(index) ||
    inputType(node, index, state.value.nodes, catalog.value!) === 'any'
      ? [index]
      : [],
  )
})
const selectedValueType = computed(() => {
  const node = selected.value
  if (!node || !valueTypeInputs.value.length) return 'number'
  return valueTypeInputs.value.length > 1
    ? pairedType(node, state.value.nodes, catalog.value!)
    : fallbackType(node, valueTypeInputs.value[0]!)
})
const literalField = computed(() => ({
  name: 'value',
  get label() {
    return t('common.value')
  },
  type: selected.value?.type ?? 'number',
  required: false,
  default: null,
  sample: null,
}))
const fallbackFields = computed(
  () =>
    selected.value?.inputs.map((_, index) => ({
      name: 'value',
      get label() {
        return t('common.value')
      },
      type: fallbackType(selected.value!, index),
      required: false,
      default: null,
      sample: null,
    })) ?? [],
)
const target = ref('label'),
  property = ref('length_mm')
const writableProperties = computed(() => catalog.value?.targets[target.value]?.properties ?? {})
const bindingDisabled = computed(() => {
  const definition = catalog.value?.targets[target.value]
  if (!definition?.properties[property.value] || property.value === 'auto_width') return true
  const element = props.document.elements.find((element) => element.id === definition.id)
  return element?.kind === 'line' && !!definition.disabled_properties?.[property.value]
})
const readableProperties = computed(
  () => catalog.value?.targets[target.value]?.readable_properties ?? writableProperties.value,
)
const availableProperties = computed(() => ({
  ...writableProperties.value,
  ...readableProperties.value,
}))
watch(target, () => {
  property.value = Object.keys(availableProperties.value)[0] ?? ''
})
const operations = computed(
  () =>
    catalog.value?.operations.filter((operation) =>
      `${title(operation.name)} ${operation.name} ${operation.description}`
        .toLowerCase()
        .includes(search.value.toLowerCase()),
    ) ?? [],
)
const active = ref<{ id: string; port: number } | null>(null)
const pointer = ref({ x: 0, y: 0 })
let sequence = 0,
  stopped = false,
  lastSent = '',
  timer: ReturnType<typeof setTimeout> | undefined
let gesture: {
  kind: 'node' | 'pan' | 'wire'
  pointerId: number
  id?: string
  port?: number
  x: number
  y: number
  startX: number
  startY: number
  moved: boolean
} | null = null
let suppressClick = false
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value))
function upgraded() {
  const document = clone(props.document)
  upgradeDocument(document)
  return document
}
async function initialize() {
  sourceSequence++
  clearTimeout(sourceTimer)
  const ticket = ++sequence
  loading.value = true
  try {
    const document = upgraded()
    const result = await api<LogicCatalog>(logicEndpoint('inspect'), 'POST', document)
    if (stopped || ticket !== sequence) return
    catalog.value = result
    if (!sourceDirty.value) {
      sourceText.value = result.source
      sourceDiagnostics.value = []
      sourceBusy.value = false
    }
    state.value = loadGraph(document)
    state.value.source = result.source
    if (!document.logic_editor) void nextTick(() => frame())
    error.value = ''
    pending.value = false
    emit('blocked', sourceDirty.value)
    if (sourceDirty.value) editSource(sourceText.value)
    else if (
      semanticProgram(compileGraph(state.value.nodes, document)) !== semanticProgram(document.logic)
    )
      changed()
  } catch (failure) {
    if (ticket === sequence) error.value = errorMessage(failure)
  } finally {
    if (ticket === sequence) loading.value = false
  }
}
function toggle() {
  open.value = !open.value
  if (open.value && !catalog.value) void initialize()
}
watch(
  () => props.destinationId,
  () => {
    if (catalog.value) void initialize()
  },
)
watch(
  () => props.document,
  () => {
    const echo = JSON.stringify(props.document) === lastSent
    lastSent = ''
    if (echo || !catalog.value) return
    clearTimeout(timer)
    active.value = null
    void initialize()
  },
  { deep: true },
)
function changed() {
  pending.value = true
  emit('blocked', true)
  clearTimeout(timer)
  sequence++
  timer = setTimeout(apply, 300)
}
async function apply() {
  const ticket = ++sequence
  try {
    const document = upgraded()
    // Preserve references in label text when a named intermediate is renamed.
    for (const previous of document.logic_editor?.nodes ?? []) {
      const node = state.value.nodes.find(
        (candidate) => candidate.id === previous.id && candidate.kind === 'variable',
      )
      if (node?.name && previous.name && node.name !== previous.name)
        for (const element of document.elements)
          if (!element.literal_content)
            element.content = element.content.replace(
              /\{\{\s*([A-Za-z][A-Za-z0-9_]*)\s*\}\}/g,
              (token, name) => (name === previous.name ? `{{${node.name}}}` : token),
            )
    }
    document.logic = compileGraph(state.value.nodes, document)
    validateGraphTypes(state.value.nodes, catalog.value!)
    document.logic_editor = clone(state.value)
    const result = await api<LogicCatalog>(logicEndpoint('inspect'), 'POST', document)
    if (stopped || ticket !== sequence) return
    state.value.source =
      semanticProgram(document.logic) === semanticProgram(props.document.logic)
        ? sourceText.value
        : result.source
    sourceText.value = state.value.source
    document.logic_editor = clone(state.value)
    catalog.value = { ...result, source: sourceText.value }
    error.value = ''
    pending.value = false
    lastSent = JSON.stringify(document)
    emit('apply', document)
    emit('blocked', false)
  } catch (failure) {
    if (!stopped && ticket === sequence) {
      error.value = errorMessage(failure)
      pending.value = true
      emit('blocked', true)
    }
  }
}
function selectMode(value: 'nodes' | 'source') {
  mode.value = value
  if (value === 'source') sourceMounted.value = true
  active.value = null
}
function modeKeys(event: KeyboardEvent) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  selectMode(
    event.key === 'Home'
      ? 'nodes'
      : event.key === 'End'
        ? 'source'
        : mode.value === 'nodes'
          ? 'source'
          : 'nodes',
  )
  const buttons = (
    event.currentTarget as HTMLElement
  ).parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]')
  buttons?.[mode.value === 'nodes' ? 0 : 1]?.focus()
}
function showReference(entry = 'source') {
  referenceEntry.value = entry
  referenceRequest.value++
  referenceOpen.value = true
  void nextTick(() =>
    document.getElementById('logic-reference-panel')?.scrollIntoView({ block: 'nearest' }),
  )
}
function nodeHelp(node: LogicNode) {
  showReference(
    node.kind === 'call'
      ? `operation:${node.operation}`
      : node.kind === 'property'
        ? 'property-inputs'
        : node.kind === 'output'
          ? `property:${node.property}`
          : node.kind === 'input'
            ? `input:${node.name}`
            : node.kind === 'variable'
              ? 'variables'
              : `type:${node.type}`,
  )
}
function editSource(text: string) {
  sourceText.value = text
  sourceDirty.value = true
  sourceBusy.value = true
  sourceDiagnostics.value = []
  emit('blocked', true)
  sourceSequence++
  clearTimeout(sourceTimer)
  sourceTimer = setTimeout(compileSource, 350)
}
async function compileSource() {
  const ticket = ++sourceSequence,
    source = sourceText.value
  try {
    const document = upgraded()
    const result = await api<CompileResult>(logicEndpoint('compile'), 'POST', { document, source })
    if (stopped || ticket !== sourceSequence) return
    if (!result.valid || !result.program || !result.catalog) {
      sourceDiagnostics.value = result.diagnostics
      return
    }
    document.logic = result.program
    const graph = loadGraph(document, false)
    if (semanticProgram(compileGraph(graph.nodes, document)) !== semanticProgram(result.program))
      throw new Error(
        'Cannot synchronize these node changes. Revert the source draft and try again.',
      )
    graph.source = source
    document.logic_editor = graph
    // Validate retained draft nodes/assets and the editor size limit before committing.
    await api<LogicCatalog>(logicEndpoint('inspect'), 'POST', document)
    if (stopped || ticket !== sourceSequence) return
    state.value = graph
    catalog.value = { ...result.catalog, source }
    sourceDirty.value = false
    sourceDiagnostics.value = []
    error.value = ''
    pending.value = false
    lastSent = JSON.stringify(document)
    emit('apply', document)
    emit('blocked', false)
  } catch (failure) {
    if (!stopped && ticket === sourceSequence)
      sourceDiagnostics.value = [
        { from: 0, to: 0, line: 1, column: 1, severity: 'error', message: errorMessage(failure) },
      ]
  } finally {
    if (ticket === sourceSequence) sourceBusy.value = false
  }
}
function revertSource() {
  sourceSequence++
  clearTimeout(sourceTimer)
  sourceText.value = catalog.value?.source ?? ''
  sourceDirty.value = false
  sourceBusy.value = false
  sourceDiagnostics.value = []
  emit('blocked', pending.value)
}
function persistLayout() {
  if (graphLocked.value) return
  if (pending.value) {
    changed()
    return
  }
  const document = upgraded()
  document.logic_editor = clone(state.value)
  lastSent = JSON.stringify(document)
  emit('apply', document)
}
function place(node: LogicNode) {
  let index = 0
  do {
    node.x = (index % 3) * 300
    node.y = Math.floor(index / 3) * 240
    index++
  } while (
    state.value.nodes.some(
      (existing) => Math.abs(existing.x - node.x) < 260 && Math.abs(existing.y - node.y) < 200,
    )
  )
  state.value.nodes.push(node)
  void nextTick(() => frame())
}
function add(kind: 'literal' | 'call' | 'variable', name: string) {
  if (graphLocked.value || !catalog.value || state.value.nodes.length >= 512) return
  const node = makeNode(kind, state.value)
  if (kind === 'literal') {
    node.type = name as ValueType
    node.value = defaultValue(node.type)
  }
  if (kind === 'variable') {
    let index = 1
    while (
      state.value.nodes.some((node) => node.name === `value${index}`) ||
      props.document.elements.some((element) => element.logic_name === `value${index}`)
    )
      index++
    node.name = `value${index}`
    node.inputs = [null]
    node.defaults = [0]
  }
  if (kind === 'call') {
    const operation = catalog.value.operations.find((operation) => operation.name === name)!
    node.operation = name
    node.inputs = Array(operation.minimum_arguments).fill(null)
    node.defaults = node.inputs.map((_, index) =>
      operation.signature === 'boolean' || (name === 'if' && index === 0)
        ? false
        : operation.signature === 'presence'
          ? ''
          : name === 'divide' && index === 1
            ? 1
            : 0,
    )
  }
  place(node)
  selectedId.value = node.id
  palette.value = false
  changed()
}
function disabledOutput(node: LogicNode): string | undefined {
  return node.kind === 'output'
    ? Object.values(catalog.value?.targets ?? {}).find((target) => target.id === node.target)
        ?.disabled_properties?.[node.property!]
    : undefined
}
function addOutput() {
  if (graphLocked.value || !catalog.value || bindingDisabled.value) return
  const targetId = catalog.value.targets[target.value]!.id
  const existing = state.value.nodes.find(
    (node) =>
      node.kind === 'output' && node.target === targetId && node.property === property.value,
  )
  if (existing) {
    selectedId.value = existing.id
    frame(existing)
    palette.value = false
    return
  }
  const type = availableProperties.value[property.value]!
  const element = props.document.elements.find((element) => element.id === targetId)
  let value =
    targetId === 'label'
      ? props.document.length_mm
      : property.value === 'gap_mm'
        ? element?.distance_holder?.gap_mm
        : (catalog.value.property_values?.[targetId]?.[property.value] ??
          element?.[property.value as keyof typeof element])
  if (type === 'image') value = null
  const node = makeNode('output', state.value, {
    target: targetId,
    property: property.value,
    type,
    inputs: [null],
    defaults: [(value ?? defaultValue(type)) as VariableValue],
  })
  place(node)
  selectedId.value = node.id
  palette.value = false
  // An explicit length is activated only by choosing manual sizing in the editor.
  changed()
}
function addPropertyInput() {
  if (graphLocked.value || !catalog.value || !readableProperties.value[property.value]) return
  const targetId = catalog.value.targets[target.value]!.id
  let node = state.value.nodes.find(
    (node) =>
      node.kind === 'property' && node.target === targetId && node.property === property.value,
  )
  if (!node) {
    node = makeNode('property', state.value, {
      target: targetId,
      property: property.value,
      type: readableProperties.value[property.value],
    })
    place(node)
    changed()
  }
  selectedId.value = node.id
  frame(node)
  palette.value = false
}
function disconnect(node: LogicNode, index: number) {
  if (graphLocked.value) return false
  const candidate = clone(node)
  const source = state.value.nodes.find((current) => current.id === node.inputs[index])
  candidate.inputs[index] = null
  const nodes = state.value.nodes.map((current) => (current.id === node.id ? candidate : current))
  try {
    try {
      validateGraphTypes(nodes, catalog.value!, [node.id])
    } catch (failure) {
      if (!source) throw failure
      // A hidden fallback from before this wire may have a different type.
      candidate.defaults[index] = defaultValue(typeOf(source))
      validateGraphTypes(nodes, catalog.value!, [node.id])
    }
    Object.assign(node, candidate)
    changed()
    return true
  } catch (failure) {
    announcement.value = errorMessage(failure)
    return false
  }
}
function removeSelected() {
  const node = selected.value
  if (graphLocked.value || !node || node.kind === 'input') return
  const nodes = clone(state.value.nodes).filter((candidate) => candidate.id !== node.id)
  const disconnected: { node: LogicNode; index: number }[] = []
  for (const candidate of nodes)
    candidate.inputs.forEach((id, index) => {
      if (id === node.id) {
        candidate.inputs[index] = null
        disconnected.push({ node: candidate, index })
      }
    })
  const affected = disconnected.map(({ node }) => node.id)
  try {
    try {
      validateGraphTypes(nodes, catalog.value!, affected)
    } catch {
      for (const connection of disconnected)
        connection.node.defaults[connection.index] = defaultValue(typeOf(node))
      validateGraphTypes(nodes, catalog.value!, affected)
    }
    state.value.nodes = nodes
    active.value = null
    selectedId.value = ''
    changed()
  } catch (failure) {
    announcement.value = errorMessage(failure)
  }
}
function label(node: LogicNode) {
  if (node.kind === 'input')
    return (
      props.document.fields.find((field) => field.name === node.name)?.label ?? node.name ?? 'Input'
    )
  if (node.kind === 'variable') return node.name ?? 'Intermediate'
  if (node.kind === 'literal') return `${title(node.type)} value`
  if (node.kind === 'call') return title(node.operation ?? '')
  const element = props.document.elements.find((element) => element.id === node.target)
  const name =
    node.target === 'label'
      ? `Label.${node.property}`
      : logicTargetLabel(
          props.document,
          element?.logic_name ?? node.target ?? '',
          node.property ?? undefined,
        )
  return `${node.kind === 'property' ? 'Read ' : ''}${name}`
}
function typeOf(node: LogicNode, depth = 0): SocketType {
  const type = catalog.value ? nodeType(node, state.value.nodes, catalog.value) : node.type
  // An empty image is still displayed as an image socket. Validation keeps null semantics.
  if (type === 'null' && node.kind === 'variable' && depth < 32) {
    const source = state.value.nodes.find((candidate) => candidate.id === node.inputs[0])
    if (source) return typeOf(source, depth + 1)
  }
  return type === 'null' && node.type === 'image' ? 'image' : type
}
function portType(node: LogicNode, index: number): SocketType {
  if (!catalog.value) return 'any'
  const expected = inputType(node, index, state.value.nodes, catalog.value)
  if (expected !== 'any') return expected
  const source = state.value.nodes.find((candidate) => candidate.id === node.inputs[index])
  const type = source ? typeOf(source) : valueType(node.defaults[index] ?? null)
  return type === 'null' && node.type === 'image' ? 'image' : type
}
function fallbackType(node: LogicNode, index: number): ValueType {
  const type = portType(node, index)
  return type === 'null' || type === 'any' ? node.type : type
}
function changeValueType(node: LogicNode, indices: number[], event: Event) {
  const control = event.target as HTMLSelectElement
  const previous =
    indices.length > 1
      ? pairedType(node, state.value.nodes, catalog.value!)
      : fallbackType(node, indices[0]!)
  const candidate = clone(node)
  candidate.type = control.value as ValueType
  for (const index of indices)
    if (valueType(candidate.defaults[index] ?? null) !== candidate.type)
      candidate.defaults[index] = defaultValue(candidate.type)
  const nodes = state.value.nodes.map((current) => (current.id === node.id ? candidate : current))
  try {
    validateGraphTypes(nodes, catalog.value!, [node.id])
    Object.assign(node, candidate)
    announcement.value = ''
    changed()
  } catch (failure) {
    control.value = previous
    announcement.value = errorMessage(failure)
  }
}
function allowsNull(node: LogicNode, index: number) {
  const type = inputType(node, index, state.value.nodes, catalog.value!)
  return type === 'any' || type === 'image' || pairedInputs(node).includes(index)
}
function choose(id: string, port: number) {
  if (suppressClick) {
    suppressClick = false
    return
  }
  if (graphLocked.value) return
  if (active.value?.id === id && active.value.port === port) {
    cancel()
    return
  }
  if (!active.value) {
    active.value = { id, port }
    announcement.value = 'Connector selected. Choose a compatible connector.'
    return
  }
  const first = active.value
  if ((first.port === -1) === (port === -1)) {
    announcement.value = 'Choose an input and an output.'
    return
  }
  const source = state.value.nodes.find((node) => node.id === (port === -1 ? id : first.id))!
  const destination = state.value.nodes.find((node) => node.id === (port === -1 ? first.id : id))!
  const index = port === -1 ? first.port : port
  if (destination.inputs[index] === source.id) {
    if (disconnect(destination, index)) {
      active.value = null
      announcement.value = `Disconnected ${label(source)} from ${label(destination)}, ${socketLabel(destination, index)}.`
    }
    return
  }
  try {
    canConnect(source, destination, index, state.value.nodes, catalog.value!, upgraded())
    destination.inputs[index] = source.id
    announcement.value = `Connected ${label(source)} to ${label(destination)}, ${socketLabel(destination, index)}.`
    active.value = null
    changed()
  } catch (failure) {
    announcement.value = errorMessage(failure)
  }
}
function cancel() {
  active.value = null
  announcement.value = 'Connection cancelled.'
}
function point(id: string, port: number) {
  const node = state.value.nodes.find((node) => node.id === id)!
  return { x: node.x + (port === -1 ? 226 : 18), y: node.y + 58 + Math.max(port, 0) * 36 }
}
function path(a: { x: number; y: number }, b: { x: number; y: number }) {
  const bend = b.x < a.x ? 60 : Math.max(60, (b.x - a.x) / 2)
  return `M${a.x},${a.y} C${a.x + bend},${a.y} ${b.x - bend},${b.y} ${b.x},${b.y}`
}
const wires = computed(() =>
  state.value.nodes.flatMap((node) =>
    node.inputs.flatMap((id, port) =>
      id && state.value.nodes.some((source) => source.id === id)
        ? [
            {
              key: `${node.id}:${port}`,
              path: path(point(id, -1), point(node.id, port)),
              node,
              port,
            },
          ]
        : [],
    ),
  ),
)
const draftWire = computed(() =>
  active.value && state.value.nodes.some((node) => node.id === active.value?.id)
    ? active.value.port === -1
      ? path(point(active.value.id, -1), pointer.value)
      : path(pointer.value, point(active.value.id, active.value.port))
    : '',
)
function startNode(event: PointerEvent, node: LogicNode) {
  if (gesture || graphLocked.value || event.button !== 0) return
  selectedId.value = node.id
  gesture = {
    kind: 'node',
    pointerId: event.pointerId,
    id: node.id,
    x: event.clientX,
    y: event.clientY,
    startX: node.x,
    startY: node.y,
    moved: false,
  }
  event.preventDefault()
}
function startPan(event: PointerEvent) {
  if (gesture || event.button > 1 || (event.target as HTMLElement).closest('.logic-node')) return
  cancel()
  gesture = {
    kind: 'pan',
    pointerId: event.pointerId,
    x: event.clientX,
    y: event.clientY,
    startX: state.value.x,
    startY: state.value.y,
    moved: false,
  }
}
function startWire(event: PointerEvent, id: string, port: number) {
  if (gesture || graphLocked.value || event.button !== 0) return
  gesture = {
    kind: 'wire',
    pointerId: event.pointerId,
    id,
    port,
    x: event.clientX,
    y: event.clientY,
    startX: 0,
    startY: 0,
    moved: false,
  }
}
const bound = (value: number) => Math.max(-100000, Math.min(100000, value))
function move(event: PointerEvent) {
  const rect = canvas.value?.getBoundingClientRect()
  if (rect)
    pointer.value = {
      x: (event.clientX - rect.left - state.value.x) / state.value.zoom,
      y: (event.clientY - rect.top - state.value.y) / state.value.zoom,
    }
  if (!gesture || gesture.pointerId !== event.pointerId) return
  const dx = event.clientX - gesture.x,
    dy = event.clientY - gesture.y
  if (Math.hypot(dx, dy) > 5) gesture.moved = true
  if (gesture.kind === 'wire' && gesture.moved)
    active.value = { id: gesture.id!, port: gesture.port! }
  else if (gesture.kind === 'pan') {
    state.value.x = bound(gesture.startX + dx)
    state.value.y = bound(gesture.startY + dy)
  } else if (gesture.kind === 'node') {
    const node = state.value.nodes.find((node) => node.id === gesture!.id)
    if (node) {
      node.x = bound(gesture.startX + dx / state.value.zoom)
      node.y = bound(gesture.startY + dy / state.value.zoom)
    }
  }
}
function end(event: PointerEvent) {
  if (!gesture || gesture.pointerId !== event.pointerId) return
  if (gesture.moved && gesture.kind === 'wire') {
    const socket = document
      .elementFromPoint(event.clientX, event.clientY)
      ?.closest<HTMLElement>('[data-port]')
    if (socket) choose(socket.dataset.node!, Number(socket.dataset.port))
    else cancel()
    suppressClick = true
    setTimeout(() => {
      suppressClick = false
    }, 0)
  } else if (gesture.moved) persistLayout()
  gesture = null
}
function zoom(factor: number, clientX?: number, clientY?: number) {
  const rect = canvas.value?.getBoundingClientRect()
  if (!rect) return
  const x = clientX === undefined ? rect.width / 2 : clientX - rect.left,
    y = clientY === undefined ? rect.height / 2 : clientY - rect.top
  const previous = state.value.zoom,
    next = Math.max(0.25, Math.min(2, previous * factor))
  state.value.x = bound(x - ((x - state.value.x) * next) / previous)
  state.value.y = bound(y - ((y - state.value.y) * next) / previous)
  state.value.zoom = next
}
function wheel(event: WheelEvent) {
  zoom(event.deltaY < 0 ? 1.1 : 1 / 1.1, event.clientX, event.clientY)
}
function frame(node?: LogicNode) {
  const nodes = node ? [node] : state.value.nodes,
    rect = canvas.value?.getBoundingClientRect()
  if (!nodes.length || !rect) return
  const left = Math.min(...nodes.map((node) => node.x)),
    top = Math.min(...nodes.map((node) => node.y))
  const width = Math.max(...nodes.map((node) => node.x + 244)) - left,
    height = Math.max(...nodes.map((node) => node.y + 90 + node.inputs.length * 36)) - top
  state.value.zoom = Math.max(
    0.25,
    Math.min(1, (rect.width - 48) / width, (rect.height - 48) / height),
  )
  state.value.x = 24 - left * state.value.zoom
  state.value.y = 24 - top * state.value.zoom
}
function keyboard(event: KeyboardEvent, node?: LogicNode) {
  if ((event.target as HTMLElement).matches('input,select,textarea')) return
  if (event.key === 'Escape') {
    cancel()
    palette.value = false
    return
  }
  if (node && ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(event.key)) {
    event.preventDefault()
    event.stopPropagation()
    if (graphLocked.value) return
    const step = event.shiftKey ? 50 : 10
    node.x = bound(
      node.x + (event.key === 'ArrowLeft' ? -step : event.key === 'ArrowRight' ? step : 0),
    )
    node.y = bound(
      node.y + (event.key === 'ArrowUp' ? -step : event.key === 'ArrowDown' ? step : 0),
    )
    persistLayout()
  }
}
window.addEventListener('pointermove', move)
window.addEventListener('pointerup', end)
window.addEventListener('pointercancel', cancelGesture)
function cancelGesture() {
  gesture = null
  cancel()
}
onBeforeUnmount(() => {
  stopped = true
  sourceSequence++
  clearTimeout(sourceTimer)
  sequence++
  clearTimeout(timer)
  window.removeEventListener('pointermove', move)
  window.removeEventListener('pointerup', end)
  window.removeEventListener('pointercancel', cancelGesture)
})
</script>

<template>
  <section class="panel logic-workspace" :class="{ expanded }" @keydown.esc="cancel">
    <div class="section-heading">
      <h2>
        <button
          class="text-button logic-heading"
          :aria-expanded="open"
          aria-controls="logic-workspace-body"
          @click="toggle"
        >
          {{ $t('common.templateLogic') }}<ChevronDownIcon :class="{ collapsed: !open }" />
        </button>
      </h2>
      <button v-if="open" class="small" :aria-pressed="expanded" @click="expanded = !expanded">
        <ArrowsPointingOutIcon />{{ expanded ? 'Restore view' : 'Expand view' }}
      </button>
    </div>
    <ExpandableContent id="logic-workspace-body" :open="open">
      <p v-if="loading" role="status">{{ $t('logicWorkspace.loadingLogic') }}</p>
      <template v-if="catalog">
        <div class="row wrap logic-modes">
          <MotionTrack
            role="tablist"
            :aria-label="$t('logicWorkspace.logicEditorMode')"
            class="inspector-tabs"
            :identity="mode"
            selector="[aria-selected='true']"
            underline
          >
            <button
              id="logic-nodes-tab"
              role="tab"
              :aria-selected="mode === 'nodes'"
              :tabindex="mode === 'nodes' ? 0 : -1"
              aria-controls="logic-nodes-panel"
              @click="selectMode('nodes')"
              @keydown="modeKeys"
            >
              {{ $t('logicWorkspace.nodes') }}
            </button>
            <button
              id="logic-source-tab"
              role="tab"
              :aria-selected="mode === 'source'"
              :tabindex="mode === 'source' ? 0 : -1"
              aria-controls="logic-source-panel"
              @click="selectMode('source')"
              @keydown="modeKeys"
            >
              {{ $t('common.source') }}
            </button>
          </MotionTrack>
          <button
            :aria-expanded="referenceOpen"
            aria-controls="logic-reference-panel"
            @click="referenceOpen = !referenceOpen"
          >
            {{ $t('logicWorkspace.reference') }}
          </button>
        </div>
        <MotionSurface :identity="mode" :order="mode === 'nodes' ? 0 : 1">
          <div
            v-show="mode === 'nodes'"
            id="logic-nodes-panel"
            role="tabpanel"
            aria-labelledby="logic-nodes-tab"
            :inert="mode !== 'nodes'"
          >
            <p v-if="sourceDirty" class="alert warning">
              {{ $t('common.sourceHasUnappliedChangesNodesShowTheLastValid') }}
            </p>
            <div class="row wrap logic-toolbar">
              <button :disabled="graphLocked" :aria-expanded="palette" @click="palette = !palette">
                <PlusIcon />{{ $t('logicWorkspace.addNode') }}
              </button>
              <button :aria-label="$t('common.zoomOutLogic')" @click="zoom(1 / 1.2)">
                <MinusIcon />
              </button>
              <output :aria-label="$t('logicWorkspace.logicZoom')"
                >{{ Math.round(state.zoom * 100) }}%</output
              >
              <button :aria-label="$t('common.zoomInLogic')" @click="zoom(1.2)">
                <PlusIcon />
              </button>
              <button @click="frame()">{{ $t('logicWorkspace.frameNodes') }}</button>
              <span v-if="pending && !error" role="status">{{
                $t('logicWorkspace.checking')
              }}</span>
            </div>
            <ExpandableContent :open="palette">
              <div class="node-palette">
                <label
                  >{{ $t('common.searchNodes') }}<input v-model="search" type="search"
                /></label>
                <div class="node-options">
                  <button
                    v-for="type in valueTypes.filter((type) =>
                      `${type} value`.includes(search.toLowerCase()),
                    )"
                    :key="type"
                    @click="add('literal', type)"
                  >
                    {{ title(type) }} {{ $t('common.value2') }}
                  </button>
                  <button
                    v-if="'intermediate variable'.includes(search.toLowerCase())"
                    @click="add('variable', '')"
                  >
                    {{ $t('logicWorkspace.intermediateVariable') }}
                  </button>
                  <button
                    v-for="operation in operations"
                    :key="operation.name"
                    :title="operation.description"
                    @click="add('call', operation.name)"
                  >
                    {{ title(operation.name) }}
                  </button>
                </div>
                <div class="field-row">
                  <label
                    >{{ $t('logicWorkspace.propertyTarget')
                    }}<select v-model="target">
                      <option
                        v-for="alias in Object.keys(catalog.targets)"
                        :key="alias"
                        :value="alias"
                      >
                        {{ logicTargetLabel(document, alias) }}
                      </option>
                    </select></label
                  >
                  <label
                    >{{ $t('logicWorkspace.property')
                    }}<select v-model="property">
                      <option v-for="(type, name) in availableProperties" :key="name" :value="name">
                        {{ name }} ({{ type }})
                      </option>
                    </select></label
                  >
                  <button :disabled="!readableProperties[property]" @click="addPropertyInput">
                    {{ $t('logicWorkspace.readProperty') }}
                  </button>
                  <button :disabled="bindingDisabled" @click="addOutput">
                    {{ $t('logicWorkspace.bindProperty') }}
                  </button>
                </div>
              </div>
            </ExpandableContent>
            <div class="logic-layout">
              <div
                ref="canvas"
                class="logic-canvas"
                tabindex="0"
                :aria-label="$t('logicWorkspace.logicNodeCanvas')"
                @pointerdown="startPan"
                @wheel.prevent="wheel"
                @keydown="keyboard($event)"
              >
                <TransitionGroup
                  name="logic-node"
                  tag="div"
                  class="node-world"
                  :style="{
                    transform: `translate(${state.x}px, ${state.y}px) scale(${state.zoom})`,
                  }"
                >
                  <svg key="wires" class="logic-wires" aria-hidden="true">
                    <path v-for="wire in wires" :key="wire.key" :d="wire.path" />
                    <path v-if="active" class="draft-wire" :d="draftWire" />
                  </svg>
                  <article
                    v-for="node in state.nodes"
                    :key="node.id"
                    class="logic-node"
                    :class="{
                      selected: selectedId === node.id,
                      inactive: automaticOutput(node, document),
                    }"
                    :style="{ left: `${node.x}px`, top: `${node.y}px` }"
                    :aria-label="label(node)"
                    @click.stop="selectedId = node.id"
                    @pointerdown.stop="startNode($event, node)"
                  >
                    <header
                      tabindex="0"
                      :aria-label="`Move ${label(node)}`"
                      @focus="selectedId = node.id"
                      @keydown="keyboard($event, node)"
                    >
                      {{ label(node) }}
                    </header>
                    <div v-if="!node.inputs.length" class="node-port-row">
                      <span class="node-value">{{
                        node.kind === 'input'
                          ? displayValue(catalog.values[node.name!] ?? null)
                          : node.kind === 'property'
                            ? displayValue(
                                catalog.property_values?.[node.target!]?.[node.property!] ?? null,
                              )
                            : displayValue(node.value ?? null) || title(node.type)
                      }}</span>
                    </div>
                    <div v-for="(source, index) in node.inputs" :key="index" class="node-port-row">
                      <LogicSocket
                        :type="portType(node, index)"
                        :disabled="!!disabledOutput(node)"
                        :title="disabledOutput(node)"
                        :label="`${label(node)} ${socketLabel(node, index)} input (${portType(node, index)})`"
                        :node="node.id"
                        :port="index"
                        :selected="active?.id === node.id && active.port === index"
                        :connected="!!source"
                        @choose="choose(node.id, index)"
                        @start="startWire($event, node.id, index)"
                      />
                      <span
                        >{{ socketLabel(node, index)
                        }}<small v-if="!source"
                          >:
                          {{
                            displayValue(node.defaults[index] ?? null) || $t('variableInput.notSet')
                          }}</small
                        ></span
                      >
                    </div>
                    <div v-if="node.kind !== 'output'" class="node-output">
                      <LogicSocket
                        :type="typeOf(node)"
                        :label="`${label(node)} output (${typeOf(node)})`"
                        :node="node.id"
                        :port="-1"
                        :selected="active?.id === node.id && active.port === -1"
                        :connected="
                          state.nodes.some((candidate) => candidate.inputs.includes(node.id))
                        "
                        @choose="choose(node.id, -1)"
                        @start="startWire($event, node.id, -1)"
                      />
                    </div>
                    <small v-if="node.kind === 'variable'" class="node-result">{{
                      displayValue(catalog.values[node.name!] ?? null)
                    }}</small>
                    <small v-if="automaticOutput(node, document)" class="node-result">{{
                      $t('logicWorkspace.inactiveAutomaticSizing')
                    }}</small>
                  </article>
                </TransitionGroup>
                <p v-if="!state.nodes.length" class="canvas-empty">
                  {{ $t('logicWorkspace.addANodeOrBindAProperty') }}
                </p>
              </div>
              <aside
                class="node-inspector form-stack"
                :aria-label="$t('logicWorkspace.nodeProperties')"
              >
                <label
                  >{{ $t('logicWorkspace.node')
                  }}<select v-model="selectedId" @change="selected && frame(selected)">
                    <option value="">{{ $t('logicWorkspace.chooseNode') }}</option>
                    <option v-for="node in state.nodes" :key="node.id" :value="node.id">
                      {{ label(node) }}
                    </option>
                  </select></label
                >
                <MotionSurface :identity="selectedId" class="form-stack">
                  <template v-if="selected">
                    <h3>{{ label(selected) }}</h3>
                    <button class="small" @click="nodeHelp(selected)">
                      {{ $t('logicWorkspace.nodeReference') }}
                    </button>
                    <p v-if="selected.kind === 'call'" class="help">
                      {{
                        catalog.operations.find(
                          (operation) => operation.name === selected?.operation,
                        )?.description
                      }}
                    </p>
                    <label v-if="selected.kind === 'variable'"
                      >{{ $t('common.variableName')
                      }}<input
                        v-model="selected.name"
                        maxlength="40"
                        :disabled="graphLocked"
                        @change="changed"
                    /></label>
                    <VariableInput
                      v-if="selected.kind === 'literal'"
                      v-model="selected.value"
                      :field="literalField"
                      :label="$t('common.value')"
                      :disabled="graphLocked"
                      nullable
                      @change="changed"
                    />
                    <label v-if="valueTypeInputs.length"
                      >{{ $t('common.valueType')
                      }}<select
                        :value="selectedValueType"
                        :disabled="
                          graphLocked || valueTypeInputs.some((index) => !!selected!.inputs[index])
                        "
                        @change="changeValueType(selected, valueTypeInputs, $event)"
                      >
                        <option v-for="type in valueTypes" :key="type" :value="type">
                          {{ title(type) }}
                        </option>
                      </select></label
                    >
                    <template
                      v-for="(source, index) in selected.inputs"
                      :key="`${selected.id}:${index}`"
                    >
                      <div v-if="source" class="connected-input">
                        <span
                          >{{ socketLabel(selected, index) }} ←
                          {{ label(state.nodes.find((node) => node.id === source)!) }}</span
                        ><button
                          class="small"
                          :disabled="graphLocked"
                          :aria-label="`Disconnect ${socketLabel(selected, index)}`"
                          @click="disconnect(selected, index)"
                        >
                          {{ $t('logicWorkspace.disconnect') }}
                        </button>
                      </div>
                      <template v-else>
                        <VariableInput
                          v-model="selected.defaults[index]"
                          :field="fallbackFields[index]!"
                          :label="socketLabel(selected, index)"
                          :disabled="graphLocked || !!disabledOutput(selected)"
                          :nullable="allowsNull(selected, index)"
                          @change="changed"
                        />
                      </template>
                    </template>
                    <button
                      v-if="selected.kind !== 'input'"
                      class="danger-text"
                      :disabled="graphLocked"
                      @click="removeSelected"
                    >
                      <TrashIcon />{{ $t('logicWorkspace.removeNode') }}
                    </button>
                  </template>
                </MotionSurface>
                <img
                  v-if="preview"
                  :src="preview"
                  :style="previewGeometry"
                  :alt="$t('logicWorkspace.logicLabelPreview')"
                  class="logic-preview"
                />
              </aside>
            </div>
            <p v-if="previewError || catalog.sample_error" class="alert danger" role="alert">
              {{ previewError || catalog.sample_error }}
            </p>
            <p class="logic-status" role="status" aria-live="polite">{{ announcement }}</p>
          </div>
          <div
            v-show="mode === 'source'"
            id="logic-source-panel"
            role="tabpanel"
            aria-labelledby="logic-source-tab"
            :inert="mode !== 'source'"
            class="source-panel"
          >
            <p v-if="pending" class="alert warning">
              {{ $t('logicWorkspace.resolveOrRevertNodeChangesBeforeEditingSource') }}
            </p>
            <div class="source-layout">
              <LogicSourceEditor
                v-if="sourceMounted"
                :source="sourceText"
                :catalog="catalog"
                :document="document"
                :diagnostics="sourceDiagnostics"
                :disabled="disabled || pending"
                :active="mode === 'source'"
                @change="editSource"
                @help="showReference"
              />
              <div class="source-preview">
                <img
                  v-if="preview"
                  :src="preview"
                  :style="previewGeometry"
                  :alt="$t('common.sourceLabelPreview')"
                />
                <p v-if="previewError || catalog.sample_error" class="alert danger" role="alert">
                  {{ previewError || catalog.sample_error }}
                </p>
              </div>
            </div>
            <div class="row wrap source-toolbar">
              <span v-if="sourceBusy" role="status">{{ $t('logicWorkspace.checkingSource') }}</span
              ><button v-if="sourceDirty" @click="revertSource">
                {{ $t('logicWorkspace.revertSourceChanges') }}
              </button>
            </div>
          </div>
        </MotionSurface>
        <ExpandableContent id="logic-reference-panel" :open="referenceOpen"
          ><LogicReference
            :catalog="catalog"
            :document="document"
            :entry="referenceEntry"
            :request="referenceRequest"
        /></ExpandableContent>
      </template>
      <div v-if="error" class="alert danger" role="alert">
        {{ error
        }}<button class="text-button" @click="initialize">
          {{ $t('logicWorkspace.revertNodeChanges') }}
        </button>
      </div>
    </ExpandableContent>
  </section>
</template>

<style scoped>
.logic-canvas,
.logic-workspace button {
  -webkit-user-select: none;
  user-select: none;
}
.logic-modes {
  justify-content: space-between;
  margin-top: 16px;
}
.logic-modes .inspector-tabs {
  margin: 0;
}
.source-panel {
  padding-top: 16px;
  min-width: 0;
}
.source-toolbar {
  min-height: 42px;
  margin-top: 8px;
}
.source-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 240px;
  gap: 16px;
  align-items: start;
}
.source-layout > * {
  min-width: 0;
}
.source-panel :deep(.cm-scroller) {
  transition: min-height var(--motion-state) var(--motion-ease);
}
.expanded .source-panel :deep(.cm-scroller) {
  min-height: 60vh;
  max-height: 75vh;
}
.source-preview img,
.logic-preview {
  display: block;
  width: min(100%, calc(140px * var(--label-ratio)));
  height: auto;
  aspect-ratio: var(--label-ratio);
}
.logic-heading {
  display: flex;
  align-items: center;
  gap: 12px;
  color: inherit;
  font: inherit;
}
.logic-heading svg {
  transition: transform var(--motion-state) var(--motion-ease);
}
.logic-heading svg.collapsed {
  transform: rotate(-90deg);
}
.logic-workspace .section-heading {
  margin-bottom: 0;
}
.logic-toolbar {
  padding-block: 16px;
}
.logic-toolbar button svg,
.section-heading button svg,
.node-inspector button svg {
  width: 20px;
  height: 20px;
}
.node-palette {
  display: grid;
  gap: 16px;
  padding-bottom: 16px;
}
.node-options {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  max-height: 160px;
  overflow: auto;
}
.logic-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 240px;
  border: 1px solid var(--line);
  border-radius: 12px;
  overflow: hidden;
}
.logic-canvas {
  position: relative;
  min-width: 0;
  height: 520px;
  transition: height var(--motion-state) var(--motion-ease);
  overflow: hidden;
  background-color: var(--surface-deepest);
  background-image: radial-gradient(var(--line) 1px, transparent 1px);
  background-size: 24px 24px;
  touch-action: none;
}
.node-world {
  position: absolute;
  transform-origin: 0 0;
  width: 1px;
  height: 1px;
}
.logic-wires {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: visible;
  pointer-events: none;
}
.logic-wires path {
  stroke: var(--muted);
  stroke-width: 2;
  fill: none;
}
.logic-wires .draft-wire {
  stroke: var(--ink);
  stroke-dasharray: 6 5;
}
.logic-node {
  cursor: grab;
  touch-action: none;
  position: absolute;
  width: 244px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--surface);
  padding-bottom: 6px;
}
.logic-node-enter-active {
  transition:
    opacity var(--motion-enter) var(--motion-ease),
    transform var(--motion-enter) var(--motion-ease);
}
.logic-node-leave-active {
  transition:
    opacity var(--motion-state) var(--motion-ease),
    transform var(--motion-state) var(--motion-ease);
  pointer-events: none;
}
.logic-node-enter-from,
.logic-node-leave-to {
  opacity: 0;
  transform: scale(0.96);
}
:global(:root[data-motion='reduce']) .logic-node-enter-active,
:global(:root[data-motion='reduce']) .logic-node-leave-active {
  transition-duration: 1ms;
}
:global(:root[data-motion='reduce']) .logic-node-enter-from,
:global(:root[data-motion='reduce']) .logic-node-leave-to {
  transform: none;
}
.logic-node.selected {
  outline: 2px solid var(--accent-hover);
}
.logic-node.inactive {
  border-style: dashed;
}
.logic-node header {
  height: 40px;
  padding: 10px 14px;
  box-sizing: border-box;
  border-bottom: 1px solid var(--line);
  cursor: grab;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
  touch-action: none;
}
.node-port-row {
  display: flex;
  align-items: center;
  height: 36px;
  padding-right: 38px;
}
.node-port-row span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.node-value {
  padding-left: 14px;
}
.node-port-row small,
.node-result {
  color: var(--muted);
}
.node-result {
  display: block;
  padding: 4px 14px;
}
.node-output {
  position: absolute;
  right: 0;
  top: 40px;
}
.node-inspector {
  padding: 16px;
  border-left: 1px solid var(--line);
  min-width: 0;
  max-height: 520px;
  overflow: auto;
  align-content: start;
}
.node-inspector h3 {
  overflow-wrap: anywhere;
  margin: 0;
}
.connected-input {
  display: grid;
  gap: 8px;
  overflow-wrap: anywhere;
}
.logic-preview {
  margin-top: 12px;
  image-rendering: pixelated;
}
.canvas-empty {
  padding: 24px;
  color: var(--muted);
}
.logic-status {
  min-height: 1.5em;
  margin-bottom: 0;
}
.expanded .logic-canvas {
  height: 75vh;
}
.expanded .node-inspector {
  max-height: 75vh;
}
@media (max-width: 760px) {
  .source-layout {
    grid-template-columns: minmax(0, 1fr);
  }
  .logic-layout {
    grid-template-columns: minmax(0, 1fr);
  }
  .node-inspector {
    border-left: 0;
    border-top: 1px solid var(--line);
    max-height: 380px;
  }
  .logic-preview {
    max-width: 320px;
  }
  .logic-canvas {
    height: 480px;
  }
}
</style>
