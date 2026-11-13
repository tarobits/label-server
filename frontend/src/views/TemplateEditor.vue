<script setup lang="ts">
import { t } from '../shared/i18n'

import SettingHelp from '../components/SettingHelp.vue'
import FontWeightControl from '../components/FontWeightControl.vue'
import TapeProfilePicker from '../components/TapeProfilePicker.vue'
import { editorHelp } from '../templates/editorHelp'
import { confirmAction } from '../shared/confirmation'
import { mediaProperties, compatibleProfile } from '../printing/media'
import EditorRuler from '../components/EditorRuler.vue'
import ElementDetails from '../components/ElementDetails.vue'
import PropertySection from '../components/PropertySection.vue'
import MotionSurface from '../components/MotionSurface.vue'
import MotionTrack from '../components/MotionTrack.vue'
import TemplateHistory from '../components/TemplateHistory.vue'
import VariableInput from '../components/VariableInput.vue'
import TemplatePreviewInputs from '../components/TemplatePreviewInputs.vue'
import ExpandableContent from '../components/ExpandableContent.vue'
import {
  copyExpression,
  nextElementName,
  renameField,
  setFieldType,
  visitReferences,
} from '../templates/variableInputs'
import { decodeLabel } from '../printing/labelPreview'
import {
  PhotoIcon,
  LanguageIcon,
  QrCodeIcon,
  StopIcon,
  MinusIcon,
  ViewColumnsIcon,
  Squares2X2Icon,
  ChevronLeftIcon,
  ChevronRightIcon,
} from '@heroicons/vue/24/outline'
import { computed, defineAsyncComponent, onMounted, onUnmounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { api, errorMessage } from '../shared/api'
import { useAuthStore } from '../auth/auth'
import { useWorkspaceStore } from '../shared/workspace'
import { useResourceStore } from '../stores/resources'
import { randomUUID } from '../shared/uuid'
import {
  newDocument,
  newElement,
  elementGeometry,
  setElementGeometry,
  automaticDimension,
  type Element,
  type Preview,
  type TemplateDocument,
  type TemplateField,
  type ValueType,
} from '../templates/editor'
import type { ImageAsset, Template } from '../shared/types'
const LogicWorkspace = defineAsyncComponent(() => import('../components/LogicWorkspace.vue'))
const w = useWorkspaceStore()
const resources = useResourceStore()
const auth = useAuthStore()
const route = useRoute(),
  router = useRouter()
const document = ref<TemplateDocument>(newDocument()),
  name = ref(t('uiMessages.untitledLabel')),
  id = ref<string | null>(null),
  revision = ref(0)
const scope = ref<'personal' | 'group' | 'global'>('personal'),
  groupId = ref<string | null>(null)
const revisionHistoryOpen = ref(false)
const logicBlocked = ref(false)
function applyLogic(value: TemplateDocument) {
  document.value = value
  record()
}
function showRevisionHistory(event: MouseEvent) {
  ;(event.currentTarget as HTMLElement).focus()
  revisionHistoryOpen.value = true
}
function applyRestoredRevision(template: Template) {
  name.value = template.name
  document.value = structuredClone(template.document)
  revision.value = template.revision
  scope.value = template.scope ?? scope.value
  groupId.value = template.group_id ?? null
  originalSharing.value = { scope: scope.value, group_id: groupId.value }
  selectedId.value = ''
  saved.value = snapshot()
  history.value = [saved.value]
  cursor.value = 0
}
const ownerId = ref<string | null>(null)
const originalSharing = ref<{ scope: string; group_id: string | null }>({
  scope: 'personal',
  group_id: null,
})
const canChangeSharing = computed(
  () => !id.value || auth.user?.is_admin || ownerId.value === auth.user?.id,
)
const userGroups = ref<{ id: string; name: string }[]>([])
const availableGroups = computed(() =>
  userGroups.value.filter(
    (group) =>
      auth.user?.is_admin ||
      (id.value &&
        originalSharing.value.scope === 'group' &&
        group.id === originalSharing.value.group_id) ||
      auth.user?.group_memberships?.[group.id]?.can_create,
  ),
)
const editable = ref(true)
const imageFile = ref<File | null>(null)
const imageInput = ref<HTMLInputElement | null>(null)
const widthInput = ref<HTMLInputElement | null>(null)
const selectedId = ref(typeof route.query.element === 'string' ? route.query.element : ''),
  zoom = ref(100),
  snap = ref(true),
  showPrintPixels = ref(true),
  showBounds = ref(true)
const pointer = ref<{ x: number; y: number } | null>(null)
const resolutionModes = ref<Record<string, [number, number]>>({})
const defaultResolution = ref<[number, number]>([180, 180])
const paddingSides = ['top', 'right', 'bottom', 'left'] as const
const preview = ref<Preview | null>(null),
  error = ref(''),
  rendering = ref(false),
  ready = ref(false)
const previewExampleId = ref('')
const previewExample = computed(() =>
  document.value.preview_examples?.find((example) => example.id === previewExampleId.value),
)
function browseCanvasExample(offset: number) {
  const examples = document.value.preview_examples ?? []
  if (!examples.length) return
  const index = examples.findIndex((example) => example.id === previewExampleId.value)
  const next =
    index < 0
      ? offset < 0
        ? examples.length - 1
        : 0
      : (index + offset + examples.length) % examples.length
  previewExampleId.value = examples[next]!.id
}
const previewData = computed(() =>
  Object.fromEntries(
    document.value.fields
      .filter(
        (field) => previewExample.value && Object.hasOwn(previewExample.value.data, field.name),
      )
      .map((field) => [field.name, previewExample.value!.data[field.name]!]),
  ),
)
const sampleProfile = computed({
  get: () => document.value.preview_tape?.id ?? '',
  set: (id: string) => {
    const profile = w.profiles.find((p) => p.id === id)
    if (!profile || profile.available === false) return
    document.value.preview_tape = {
      id: profile.id,
      name: profile.name,
      foreground: profile.foreground,
      background: profile.background,
    }
    document.value.width_mm = profile.width_mm
    document.value.media = mediaProperties(profile)
    if (profile.media_family === 'fixed_label') {
      document.value.auto_length = false
      document.value.length_mm = profile.label_length_mm!
      document.value.logic?.bindings.splice(
        0,
        document.value.logic.bindings.length,
        ...document.value.logic.bindings.filter((binding) => binding.target !== 'label'),
      )
    }
    record()
  },
})
const selectedProfile = computed(() => w.profiles.find((p) => p.id === sampleProfile.value))
const saved = ref(''),
  history = ref<string[]>([]),
  cursor = ref(0),
  margin = ref(1)
const printableWidths = ref<Record<string, number>>({})
const printableBand = computed(() => {
  const band = printableWidths.value[String(document.value.width_mm)]
  if (!band) return { top: margin.value, height: document.value.width_mm - 2 * margin.value }
  const dpi =
    resolutionModes.value[document.value.print_resolution ?? 'printer']?.[1] ??
    defaultResolution.value[1]
  const pixels = Math.round((document.value.width_mm * dpi) / 25.4)
  const rows = Math.min(pixels, Math.round((band * dpi) / 25.4))
  return {
    top: (Math.floor((pixels - rows) / 2) * document.value.width_mm) / pixels,
    height: (rows * document.value.width_mm) / pixels,
  }
})
const verticalMargin = computed(() => printableBand.value.top)
const printableBorder = computed(() => {
  const background = document.value.preview_tape?.background ?? '#ffffff'
  const channels = [1, 3, 5].map((offset) => {
    const value = parseInt(background.slice(offset, offset + 2), 16) / 255
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
  })
  const luminance = channels[0]! * 0.2126 + channels[1]! * 0.7152 + channels[2]! * 0.0722
  return luminance > 0.179 ? '#000000' : '#ffffff'
})
const selected = computed(() => document.value.elements.find((e) => e.id === selectedId.value))
const elementTitles = {
  get text() {
    return t('common.text')
  },
  get qr() {
    return t('remainingUi.qRCode')
  },
  get barcode() {
    return t('templateEditor.barcode')
  },
  get datamatrix() {
    return t('templateEditor.dataMatrix')
  },
  get aztec() {
    return t('uiMessages.aztecCode')
  },
  get image() {
    return t('templateEditor.image')
  },
  get rectangle() {
    return t('templateEditor.rectangle')
  },
  get line() {
    return t('logicSourceEditor.line')
  },
}
type InspectorTab = 'content' | 'style' | 'layout'
const activeInspector = ref<InspectorTab>('content')
const inspectorRoot = ref<HTMLElement | null>(null)
watch(
  [selectedId, activeInspector],
  () => {
    inspectorRoot.value?.querySelector('.editor-property-sections')?.scrollTo({ top: 0 })
  },
  { flush: 'post' },
)
const inspectorTabs = computed(() =>
  [
    {
      id: 'content' as const,
      get label() {
        return t('templateEditor.content')
      },
    },
    {
      id: 'style' as const,
      get label() {
        return t('uiMessages.style')
      },
    },
    {
      id: 'layout' as const,
      get label() {
        return t('uiMessages.layout')
      },
    },
  ].filter((tab) =>
    tab.id === 'content'
      ? ['text', 'qr', 'barcode', 'datamatrix', 'aztec', 'image'].includes(
          selected.value?.kind ?? '',
        )
      : tab.id === 'style'
        ? !['qr', 'barcode', 'datamatrix', 'aztec'].includes(selected.value?.kind ?? '')
        : true,
  ),
)
watch(
  inspectorTabs,
  (tabs) => {
    if (!selected.value) return
    if (!tabs.some((tab) => tab.id === activeInspector.value)) activeInspector.value = tabs[0]!.id
  },
  { immediate: true },
)
function moveInspectorTab(event: KeyboardEvent) {
  const tabs = inspectorTabs.value
  const index = tabs.findIndex((tab) => tab.id === activeInspector.value)
  let next = index
  if (event.key === 'ArrowRight') next = (index + 1) % tabs.length
  else if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length
  else if (event.key === 'Home') next = 0
  else if (event.key === 'End') next = tabs.length - 1
  else return
  event.preventDefault()
  activeInspector.value = tabs[next]!.id
  ;(event.currentTarget as HTMLElement).parentElement
    ?.querySelector<HTMLButtonElement>(`#inspector-${activeInspector.value}-tab`)
    ?.focus()
}
const snapshot = () =>
  JSON.stringify({
    name: name.value,
    document: document.value,
    scope: scope.value,
    group_id: groupId.value,
  })
const dirty = computed(() => ready.value && (logicBlocked.value || snapshot() !== saved.value))
const boundLength = computed(() =>
  document.value.logic?.bindings.some((binding) => binding.target === 'label'),
)
const selectedBindings = computed(
  () =>
    document.value.logic?.bindings
      .filter((binding) => binding.target === selectedId.value)
      .map((binding) => binding.property) ?? [],
)
const canvasLength = computed(() =>
  document.value.auto_length || boundLength.value
    ? (preview.value?.length_mm ?? document.value.length_mm)
    : document.value.length_mm,
)
const canvasElements = computed(() =>
  document.value.elements
    .map((element) => {
      const resolved = preview.value?.resolved_elements.find((e) => e.id === element.id)
      const bound = (property: string) =>
        document.value.logic?.bindings.some(
          (binding) => binding.target === element.id && binding.property === property,
        )
      const geometryBound = ['x', 'y', 'width', 'height', 'rotation', 'stroke'].some(bound)
      return resolved
        ? {
            ...element,
            x:
              element.distance_holder?.axis === 'horizontal' || geometryBound
                ? resolved.x
                : element.x,
            y:
              element.distance_holder?.axis === 'vertical' || geometryBound
                ? resolved.y
                : element.y,
            width:
              element.auto_width || geometryBound || bound('auto_width')
                ? resolved.width
                : element.width,
            height: geometryBound ? resolved.height : element.height,
            stroke: bound('stroke') ? resolved.stroke : element.stroke,
            rotation: bound('rotation') ? resolved.rotation : element.rotation,
            visible: bound('visible') ? resolved.visible : element.visible,
          }
        : element
    })
    .filter((element) => element.visible !== false),
)
const scale = computed(() => (zoom.value / 100) * 8)
const distanceTargets = computed(() =>
  document.value.elements.filter((element) => {
    let candidate: Element | undefined = element
    const seen = new Set<string>()
    while (candidate) {
      if (candidate.id === selectedId.value || seen.has(candidate.id)) return false
      seen.add(candidate.id)
      const anchor: string | undefined = candidate.distance_holder?.element_id
      candidate = anchor ? document.value.elements.find((e) => e.id === anchor) : undefined
    }
    return true
  }),
)
function positionedElement(element: Element) {
  return canvasElements.value.find((e) => e.id === element.id) ?? element
}
function positionLocked(axis: 'x' | 'y') {
  return selected.value?.distance_holder?.axis === (axis === 'x' ? 'horizontal' : 'vertical')
}
function setPosition(axis: 'x' | 'y', event: Event) {
  if (!selected.value || positionLocked(axis)) return
  const geometry = elementGeometry(positionedElement(selected.value))
  geometry[axis] = Number((event.target as HTMLInputElement).value)
  setElementGeometry(selected.value, geometry)
}
function setDistanceTarget(event: Event) {
  if (!selected.value) return
  const target = (event.target as HTMLSelectElement).value
  const current = positionedElement(selected.value)
  selected.value.x = current.x
  selected.value.y = current.y
  selected.value.distance_holder = target
    ? {
        element_id: target,
        axis: selected.value.distance_holder?.axis ?? 'horizontal',
        gap_mm: selected.value.distance_holder?.gap_mm ?? 2,
      }
    : null
  record()
}
const selectedBounds = computed(() => {
  const e = canvasElements.value.find((item) => item.id === selectedId.value)
  if (!e) return null
  return elementGeometry(e)
})
watch(
  () => w.selectedPrinter,
  () => {
    const capabilities = w.destinationPrinter(w.selectedPrinter)?.capabilities
    if (!capabilities) return
    margin.value = capabilities.printable_margin_mm
    printableWidths.value = capabilities.printable_widths_mm ?? {}
    resolutionModes.value = capabilities.resolution_modes ?? {}
    defaultResolution.value = [capabilities.dpi_x, capabilities.dpi_y]
  },
)
let timer: ReturnType<typeof setTimeout> | undefined,
  serial = 0,
  loadGeneration = 0,
  stopped = false
const canvas = ref<SVGSVGElement | null>(null)
let drag: {
  mode: 'move' | 'size'
  pointerId: number
  x: number
  y: number
  element: Element
} | null = null
function record() {
  const state = snapshot()
  if (history.value[cursor.value] === state) return
  history.value = history.value.slice(0, cursor.value + 1)
  history.value.push(state)
  if (history.value.length > 100) history.value.shift()
  cursor.value = history.value.length - 1
}
function changeFont() {
  if (selected.value) selected.value.font_weight = null
  record()
}
function changeWeight(value: number) {
  if (selected.value) selected.value.font_weight = value
  record()
}
function restore(offset: number) {
  const position = cursor.value + offset
  if (position < 0 || position >= history.value.length) return
  cursor.value = position
  const value = JSON.parse(history.value[position]) as {
    name: string
    document: TemplateDocument
    scope: 'personal' | 'group' | 'global'
    group_id: string | null
  }
  name.value = value.name
  document.value = value.document
  scope.value = value.scope
  groupId.value = value.group_id
}
async function load() {
  const ticket = ++loadGeneration,
    actor = auth.user?.id,
    identifier = route.params.id
  const current = () =>
    !stopped &&
    ticket === loadGeneration &&
    auth.user?.id === actor &&
    route.params.id === identifier
  ready.value = false
  error.value = ''
  if (!w.profiles.length) return
  try {
    const groups = await resources.get<{ id: string; name: string }[]>('/user-groups')
    if (!current()) return
    userGroups.value = [...groups]
    const capabilities = w.destinationPrinter(w.selectedPrinter)?.capabilities
    margin.value = capabilities?.printable_margin_mm ?? 1
    printableWidths.value = capabilities?.printable_widths_mm ?? {}
    resolutionModes.value = capabilities?.resolution_modes ?? {}
    defaultResolution.value = [capabilities?.dpi_x ?? 180, capabilities?.dpi_y ?? 180]
    if (route.params.id) {
      const template = await resources.get<Template>(`/templates/${identifier}`)
      if (!current()) return
      id.value = template.id
      revision.value = template.revision
      name.value = template.name
      ownerId.value = template.owner_id ?? null
      scope.value = template.scope ?? 'global'
      groupId.value = template.group_id ?? null
      originalSharing.value = { scope: scope.value, group_id: groupId.value }
      if (groupId.value && !userGroups.value.some((g) => g.id === groupId.value))
        userGroups.value.push({ id: groupId.value, name: t('uiMessages.currentTemplateGroup') })
      editable.value =
        template.can_edit ?? (!!auth.user?.is_admin || template.owner_id === auth.user?.id)
      document.value = { print_resolution: 'printer', ...structuredClone(template.document) }
    } else {
      id.value = null
      revision.value = 0
      name.value = t('uiMessages.untitledLabel')
      ownerId.value = auth.user?.id ?? null
      scope.value = auth.can('templates.create_personal')
        ? 'personal'
        : auth.can('templates.create_global')
          ? 'global'
          : 'group'
      groupId.value = scope.value === 'group' ? (availableGroups.value[0]?.id ?? null) : null
      originalSharing.value = { scope: scope.value, group_id: groupId.value }
      editable.value = auth.canCreateTemplates
      document.value = newDocument()
    }
    if (!document.value.preview_tape) {
      const profile =
        (!id.value &&
          (w.profiles.find((p) => p.id === route.query.profile && p.available !== false) ||
            w.defaultProfile)) ||
        w.profiles.find(
          (p) => p.available !== false && compatibleProfile(p, undefined, document.value),
        )
      if (profile) sampleProfile.value = profile.id
    }
    saved.value = snapshot()
    history.value = [snapshot()]
    cursor.value = 0
    selectedId.value =
      typeof route.query.element === 'string' &&
      document.value.elements.some((e) => e.id === route.query.element)
        ? route.query.element
        : ''
    ready.value = true
    previewExampleId.value = ''
    clearTimeout(timer)
    await updatePreview()
  } catch (e) {
    if (current()) error.value = errorMessage(e)
  }
}
async function updatePreview() {
  if (!w.profiles.length) return
  const ticket = ++serial
  rendering.value = true
  try {
    const result = await resources.preview<Preview>(
      {
        destination_id: w.selectedPrinter || undefined,
        document: { ...document.value, logic_editor: undefined },
        use_samples: true,
        data: previewData.value,
      },
      w.destinationPrinter(w.selectedPrinter)?.capabilities,
    )
    if (ticket !== serial || stopped) return
    await decodeLabel(result)
    if (ticket === serial && !stopped) {
      preview.value = result
      error.value = ''
    }
  } catch (e) {
    if (ticket === serial && !stopped) {
      error.value = errorMessage(e)
      preview.value = null
    }
  } finally {
    if (ticket === serial) rendering.value = false
  }
}
watch(
  [document, previewData, sampleProfile, () => w.selectedPrinter],
  () => {
    serial++
    clearTimeout(timer)
    rendering.value = true
    timer = setTimeout(updatePreview, 300)
  },
  { deep: true },
)
watch(
  () => route.params.id,
  (identifier) => {
    if (identifier !== id.value) void load()
  },
)
watch([selectedId, sampleProfile], () => {
  if (ready.value && route.path.startsWith('/templates/'))
    void router.replace({
      query: {
        ...route.query,
        element: selectedId.value || undefined,
        profile: sampleProfile.value || undefined,
      },
    })
})
watch(
  () => route.query,
  (query) => {
    selectedId.value = typeof query.element === 'string' ? query.element : ''
  },
)
function add(kind: Element['kind'], vertical = false) {
  const element = newElement(kind)
  if (document.value.version === 2) element.logic_name = nextElementName(document.value, kind)
  element.x = margin.value
  element.y = verticalMargin.value
  element.width = Math.min(element.width, document.value.length_mm - 2 * margin.value)
  element.height = Math.min(element.height, printableBand.value.height)
  if (kind === 'qr') element.width = element.height
  if (kind === 'line' && vertical) {
    element.rotation = 90
    setElementGeometry(element, {
      x: margin.value,
      y: verticalMargin.value,
      width: element.stroke,
      height: Math.min(30, printableBand.value.height),
    })
  }
  document.value.elements.push(element)
  selectedId.value = element.id
  activeInspector.value = ['text', 'qr', 'barcode', 'datamatrix', 'aztec', 'image'].includes(kind)
    ? 'content'
    : 'style'
  record()
}
function remove() {
  for (const element of document.value.elements) {
    if (element.distance_holder?.element_id === selectedId.value) {
      const current = positionedElement(element)
      element.x = current.x
      element.y = current.y
      element.distance_holder = null
    }
  }
  document.value.elements = document.value.elements.filter((e) => e.id !== selectedId.value)
  if (document.value.logic)
    document.value.logic.bindings = document.value.logic.bindings.filter(
      (binding) => binding.target !== selectedId.value,
    )
  selectedId.value = ''
  record()
}
function duplicate() {
  if (selected.value) {
    const e = structuredClone({ ...selected.value })
    e.id = randomUUID()
    if (document.value.version === 2) e.logic_name = nextElementName(document.value, e.kind)
    if (document.value.logic) {
      const bindings = document.value.logic.bindings.filter(
        (binding) => binding.target === selected.value?.id,
      )
      document.value.logic.bindings.push(
        ...bindings.map((binding) => ({
          ...binding,
          target: e.id,
          expression: copyExpression(binding.expression),
        })),
      )
    }
    document.value.elements.push(e)
    selectedId.value = e.id
    record()
  }
}
function order(direction: number) {
  const elements = document.value.elements,
    index = elements.findIndex((e) => e.id === selectedId.value)
  if (index + direction < 0 || index + direction >= elements.length) return
  const [element] = elements.splice(index, 1)
  elements.splice(index + direction, 0, element)
  record()
}
function align(axis: 'left' | 'center' | 'right' | 'middle') {
  if (!selected.value) return
  const e = selected.value
  const geometry = elementGeometry(positionedElement(e))
  if (axis === 'middle' && !positionLocked('y'))
    geometry.y = (document.value.width_mm - geometry.height) / 2
  else if (axis !== 'middle' && !positionLocked('x'))
    geometry.x =
      axis === 'left'
        ? margin.value
        : axis === 'right'
          ? canvasLength.value - margin.value - geometry.width
          : (canvasLength.value - geometry.width) / 2
  setElementGeometry(e, geometry)
  record()
}
function point(event: PointerEvent) {
  const box = canvas.value!.getBoundingClientRect()
  return { x: (event.clientX - box.left) / scale.value, y: (event.clientY - box.top) / scale.value }
}
function start(event: PointerEvent, element: Element, mode: 'move' | 'size') {
  if (drag || !event.isPrimary || event.button !== 0) return
  event.preventDefault()
  selectedId.value = element.id
  if (element.kind === 'line') {
    element = { ...element }
    setElementGeometry(element, elementGeometry(element))
    setElementGeometry(selected.value!, elementGeometry(element))
  }
  drag = { mode, pointerId: event.pointerId, ...point(event), element: { ...element } }
  canvas.value?.setPointerCapture(event.pointerId)
}
function move(event: PointerEvent) {
  if (drag && event.pointerId !== drag.pointerId) return
  const p = point(event)
  pointer.value =
    p.x >= 0 && p.x <= canvasLength.value && p.y >= 0 && p.y <= document.value.width_mm ? p : null
  if (!drag || !selected.value || selected.value.id !== drag.element.id) return
  const dx = p.x - drag.x,
    dy = p.y - drag.y
  const round = (value: number) =>
    Math.round(value * (snap.value ? 2 : 100)) / (snap.value ? 2 : 100)
  if (drag.mode === 'move') {
    const geometry = elementGeometry(drag.element)
    if (!positionLocked('x')) geometry.x = Math.max(0, round(geometry.x + dx))
    if (!positionLocked('y')) geometry.y = Math.max(0, round(geometry.y + dy))
    setElementGeometry(selected.value, geometry)
  } else {
    const angle = (drag.element.rotation * Math.PI) / 180
    const cos = Math.round(Math.cos(angle)),
      sin = Math.round(Math.sin(angle))
    const localX = cos * dx + sin * dy
    const localY = -sin * dx + cos * dy
    selected.value.auto_width = false
    if (selected.value.kind === 'line') selected.value.height = selected.value.stroke
    selected.value.width = Math.max(1, round(drag.element.width + localX))
    if (selected.value.kind === 'image' && boxAspectLocked(selected.value)) {
      const ratio = drag.element.width / drag.element.height
      // Snap the actively dragged dimension; derive the other without rounding.
      if (Math.abs(localY / drag.element.height) > Math.abs(localX / drag.element.width)) {
        selected.value.height = Math.max(1, round(drag.element.height + localY))
        selected.value.width = selected.value.height * ratio
      } else {
        selected.value.height = selected.value.width / ratio
      }
    } else
      selected.value.height =
        selected.value.kind === 'line'
          ? selected.value.stroke
          : selected.value.kind === 'qr'
            ? selected.value.width
            : Math.max(1, round(drag.element.height + localY))
    const dw = selected.value.width - drag.element.width
    const dh = selected.value.height - drag.element.height
    // Keep the opposite rotated corner fixed while resizing around the moving center.
    if (!positionLocked('x'))
      selected.value.x = Math.max(-1000, drag.element.x + ((cos - 1) * dw - sin * dh) / 2)
    if (!positionLocked('y'))
      selected.value.y = Math.max(-100, drag.element.y + (sin * dw + (cos - 1) * dh) / 2)
  }
}
function finish(event?: PointerEvent) {
  if (!drag || (event && event.pointerId !== drag.pointerId)) return
  const pointerId = drag.pointerId
  drag = null
  if (canvas.value?.hasPointerCapture(pointerId)) canvas.value.releasePointerCapture(pointerId)
  record()
}
function interruptDrag() {
  finish()
  pointer.value = null
}
function changeAutomaticLength() {
  if (document.value.auto_length && document.value.logic)
    document.value.logic.bindings = document.value.logic.bindings.filter(
      (binding) => binding.target !== 'label',
    )
  record()
}
function changeAutomaticWidth() {
  if (selected.value?.auto_width && document.value.logic)
    document.value.logic.bindings = document.value.logic.bindings.filter(
      (binding) =>
        !(
          binding.target === selected.value?.id &&
          binding.property === automaticDimension(selected.value!)
        ),
    )
  record()
}
function setManualLength(event: Event) {
  if (!document.value.auto_length)
    document.value.length_mm = Number((event.target as HTMLInputElement).value)
}
function setClipping(event: Event) {
  document.value.out_of_bounds = (event.target as HTMLInputElement).checked ? 'clip' : 'error'
  record()
}
function setQrMargin(event: Event) {
  if (!selected.value) return
  const value = (event.target as HTMLInputElement).value
  selected.value.qr_margin_mm = value === '' ? null : Number(value)
  record()
}
function setVerticalAlign(event: Event) {
  if (!selected.value) return
  selected.value.vertical_align = (event.target as HTMLSelectElement).value as
    'top' | 'center' | 'bottom'
  record()
}
function setPadding(side: (typeof paddingSides)[number], event: Event) {
  if (!selected.value) return
  selected.value[`padding_${side}`] = Number((event.target as HTMLInputElement).value)
  record()
}
function setTextSpacing(key: 'character_spacing' | 'line_spacing', event: Event) {
  if (!selected.value) return
  selected.value[key] = Number((event.target as HTMLInputElement).value)
  record()
}
function chooseImageFile(event: Event) {
  imageFile.value = (event.target as HTMLInputElement).files?.[0] ?? null
}
async function uploadImage() {
  const file = imageFile.value,
    target = selected.value
  if (!file || target?.kind !== 'image') return
  if (file.size > 5_000_000) {
    w.actionError = t('uiMessages.uploadAnImageOfAtMost5MB')
    return
  }
  let asset: ImageAsset | undefined
  const ok = await w.action(async () => {
    asset = await api<ImageAsset>(
      `/image-assets?name=${encodeURIComponent(file.name)}`,
      'POST',
      file,
    )
    if (asset.archived) asset = await api<ImageAsset>(`/image-assets/${asset.id}/restore`, 'POST')
  }, t('uiMessages.imageUploadedAndAddedToTheTemplate'))
  if (ok && asset && document.value.elements.includes(target)) {
    target.image_asset = asset.id
    selectedId.value = target.id
    record()
    imageFile.value = null
    if (imageInput.value) imageInput.value.value = ''
  }
}
function imageRatio(element: Element): number | undefined {
  const bound = document.value.logic?.bindings.some(
    (binding) => binding.target === element.id && binding.property === 'image_asset',
  )
  const identifier = bound
    ? preview.value?.resolved_elements.find((item) => item.id === element.id)?.image_asset
    : element.image_asset
  const asset = w.images.find((asset) => asset.id === identifier)
  return asset ? asset.width / asset.height : undefined
}
const imageBoxMismatch = computed(() => {
  const element = selected.value
  if (!element || element.kind !== 'image') return false
  const ratio = imageRatio(element)
  const box = positionedElement(element)
  return ratio !== undefined && Math.abs(box.width / box.height - ratio) > ratio * 0.000001
})
function boxAspectLocked(element: Element) {
  return element.lock_aspect ?? element.preserve_aspect ?? true
}
function setBoxAspectLock(event: Event) {
  if (!selected.value) return
  selected.value.lock_aspect = (event.target as HTMLInputElement).checked
  record()
}
function fitImageBox() {
  const element = selected.value
  if (!element || element.kind !== 'image') return
  const ratio = imageRatio(element)
  if (ratio) {
    const current = positionedElement(element)
    const before = elementGeometry(current)
    // Fit within the existing box without enlarging the label.
    element.width = Math.min(current.width, current.height * ratio)
    element.height = element.width / ratio
    setElementGeometry(element, { ...elementGeometry(element), x: before.x, y: before.y })
  }
  record()
  widthInput.value?.focus()
}
function setPreserveAspect(event: Event) {
  if (!selected.value) return
  // Old documents shared this setting. Freeze their resize preference before
  // changing artwork fitting so the two controls remain independent.
  selected.value.lock_aspect = boxAspectLocked(selected.value)
  selected.value.preserve_aspect = (event.target as HTMLInputElement).checked
  record()
}
function setImageScale(event: Event) {
  const value = Number((event.target as HTMLInputElement).value)
  if (selected.value && Number.isFinite(value) && value >= 0.1 && value <= 1)
    selected.value.image_scale = value
}
function resize(axis: 'width' | 'height', event: Event) {
  const element = selected.value
  if (!element) return
  const value = Number((event.target as HTMLInputElement).value)
  if (!Number.isFinite(value) || value <= 0) return
  const geometry = elementGeometry(positionedElement(element))
  const ratio = geometry.width / geometry.height
  geometry[axis] = value
  if (element.kind === 'qr') geometry.height = geometry.width
  if (element.kind === 'image' && boxAspectLocked(element)) {
    if (axis === 'width') geometry.height = geometry.width / ratio
    else geometry.width = geometry.height * ratio
  }
  setElementGeometry(element, geometry)
}
function rotateElement(event: Event) {
  const element = selected.value
  if (!element) return
  const previous = elementGeometry(positionedElement(element))
  element.rotation = Number((event.target as HTMLSelectElement).value) as Element['rotation']
  const rotated = elementGeometry(element)
  setElementGeometry(element, { ...rotated, x: previous.x, y: previous.y })
  changeAutomaticWidth()
}
function setStroke(event: Event) {
  const element = selected.value
  if (!element) return
  const geometry = elementGeometry(positionedElement(element))
  element.stroke = Number((event.target as HTMLInputElement).value)
  if (element.kind === 'line') {
    geometry[element.rotation % 180 ? 'width' : 'height'] = element.stroke
    setElementGeometry(element, geometry)
  }
}
function key(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
    event.preventDefault()
    restore(event.shiftKey ? 1 : -1)
    return
  }
  if (!selected.value) return
  if (event.key === 'Delete' || event.key === 'Backspace') {
    event.preventDefault()
    remove()
  }
  const delta = event.shiftKey ? 1 : 0.5
  if (event.key.startsWith('Arrow')) {
    event.preventDefault()
    if (event.key === 'ArrowLeft' && !positionLocked('x'))
      selected.value.x = Math.max(-1000, selected.value.x - delta)
    if (event.key === 'ArrowRight' && !positionLocked('x')) selected.value.x += delta
    if (event.key === 'ArrowUp' && !positionLocked('y'))
      selected.value.y = Math.max(-100, selected.value.y - delta)
    if (event.key === 'ArrowDown' && !positionLocked('y')) selected.value.y += delta
    record()
  }
}
async function save() {
  if (!editable.value || !selectedProfile.value || (scope.value === 'group' && !groupId.value))
    return
  const submitted = snapshot()
  let result: Template | undefined
  const ok = await w.action(async () => {
    result = await api<Template>(
      `/templates${id.value ? `/${id.value}` : ''}`,
      id.value ? 'PUT' : 'POST',
      {
        name: name.value,
        scope: scope.value,
        group_id: scope.value === 'group' ? groupId.value : null,
        destination_id: w.selectedPrinter || undefined,
        document: document.value,
        expected_revision: id.value ? revision.value : null,
      },
    )
  }, t('uiMessages.templateRevisionSavedExistingQueuedLabelsKeepTheirOriginalLayout'))
  if (ok && result) {
    saved.value = submitted
    revision.value = result.revision
    id.value = result.id
    ownerId.value = result.owner_id ?? null
    originalSharing.value = {
      scope: result.scope ?? scope.value,
      group_id: result.group_id ?? null,
    }
    if (!dirty.value)
      await router.replace({ path: `/templates/${result.id}/edit`, query: route.query })
  }
}
function changeFieldName(field: TemplateField, event: Event) {
  const input = event.target as HTMLInputElement
  try {
    renameField(document.value, field, input.value)
    record()
  } catch (error) {
    w.actionError = errorMessage(error)
    input.value = field.name
  }
}
function changeFieldType(field: TemplateField, event: Event) {
  const select = event.target as HTMLSelectElement
  try {
    setFieldType(document.value, field, select.value as ValueType)
    record()
  } catch (error) {
    w.actionError = errorMessage(error)
    select.value = field.type ?? 'text'
  }
}
function changeLimit(
  field: TemplateField,
  key: 'minimum' | 'maximum' | 'min_length' | 'max_length',
  event: Event,
) {
  const value = (event.target as HTMLInputElement).valueAsNumber
  field[key] = Number.isFinite(value) ? value : null
  record()
}
function removeField(index: number) {
  const name = document.value.fields[index]!.name
  let referenced = false
  visitReferences(document.value, (reference) => {
    if (reference.name === name) referenced = true
  })
  if (referenced) {
    w.actionError = t('uiMessages.removeReferencesToThisVariableFromLogicBeforeDeletingIt')
    return
  }
  document.value.fields.splice(index, 1)
  for (const example of document.value.preview_examples ?? []) delete example.data[name]
  record()
}
function addField() {
  let index = document.value.fields.length + 1
  while (
    document.value.fields.some((f) => f.name === `field${index}`) ||
    Object.hasOwn(document.value.logic?.variables ?? {}, `field${index}`) ||
    document.value.elements.some((e) => e.logic_name === `field${index}`)
  )
    index++
  document.value.fields.push({
    name: `field${index}`,
    label: t('uiDetails.field', { value1: String(index) }),
    required: true,
    default: '',
    sample: t('templatePreviewInputs.example'),
    ...(document.value.version === 2 ? { type: 'text' as const } : {}),
  })
  record()
}
function beforeUnload(event: BeforeUnloadEvent) {
  if (dirty.value) {
    event.preventDefault()
    event.returnValue = ''
  }
}
onBeforeRouteLeave(
  () => !dirty.value || confirmAction(t('uiMessages.discardUnsavedTemplateChanges')),
)
onMounted(() => {
  void load()
  window.addEventListener('beforeunload', beforeUnload)
  window.addEventListener('blur', interruptDrag)
})
onUnmounted(() => {
  interruptDrag()
  stopped = true
  loadGeneration++
  serial++
  clearTimeout(timer)
  window.removeEventListener('beforeunload', beforeUnload)
  window.removeEventListener('blur', interruptDrag)
})
</script>
<template>
  <div v-if="!w.profiles.length" class="panel empty">
    <h2>{{ $t('common.noTapeProfiles') }}</h2>
    <RouterLink v-if="auth.can('inventory.manage')" class="button primary" to="/profiles">{{
      $t('common.createTapeProfile')
    }}</RouterLink>
    <p v-else class="help">{{ $t('common.askAnAdministratorToCreateATapeProfile') }}</p>
  </div>
  <div v-if="w.profiles.length && !ready" class="panel empty">
    <template v-if="error"
      ><p class="alert danger" role="alert">{{ error }}</p>
      <button class="secondary" @click="load">{{ $t('common.retry') }}</button></template
    >
    <p v-else role="status">{{ $t('templateEditor.loadingTemplate') }}</p>
  </div>
  <div v-if="ready && w.profiles.length && !editable" class="alert warning">
    {{
      id
        ? $t('uiMessages.thisTemplateIsReadOnly')
        : $t('uiMessages.youDoNotHavePermissionToCreateTemplates')
    }}
  </div>
  <section v-if="ready && w.profiles.length" class="panel editor-toolbar">
    <div class="editor-settings-fields">
      <label
        >{{ $t('common.templateName')
        }}<input v-model="name" maxlength="100" required @change="record"
      /></label>
      <div class="setting-field resolution-choice">
        <SettingHelp
          :help="editorHelp.resolution"
          for="setting-resolution"
          :label="$t('templateEditor.printResolution')"
        /><select id="setting-resolution" v-model="document.print_resolution" @change="record">
          <option value="printer">
            {{ $t('templateEditor.printerDefault') }}{{ defaultResolution[1] }} ×
            {{ defaultResolution[0] }} {{ $t('common.dpi2') }}
          </option>
          <option v-for="(dpi, mode) in resolutionModes" :key="mode" :value="mode">
            {{ mode === 'high' ? $t('companionApp.high') : $t('companionApp.normal') }} ·
            {{ dpi[1] }} × {{ dpi[0] }} {{ $t('common.dpi') }}
          </option>
        </select>
      </div>
      <div class="setting-field">
        <TapeProfilePicker
          control-id="setting-profile"
          v-model="sampleProfile"
          :profiles="w.profiles"
          :saved-name="document.preview_tape?.name"
          :disabled="!editable"
          compact
        >
          <template #label
            ><SettingHelp
              :help="editorHelp.profile"
              for="setting-profile"
              :label="$t('common.tapeProfile')"
          /></template>
        </TapeProfilePicker>
      </div>
      <div class="setting-field">
        <SettingHelp
          :help="editorHelp.length"
          for="setting-length"
          :label="$t('templateEditor.labelLengthMm')"
        /><input
          id="setting-length"
          :value="document.auto_length || boundLength ? canvasLength : document.length_mm"
          @input="setManualLength"
          :disabled="
            !editable ||
            document.auto_length ||
            boundLength ||
            document.media?.media_family === 'fixed_label'
          "
          type="number"
          min="10"
          max="300"
          @change="record"
        />
      </div>
    </div>
    <div class="template-sharing field-row">
      <div v-if="w.destinations.length > 1" class="setting-field">
        <SettingHelp
          :help="editorHelp.destination"
          for="setting-destination"
          :label="$t('templateEditor.designDestination')"
        /><select id="setting-destination" v-model="w.selectedPrinter">
          <option v-for="printer in w.destinations" :key="printer.id" :value="printer.id">
            {{ printer.name }}
          </option>
        </select>
      </div>
      <div class="setting-field">
        <SettingHelp
          :help="editorHelp.visibility"
          for="setting-visibility"
          :label="$t('common.templateVisibility')"
        /><select
          id="setting-visibility"
          v-model="scope"
          :disabled="!editable || !canChangeSharing"
          @change="record"
        >
          <option
            v-if="
              auth.can('templates.create_personal') || (id && originalSharing.scope === 'personal')
            "
            value="personal"
          >
            {{ $t('common.personal') }}
          </option>
          <option v-if="availableGroups.length" value="group">{{ $t('common.userGroup') }}</option>
          <option
            v-if="auth.can('templates.create_global') || (id && originalSharing.scope === 'global')"
            value="global"
          >
            {{ $t('common.global') }}
          </option>
        </select>
      </div>
      <label v-if="scope === 'group'"
        >{{ $t('common.userGroup')
        }}<select
          v-model="groupId"
          :disabled="!editable || !canChangeSharing"
          required
          @change="record"
        >
          <option :value="null" disabled>{{ $t('templateEditor.chooseAGroup') }}</option>
          <option v-for="group in availableGroups" :key="group.id" :value="group.id">
            {{ group.name }}
          </option>
        </select></label
      >
    </div>
    <p
      v-if="
        id &&
        scope !== 'personal' &&
        (scope !== originalSharing.scope ||
          (scope === 'group' && groupId !== originalSharing.group_id))
      "
      class="help template-history-sharing"
    >
      {{ $t('common.sharingIncludesAllSavedRevisions') }}
    </p>
    <div class="editor-settings-footer">
      <div class="editor-settings-toggles">
        <div class="setting-toggle">
          <label class="checkbox"
            ><input
              v-model="document.auto_length"
              :disabled="document.media?.media_family === 'fixed_label'"
              type="checkbox"
              @change="changeAutomaticLength"
            /><span>{{ $t('templateEditor.automaticLabelLength') }}</span></label
          ><SettingHelp :help="editorHelp.autoLength" />
        </div>
        <div class="setting-toggle">
          <label class="checkbox"
            ><input
              :checked="document.out_of_bounds === 'clip'"
              type="checkbox"
              @change="setClipping"
            /><span>{{ $t('templateEditor.ignoreOutOfBoundsObjects') }}</span></label
          ><SettingHelp :help="editorHelp.clipping" />
        </div>
      </div>
      <div class="editor-settings-actions">
        <button v-if="id" type="button" :disabled="w.busy" @click="showRevisionHistory">
          {{ $t('common.history') }}
        </button>
        <button :disabled="cursor === 0" @click="restore(-1)">{{ $t('common.undo') }}</button
        ><button :disabled="cursor >= history.length - 1" @click="restore(1)">
          {{ $t('templateEditor.redo') }}
        </button>
        <button
          class="primary"
          :disabled="
            w.busy ||
            logicBlocked ||
            !ready ||
            rendering ||
            !!error ||
            !name.trim() ||
            !editable ||
            !selectedProfile ||
            (scope === 'group' && !groupId)
          "
          @click="save"
        >
          {{ $t('common.saveTemplate') }}
        </button>
        <span class="help">{{
          dirty
            ? $t('uiMessages.unsavedChanges')
            : revision
              ? $t('uiDetails.revision', { value1: String(revision) })
              : $t('uiMessages.newDocument')
        }}</span>
      </div>
    </div>
  </section>
  <TemplatePreviewInputs
    v-if="ready && w.profiles.length"
    v-model="previewExampleId"
    :document="document"
    :disabled="!editable"
    @change="record"
  />
  <div
    v-if="ready && w.profiles.length"
    class="editor-layout"
    :class="{ 'no-selection': !selected }"
  >
    <section class="panel editor-workspace">
      <div class="editor-tools">
        <div class="editor-add-buttons" role="group" :aria-label="$t('templateEditor.addElements')">
          <button :aria-label="$t('templateEditor.addImage')" @click="add('image')">
            <PhotoIcon />{{ $t('templateEditor.image') }}
          </button>
          <button :aria-label="$t('templateEditor.addText')" @click="add('text')">
            <LanguageIcon />{{ $t('common.text') }}
          </button>
          <button :aria-label="$t('templateEditor.addQrCode')" @click="add('qr')">
            <QrCodeIcon />{{ $t('templateEditor.qrCode') }}
          </button>
          <button :aria-label="$t('templateEditor.addBarcode')" @click="add('barcode')">
            <ViewColumnsIcon />{{ $t('templateEditor.barcode') }}
          </button>
          <button :aria-label="$t('templateEditor.addDataMatrix')" @click="add('datamatrix')">
            <Squares2X2Icon />{{ $t('templateEditor.dataMatrix') }}
          </button>
          <button :aria-label="$t('templateEditor.addAztecCode')" @click="add('aztec')">
            <QrCodeIcon />{{ $t('templateEditor.aztec') }}
          </button>
          <button :aria-label="$t('templateEditor.addRectangle')" @click="add('rectangle')">
            <StopIcon />{{ $t('templateEditor.rectangle') }}
          </button>
          <button :aria-label="$t('templateEditor.addHorizontalLine')" @click="add('line')">
            <MinusIcon />{{ $t('templateEditor.horizontalLine') }}
          </button>
          <button :aria-label="$t('templateEditor.addVerticalLine')" @click="add('line', true)">
            <MinusIcon style="transform: rotate(90deg)" />{{ $t('common.verticalLine') }}
          </button>
        </div>
      </div>
      <div class="editor-options">
        <div class="setting-toggle">
          <label class="checkbox"
            ><input v-model="showPrintPixels" type="checkbox" />{{
              $t('common.showPrintPixels')
            }}</label
          ><SettingHelp :help="editorHelp.pixels" />
        </div>
        <div class="setting-toggle">
          <label class="checkbox"
            ><input v-model="snap" type="checkbox" />{{ $t('common.snap05Mm') }}</label
          ><SettingHelp :help="editorHelp.snap" />
        </div>
        <div class="setting-toggle">
          <label class="checkbox"
            ><input v-model="showBounds" type="checkbox" />{{
              $t('templateEditor.objectBoundaries')
            }}</label
          ><SettingHelp :help="editorHelp.bounds" />
        </div>
        <label class="editor-zoom"
          >{{ $t('common.zoom') }}
          <input
            :aria-label="$t('common.zoom')"
            v-model.number="zoom"
            type="range"
            min="50"
            max="250"
            step="10"
          />
          <output>{{ zoom }}%</output>
        </label>
      </div>
      <p
        v-if="document.fields.length || document.preview_examples?.length"
        class="canvas-example-name"
        role="status"
        :aria-label="$t('templateEditor.canvasExample')"
      >
        {{ previewExample?.name ?? $t('templatePreviewInputs.sampleValues') }}
      </p>
      <div
        class="canvas-example-navigation"
        :class="{ 'has-examples': document.preview_examples?.length }"
      >
        <button
          v-if="document.preview_examples?.length"
          type="button"
          class="secondary canvas-example-arrow"
          :aria-label="$t('templateEditor.previousCanvasExample')"
          @click="browseCanvasExample(-1)"
        >
          <ChevronLeftIcon aria-hidden="true" />
        </button>
        <div class="editor-canvas-scroll">
          <div class="editor-board">
            <div class="ruler-corner">{{ $t('common.mm') }}</div>
            <EditorRuler
              :selection-key="selectedId"
              :length="canvasLength"
              :scale="scale"
              :position="pointer?.x ?? null"
              :selection="
                selectedBounds
                  ? { start: selectedBounds.x, end: selectedBounds.x + selectedBounds.width }
                  : null
              "
            />
            <EditorRuler
              :selection-key="selectedId"
              vertical
              :length="document.width_mm"
              :scale="scale"
              :position="pointer?.y ?? null"
              :selection="
                selectedBounds
                  ? { start: selectedBounds.y, end: selectedBounds.y + selectedBounds.height }
                  : null
              "
            />
            <svg
              ref="canvas"
              class="editor-canvas"
              tabindex="0"
              role="img"
              :aria-label="$t('templateEditor.labelDesignCanvas')"
              :width="canvasLength * scale"
              :height="document.width_mm * scale"
              :viewBox="`0 0 ${canvasLength} ${document.width_mm}`"
              @pointermove="move"
              @pointerup="finish"
              @pointercancel="finish"
              @lostpointercapture="finish"
              @pointerleave="pointer = null"
              @keydown="key"
            >
              <defs>
                <pattern id="editor-grid" width="1" height="1" patternUnits="userSpaceOnUse">
                  <path d="M1 0H0V1" fill="none" stroke="#818cf8" stroke-width="0.03" />
                </pattern>
              </defs>
              <rect
                width="100%"
                height="100%"
                fill="white"
                @pointerdown="!drag && $event.isPrimary && $event.button === 0 && (selectedId = '')"
              />
              <image
                v-if="preview"
                :href="showPrintPixels ? preview.png : preview.design_png"
                width="100%"
                height="100%"
                preserveAspectRatio="none"
                style="pointer-events: none"
                :style="{ imageRendering: showPrintPixels ? 'pixelated' : 'auto' }"
              />
              <rect
                width="100%"
                height="100%"
                fill="url(#editor-grid)"
                style="pointer-events: none"
              />
              <rect
                class="printable-border"
                :x="margin"
                :y="verticalMargin"
                :width="canvasLength - margin * 2"
                :height="printableBand.height"
                fill="none"
                :stroke="printableBorder"
                stroke-width="1.25"
                stroke-dasharray="5 5"
                vector-effect="non-scaling-stroke"
                style="pointer-events: none"
              />
              <g
                v-for="element in canvasElements"
                :key="element.id"
                :transform="`rotate(${element.rotation},${element.x + element.width / 2},${element.y + element.height / 2})`"
              >
                <line
                  v-if="element.kind === 'line'"
                  :x1="element.x"
                  :x2="element.x + element.width"
                  :y1="element.y + element.height / 2"
                  :y2="element.y + element.height / 2"
                  stroke="transparent"
                  :stroke-width="Math.max(element.stroke, 12 / scale)"
                  @pointerdown.stop="start($event, element, 'move')"
                />
                <rect
                  :x="element.x"
                  :y="
                    element.y +
                    (element.kind === 'line' ? (element.height - element.stroke) / 2 : 0)
                  "
                  :width="element.width"
                  :height="element.kind === 'line' ? element.stroke : element.height"
                  :fill="selectedId === element.id ? '#6366f11a' : 'transparent'"
                  class="object-boundary"
                  :class="{ selected: selectedId === element.id }"
                  :stroke="
                    selectedId === element.id ? '#6366f1' : showBounds ? '#64748b' : 'transparent'
                  "
                  :stroke-width="selectedId === element.id ? 1.5 : 0.75"
                  :stroke-dasharray="selectedId === element.id ? undefined : '4 3'"
                  vector-effect="non-scaling-stroke"
                  @pointerdown.stop="start($event, element, 'move')"
                />
                <circle
                  v-if="selectedId === element.id"
                  :cx="element.x + element.width"
                  :cy="element.y + (element.kind === 'line' ? element.height / 2 : element.height)"
                  r="0.6"
                  fill="#6366f1"
                  :style="{
                    cursor:
                      element.kind === 'line'
                        ? element.rotation % 180
                          ? 'ns-resize'
                          : 'ew-resize'
                        : element.rotation % 180
                          ? 'nesw-resize'
                          : 'nwse-resize',
                  }"
                  @pointerdown.stop="start($event, element, 'size')"
                />
              </g>
              <g v-if="pointer" class="canvas-cursor-guides" pointer-events="none">
                <line :x1="pointer.x" :x2="pointer.x" y1="0" :y2="document.width_mm" />
                <line x1="0" :x2="canvasLength" :y1="pointer.y" :y2="pointer.y" />
              </g>
            </svg>
          </div>
        </div>
        <button
          v-if="document.preview_examples?.length"
          type="button"
          class="secondary canvas-example-arrow"
          :aria-label="$t('templateEditor.nextCanvasExample')"
          @click="browseCanvasExample(1)"
        >
          <ChevronRightIcon aria-hidden="true" />
        </button>
      </div>
      <p v-if="pointer" class="help cursor-position">
        {{ $t('templateEditor.cursor') }} {{ pointer.x.toFixed(2) }} × {{ pointer.y.toFixed(2) }}
        {{ $t('common.mm') }}
      </p>
      <p class="help">
        {{ canvasLength }} × {{ document.width_mm }} {{ $t('common.mm2') }} {{ margin }}
        {{ $t('common.mmEnd') }} {{ printableBand.height.toFixed(2) }}
        {{ $t('common.mmPrintableWidth') }}
        {{
          rendering
            ? $t('newLabel.rendering')
            : showPrintPixels
              ? $t('uiMessages.deviceRasterPreview')
              : $t('uiMessages.smoothDesignPreview')
        }}
      </p>
      <p v-if="document.auto_length || document.out_of_bounds === 'clip'" class="help">
        <span v-if="document.auto_length">{{ $t('templateEditor.automaticLength10300Mm') }}</span>
        <span v-if="document.out_of_bounds === 'clip'">
          {{ $t('templateEditor.objectsOutsideTheGuidesAreClipped') }}
        </span>
      </p>
      <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
      <p v-for="warning in preview?.warnings ?? []" :key="warning" class="alert warning">
        {{ warning }}
      </p>
      <div v-if="document.elements.length" class="row wrap element-list">
        <button
          v-for="(element, index) in document.elements"
          :key="element.id"
          class="small"
          :aria-pressed="selectedId === element.id"
          @click="selectedId = element.id"
        >
          {{ index + 1 }}. {{ element.name?.trim() || element.kind }}
        </button>
      </div>
    </section>
    <section
      v-if="selected"
      ref="inspectorRoot"
      class="panel editor-properties"
      aria-labelledby="element-properties-heading"
    >
      <h2 id="element-properties-heading">
        {{ selected.name?.trim() || elementTitles[selected.kind] }}
      </h2>
      <p v-if="selectedBindings.length" class="help">
        {{ $t('templateEditor.controlledByLogic') }} {{ selectedBindings.join(', ') }}.
      </p>
      <MotionTrack
        class="inspector-tabs"
        :identity="`${selected.kind}:${activeInspector}`"
        selector="[aria-selected='true']"
        underline
        role="tablist"
        :aria-label="$t('templateEditor.elementSettings')"
      >
        <button
          v-for="tab in inspectorTabs"
          :key="tab.id"
          :id="`inspector-${tab.id}-tab`"
          type="button"
          role="tab"
          :aria-selected="activeInspector === tab.id"
          :aria-controls="`inspector-${tab.id}-panel`"
          :tabindex="activeInspector === tab.id ? 0 : -1"
          @click="activeInspector = tab.id"
          @keydown="moveInspectorTab"
        >
          {{ tab.label }}
        </button>
      </MotionTrack>
      <MotionSurface
        :order="['content', 'style', 'layout'].indexOf(activeInspector)"
        :identity="`${selected.id}:${activeInspector}`"
        class="editor-property-sections"
      >
        <div
          v-show="activeInspector === 'content'"
          id="inspector-content-panel"
          role="tabpanel"
          aria-labelledby="inspector-content-tab"
          :inert="activeInspector !== 'content'"
          class="inspector-panel"
        >
          <ElementDetails
            v-model:name="selected.name"
            @change="record"
            @duplicate="duplicate"
            @remove="remove"
          />
          <label v-if="['text', 'qr', 'barcode', 'datamatrix', 'aztec'].includes(selected.kind)"
            >{{ $t('templateEditor.content')
            }}<textarea
              :aria-label="$t('templateEditor.content')"
              v-model="selected.content"
              maxlength="2000"
              rows="3"
              @change="record"
            ></textarea
            ><span class="help"
              >{{ $t('common.use') }} <code v-pre>{{ name }}</code>
              {{ $t('common.forAVariable') }}</span
            ></label
          >
          <template v-if="selected.kind === 'barcode'">
            <div class="setting-field">
              <SettingHelp
                :help="editorHelp.barcode"
                for="setting-barcode"
                :label="$t('templateEditor.barcodeFormat')"
              /><select id="setting-barcode" v-model="selected.barcode_format" @change="record">
                <option value="code128">{{ $t('templateEditor.code128') }}</option>
                <option value="ean13">{{ $t('templateEditor.ean13') }}</option>
                <option value="ean8">{{ $t('templateEditor.ean8') }}</option>
                <option value="code39">{{ $t('templateEditor.code39') }}</option>
              </select>
            </div>
            <div class="setting-toggle">
              <label class="checkbox"
                ><input v-model="selected.barcode_caption" type="checkbox" @change="record" />{{
                  $t('common.showCaption')
                }}</label
              ><SettingHelp :help="editorHelp.caption" />
            </div>
            <ExpandableContent :open="!!selected.barcode_caption">
              <label
                >{{ $t('templateEditor.captionSizeMm')
                }}<input
                  v-model.number="selected.font_size"
                  type="number"
                  min="1"
                  max="24"
                  step="0.1"
                  @change="record"
              /></label>
            </ExpandableContent>
          </template>
          <template v-if="selected.kind === 'image'">
            <label
              >{{ $t('templateEditor.image')
              }}<select v-model="selected.image_asset" @change="record">
                <option :value="null" disabled>{{ $t('common.selectAnUploadedImage') }}</option>
                <option
                  v-if="preview?.missing_assets?.[selected.id] === 'image'"
                  :value="selected.image_asset"
                  disabled
                >
                  {{ $t('templateEditor.missingImageChooseAReplacement') }}
                </option>
                <option
                  v-for="asset in w.images.filter(
                    (a) => !a.archived || a.id === selected?.image_asset,
                  )"
                  :key="asset.id"
                  :value="asset.id"
                >
                  {{ asset.name }}{{ asset.archived ? ' (hidden)' : '' }}
                </option>
              </select></label
            >
            <label v-if="auth.can('images.create_personal')"
              >{{ $t('common.uploadImageFile')
              }}<input
                ref="imageInput"
                type="file"
                accept=".png,.jpg,.jpeg,.webp,.bmp,.gif,.svg"
                :disabled="w.busy"
                @change="chooseImageFile"
            /></label>
            <button
              v-if="auth.can('images.create_personal')"
              class="secondary"
              :disabled="!imageFile || w.busy"
              @click="uploadImage"
            >
              {{ $t('common.uploadAndUseImage') }}
            </button>
          </template>
        </div>
        <div
          v-show="activeInspector === 'style'"
          id="inspector-style-panel"
          role="tabpanel"
          aria-labelledby="inspector-style-tab"
          :inert="activeInspector !== 'style'"
          class="inspector-panel"
        >
          <ElementDetails
            v-if="inspectorTabs[0]?.id === 'style'"
            v-model:name="selected.name"
            @change="record"
            @duplicate="duplicate"
            @remove="remove"
          />
          <PropertySection
            v-if="selected.kind === 'text'"
            :title="$t('common.typography')"
            initially-open
          >
            <template v-if="selected.kind === 'text'">
              <div class="field-row typography-fonts">
                <label
                  >{{ $t('templateEditor.font')
                  }}<select v-model="selected.font" @change="changeFont">
                    <option>{{ $t('common.notoSans') }}</option>
                    <option
                      v-if="preview?.missing_assets?.[selected.id] === 'font'"
                      :value="selected.font"
                      disabled
                    >
                      {{ $t('templateEditor.missingFontChooseAReplacement') }}
                    </option>
                    <option
                      v-for="font in w.fonts.filter((f) => !f.archived || f.id === selected?.font)"
                      :key="font.id"
                      :value="font.id"
                    >
                      {{ font.family }} · {{ font.variable ? $t('uiMessages.variable') : font.style
                      }}{{ font.archived ? ' (hidden)' : '' }}
                    </option>
                  </select></label
                >
                <div class="setting-field">
                  <SettingHelp
                    :help="editorHelp.fontSize"
                    for="setting-fontSize"
                    :label="$t('templateEditor.fontSizeMm')"
                  /><input
                    id="setting-fontSize"
                    v-model.number="selected.font_size"
                    type="number"
                    min="1"
                    max="24"
                    step="0.1"
                    @change="record"
                  />
                </div>
              </div>

              <FontWeightControl
                :element="selected"
                :fonts="w.fonts"
                :disabled="selectedBindings.includes('bold')"
                @change="changeWeight" />
              <div class="row">
                <div class="setting-toggle">
                  <label class="checkbox"
                    ><input v-model="selected.wrap" type="checkbox" @change="record" />{{
                      $t('common.wrapText')
                    }}</label
                  ><SettingHelp :help="editorHelp.wrap" />
                </div></div
            ></template>
            <div class="field-row">
              <label
                >{{ $t('templateEditor.horizontalTextAlignment')
                }}<select v-model="selected.align" @change="record">
                  <option value="left">{{ $t('templateEditor.left') }}</option>
                  <option value="center">{{ $t('templateEditor.center') }}</option>
                  <option value="right">{{ $t('templateEditor.right') }}</option>
                </select></label
              >
              <label
                >{{ $t('common.verticalTextAlignment')
                }}<select :value="selected.vertical_align ?? 'top'" @change="setVerticalAlign">
                  <option value="top">{{ $t('common.top') }}</option>
                  <option value="center">{{ $t('templateEditor.center') }}</option>
                  <option value="bottom">{{ $t('templateEditor.bottom') }}</option>
                </select></label
              >
            </div>
          </PropertySection>
          <PropertySection v-if="selected.kind === 'text'" :title="$t('common.spacingPadding')">
            <fieldset class="text-padding">
              <legend>{{ $t('common.textSpacingMm') }}</legend>
              <div class="field-row">
                <div class="setting-field">
                  <SettingHelp
                    :help="editorHelp.characterSpacing"
                    for="setting-characterSpacing"
                    :label="$t('templateEditor.horizontal')"
                  /><input
                    id="setting-characterSpacing"
                    :aria-label="$t('templateEditor.horizontalCharacterSpacingMm')"
                    :value="selected.character_spacing ?? 0"
                    type="number"
                    min="0"
                    max="20"
                    step="0.1"
                    @input="setTextSpacing('character_spacing', $event)"
                  />
                </div>
                <div class="setting-field">
                  <SettingHelp
                    :help="editorHelp.lineSpacing"
                    for="setting-lineSpacing"
                    :label="$t('common.vertical')"
                  /><input
                    id="setting-lineSpacing"
                    :aria-label="$t('common.verticalLineSpacingMm')"
                    :value="selected.line_spacing ?? 0"
                    type="number"
                    min="0"
                    max="20"
                    step="0.1"
                    @input="setTextSpacing('line_spacing', $event)"
                  />
                </div>
              </div>
            </fieldset>
            <p class="help">{{ $t('common.zeroUsesNormalSpacingGapsShrinkWithText') }}</p>
            <fieldset class="text-padding">
              <legend>
                <span class="setting-toggle"
                  >{{ $t('common.textPaddingMm') }}<SettingHelp :help="editorHelp.padding"
                /></span>
              </legend>
              <div
                class="field-row"
                v-for="pair in [paddingSides.slice(0, 2), paddingSides.slice(2)]"
                :key="pair[0]"
              >
                <label v-for="side in pair" :key="side"
                  >{{ side[0].toUpperCase() + side.slice(1) }}
                  <input
                    :aria-label="`${side[0].toUpperCase() + side.slice(1)} padding (mm)`"
                    :value="selected[`padding_${side}`] ?? 0"
                    type="number"
                    min="0"
                    step="0.1"
                    @input="setPadding(side, $event)"
                  />
                </label>
              </div>
            </fieldset>
          </PropertySection>
          <PropertySection
            v-if="selected.kind === 'image'"
            :title="$t('templateEditor.imageAdjustments')"
            initially-open
          >
            <div class="setting-toggle">
              <label class="checkbox"
                ><input
                  type="checkbox"
                  :checked="selected.preserve_aspect ?? true"
                  @change="setPreserveAspect"
                />{{ $t('templateEditor.keepImageProportions') }}</label
              ><SettingHelp :help="editorHelp.imageProportions" />
            </div>
            <div class="setting-field">
              <SettingHelp
                :help="editorHelp.imageScale"
                for="setting-imageScale"
                :label="$t('templateEditor.imageScale')"
              /><input
                id="setting-imageScale"
                type="number"
                min="0.1"
                max="1"
                step="0.05"
                :value="selected.image_scale ?? 1"
                @input="setImageScale"
                @change="record"
              />
            </div>
            <input
              type="range"
              :aria-label="$t('templateEditor.imageScaleSlider')"
              min="0.1"
              max="1"
              step="0.05"
              :value="selected.image_scale ?? 1"
              @input="setImageScale"
              @change="record"
            />
            <div class="setting-field">
              <SettingHelp
                :help="editorHelp.brightness"
                for="setting-brightness"
                :label="$t('templateEditor.brightness')"
              /><input
                id="setting-brightness"
                type="number"
                min="0"
                max="3"
                step="0.1"
                v-model.number="selected.brightness"
                @change="record"
              />
            </div>
            <div class="setting-field">
              <SettingHelp
                :help="editorHelp.contrast"
                for="setting-contrast"
                :label="$t('templateEditor.contrast')"
              /><input
                id="setting-contrast"
                type="number"
                min="0"
                max="3"
                step="0.1"
                v-model.number="selected.contrast"
                @change="record"
              />
            </div>
            <div class="setting-field">
              <SettingHelp
                :help="editorHelp.conversion"
                for="setting-conversion"
                :label="$t('templateEditor.imageConversion')"
              /><select id="setting-conversion" v-model="selected.image_mode" @change="record">
                <option value="threshold">{{ $t('templateEditor.blackAndWhiteThreshold') }}</option>
                <option value="dither">{{ $t('templateEditor.ditheredShading') }}</option>
              </select>
            </div>
            <div v-if="selected.image_mode !== 'dither'" class="setting-field">
              <SettingHelp
                :help="editorHelp.threshold"
                for="setting-threshold"
                :label="$t('common.threshold')"
              /><input
                id="setting-threshold"
                type="number"
                min="1"
                max="255"
                step="1"
                v-model.number="selected.image_threshold"
                @change="record"
              />
            </div>
          </PropertySection>
          <PropertySection
            v-if="selected.kind === 'rectangle' || selected.kind === 'line'"
            :title="$t('templateEditor.appearance')"
            initially-open
          >
            <template v-if="selected.kind === 'rectangle' || selected.kind === 'line'"
              ><label
                >{{ $t('common.strokeMm')
                }}<input
                  :value="selected.stroke"
                  @input="setStroke"
                  type="number"
                  min="0.1"
                  max="3"
                  step="0.1"
                  @change="record" /></label
              ><label v-if="selected.kind === 'rectangle'" class="checkbox"
                ><input v-model="selected.filled" type="checkbox" @change="record" />{{
                  $t('templateEditor.filledRectangle')
                }}</label
              ></template
            >
          </PropertySection>
        </div>
        <div
          v-show="activeInspector === 'layout'"
          id="inspector-layout-panel"
          role="tabpanel"
          aria-labelledby="inspector-layout-tab"
          :inert="activeInspector !== 'layout'"
          class="inspector-panel"
        >
          <PropertySection :title="$t('templateEditor.positionSize')" initially-open>
            <div class="field-row">
              <label
                >{{ $t('common.xMm')
                }}<input
                  :value="elementGeometry(positionedElement(selected)).x"
                  :disabled="positionLocked('x')"
                  @input="setPosition('x', $event)"
                  type="number"
                  min="-1000"
                  step="0.5"
                  @change="record" /></label
              ><label
                >{{ $t('common.yMm')
                }}<input
                  :value="elementGeometry(positionedElement(selected)).y"
                  :disabled="positionLocked('y')"
                  @input="setPosition('y', $event)"
                  type="number"
                  min="-100"
                  step="0.5"
                  @change="record"
              /></label>
            </div>
            <div class="field-row">
              <label
                >{{
                  selected.kind === 'line' ? $t('companionApp.lengthMm') : $t('uiMessages.widthMm')
                }}<input
                  ref="widthInput"
                  :value="
                    elementGeometry(positionedElement(selected))[
                      selected.kind === 'line' && selected.rotation % 180 ? 'height' : 'width'
                    ]
                  "
                  :disabled="automaticDimension(selected) === 'width'"
                  type="number"
                  min="1"
                  step="0.5"
                  @input="
                    resize(
                      selected.kind === 'line' && selected.rotation % 180 ? 'height' : 'width',
                      $event,
                    )
                  "
                  @change="record" /></label
              ><label v-if="selected.kind !== 'line'"
                >{{ $t('templateEditor.heightMm')
                }}<input
                  :value="elementGeometry(positionedElement(selected)).height"
                  :disabled="selected.kind === 'qr' || automaticDimension(selected) === 'height'"
                  type="number"
                  min="1"
                  step="0.5"
                  @input="resize('height', $event)"
                  @change="record"
              /></label>
            </div>
            <label v-if="selected.kind === 'line'"
              >{{ $t('templateEditor.direction')
              }}<select :value="selected.rotation % 180" @change="rotateElement">
                <option :value="0">{{ $t('templateEditor.horizontal') }}</option>
                <option :value="90">{{ $t('common.vertical') }}</option>
              </select></label
            >
            <label v-else
              >{{ $t('templateEditor.rotation')
              }}<select :value="selected.rotation" @change="rotateElement">
                <option v-for="angle in [0, 90, 180, 270]" :key="angle">{{ angle }}</option>
              </select></label
            >
            <template v-if="selected.kind === 'image'">
              <div class="setting-toggle">
                <label class="checkbox"
                  ><input
                    type="checkbox"
                    :checked="boxAspectLocked(selected)"
                    @change="setBoxAspectLock"
                  />{{ $t('templateEditor.lockBoxProportions') }}</label
                ><SettingHelp :help="editorHelp.boxProportions" />
              </div>
              <ExpandableContent :open="imageBoxMismatch"
                ><div class="image-fit-action">
                  <button
                    type="button"
                    class="secondary"
                    :disabled="
                      rendering ||
                      selectedBindings.some((property) =>
                        ['width', 'height', 'rotation'].includes(property),
                      )
                    "
                    @click="fitImageBox"
                  >
                    {{ $t('templateEditor.fitBoxToImage') }}
                  </button>
                </div></ExpandableContent
              >
            </template>
            <template v-if="selected.kind === 'text'">
              <div class="setting-toggle">
                <label class="checkbox"
                  ><input
                    v-model="selected.auto_width"
                    type="checkbox"
                    @change="changeAutomaticWidth"
                  />{{
                    selected.rotation % 180
                      ? $t('uiMessages.fitTextBoxHeightToContent')
                      : $t('uiMessages.fitTextBoxWidthToContent')
                  }}</label
                ><SettingHelp :help="editorHelp.autoWidth" />
              </div>
            </template>
            <template v-if="selected.kind === 'qr'">
              <div class="setting-toggle">
                <label class="checkbox">
                  <input v-model="selected.qr_fill_box" type="checkbox" @change="record" />
                  {{ $t('common.scaleUpToBoundingBox') }} </label
                ><SettingHelp :help="editorHelp.qrFill" />
              </div>
              <template v-if="selected.qr_fill_box">
                <div class="setting-field">
                  <SettingHelp
                    :help="editorHelp.qrMargin"
                    for="setting-qrMargin"
                    :label="$t('templateEditor.qrMarginMm')"
                  /><input
                    id="setting-qrMargin"
                    type="number"
                    min="0"
                    step="0.1"
                    :value="selected.qr_margin_mm ?? ''"
                    :placeholder="$t('templateEditor.auto4Modules')"
                    @change="setQrMargin"
                  />
                </div>
                <p class="help">
                  {{ $t('templateEditor.insetOnEachSide0FillsTheBoxBlank') }}
                </p>
              </template>
            </template>
          </PropertySection>
          <PropertySection :title="$t('templateEditor.distanceHolder')">
            <div class="setting-field">
              <SettingHelp
                :help="editorHelp.follow"
                for="setting-follow"
                :label="$t('templateEditor.followElement')"
              /><select
                id="setting-follow"
                :value="selected.distance_holder?.element_id ?? ''"
                @change="setDistanceTarget"
              >
                <option value="">{{ $t('templateEditor.noneFreePosition') }}</option>
                <option v-for="element in distanceTargets" :key="element.id" :value="element.id">
                  {{ document.elements.indexOf(element) + 1 }}.
                  {{ element.name?.trim() || element.kind
                  }}{{
                    !element.name?.trim() && element.content
                      ? ` · ${element.content.slice(0, 40)}`
                      : ''
                  }}
                </option>
              </select>
            </div>
            <template v-if="selected.distance_holder">
              <label
                >{{ $t('templateEditor.placement')
                }}<select v-model="selected.distance_holder.axis" @change="record">
                  <option value="horizontal">{{ $t('templateEditor.rightOfElement') }}</option>
                  <option value="vertical">{{ $t('templateEditor.belowElement') }}</option>
                </select></label
              >
              <div class="setting-field">
                <SettingHelp
                  :help="editorHelp.gap"
                  for="setting-gap"
                  :label="$t('templateEditor.gapMm')"
                /><input
                  id="setting-gap"
                  v-model.number="selected.distance_holder.gap_mm"
                  type="number"
                  min="0"
                  max="300"
                  step="0.5"
                  @change="record"
                />
              </div>
            </template>
            <p class="help">
              {{ $t('templateEditor.gapBetweenElementBoundsIncludingRotationAndPaddingDeleting') }}
            </p>
          </PropertySection>
          <PropertySection :title="$t('templateEditor.arrange')">
            <div class="row wrap">
              <button class="small" @click="align('left')">
                {{ $t('templateEditor.alignLeft') }}</button
              ><button class="small" @click="align('center')">
                {{ $t('templateEditor.centerHorizontally') }}</button
              ><button class="small" @click="align('right')">
                {{ $t('templateEditor.alignRight') }}</button
              ><button class="small" @click="align('middle')">
                {{ $t('templateEditor.centerVertically') }}
              </button>
            </div>
            <div class="row wrap">
              <button class="small" @click="order(-1)">{{ $t('common.sendBackward') }}</button
              ><button class="small" @click="order(1)">
                {{ $t('templateEditor.bringForward') }}
              </button>
            </div>
          </PropertySection>
        </div>
      </MotionSurface>
    </section>
  </div>
  <LogicWorkspace
    v-if="ready && w.profiles.length"
    :document="document"
    :destination-id="w.selectedPrinter || undefined"
    :preview="preview?.design_png"
    :preview-length-mm="preview?.length_mm"
    :preview-width-mm="preview?.width_mm"
    :preview-error="error"
    :disabled="!editable || w.busy"
    @apply="applyLogic"
    @blocked="logicBlocked = $event"
  />
  <section v-if="ready && w.profiles.length" class="panel variable-fields">
    <div class="section-heading">
      <div class="setting-toggle">
        <h2>{{ $t('common.variableFields') }}</h2>
        <SettingHelp :help="editorHelp.variables" />
      </div>
      <button @click="addField">{{ $t('templateEditor.addVariable') }}</button>
    </div>
    <p v-if="document.fields.length" class="help">
      {{ $t('templateEditor.samplesAreUsedInTheEditorDefaultsPrefillThe') }}
    </p>
    <div
      v-for="(field, index) in document.fields"
      :key="index"
      class="variable-row"
      :class="{ 'image-variable': field.type === 'image' }"
    >
      <label
        >{{ $t('common.variableName')
        }}<input
          :value="field.name"
          pattern="[A-Za-z][A-Za-z0-9_]*"
          :maxlength="document.version === 2 ? 40 : undefined"
          @change="changeFieldName(field, $event)" /></label
      ><label
        >{{ $t('templateEditor.fieldLabel') }}<input v-model="field.label" @change="record"
      /></label>
      <label
        >{{ $t('common.type')
        }}<select :value="field.type ?? 'text'" @change="changeFieldType(field, $event)">
          <option value="text">{{ $t('common.text') }}</option>
          <option value="number">{{ $t('templateEditor.number') }}</option>
          <option value="boolean">{{ $t('templateEditor.boolean') }}</option>
          <option value="image">{{ $t('templateEditor.image') }}</option>
        </select></label
      >
      <VariableInput
        :key="`${field.name}:${field.type}:sample`"
        v-model="field.sample"
        :field="field"
        :label="$t('templateEditor.sampleValue')"
        nullable
        @change="record"
      />
      <VariableInput
        :key="`${field.name}:${field.type}:default`"
        v-model="field.default"
        :field="field"
        :label="$t('templateEditor.defaultValue')"
        nullable
        @change="record"
      />
      <label class="checkbox"
        ><input v-model="field.required" type="checkbox" @change="record" />{{
          $t('common.required')
        }}</label
      ><button class="danger-text" @click="removeField(index)">
        {{ $t('templateEditor.removeVariable') }}
      </button>
      <ExpandableContent :open="field.type === 'number'" class="variable-limits">
        <div class="field-row">
          <label
            >{{ $t('templateEditor.minimum')
            }}<input
              type="number"
              step="any"
              min="-1000000000000"
              max="1000000000000"
              :value="field.minimum ?? ''"
              @change="changeLimit(field, 'minimum', $event)"
          /></label>
          <label
            >{{ $t('templateEditor.maximum')
            }}<input
              type="number"
              step="any"
              min="-1000000000000"
              max="1000000000000"
              :value="field.maximum ?? ''"
              @change="changeLimit(field, 'maximum', $event)"
          /></label>
        </div>
      </ExpandableContent>
      <ExpandableContent :open="!field.type || field.type === 'text'" class="variable-limits">
        <div class="field-row">
          <div class="setting-field">
            <SettingHelp
              :help="editorHelp.minimumLength"
              :for="`setting-minimumLength-${index}`"
              :label="$t('templateEditor.minimumLength')"
            /><input
              :id="`setting-minimumLength-${index}`"
              type="number"
              min="0"
              max="2000"
              step="1"
              :value="field.min_length ?? ''"
              @change="changeLimit(field, 'min_length', $event)"
            />
          </div>
          <div class="setting-field">
            <SettingHelp
              :help="editorHelp.maximumLength"
              :for="`setting-maximumLength-${index}`"
              :label="$t('templateEditor.maximumLength')"
            /><input
              :id="`setting-maximumLength-${index}`"
              type="number"
              min="0"
              max="2000"
              step="1"
              :value="field.max_length ?? ''"
              @change="changeLimit(field, 'max_length', $event)"
            />
          </div>
        </div>
      </ExpandableContent>
    </div>
  </section>
  <TemplateHistory
    :open="revisionHistoryOpen"
    :template-id="id ?? ''"
    :template-name="name"
    :can-restore="editable"
    :unsaved-changes="dirty"
    @close="revisionHistoryOpen = false"
    @restored="applyRestoredRevision"
  />
</template>
<style scoped>
.canvas-example-name {
  text-align: right;
  color: var(--text-secondary);
  overflow-wrap: anywhere;
  margin-bottom: 8px;
}
.canvas-example-navigation {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  align-items: center;
  gap: 8px;
}
.canvas-example-navigation.has-examples {
  grid-template-columns: 44px minmax(0, 1fr) 44px;
}
.canvas-example-arrow {
  width: 44px;
  min-height: 44px;
  padding: 10px;
}
.canvas-example-arrow svg {
  width: 20px;
  height: 20px;
}
.setting-field {
  display: flex;
  flex-direction: column;
  gap: 7px;
  min-width: 0;
}
.setting-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.setting-toggle > label {
  flex: initial;
}
.variable-row > .setting-field {
  flex: 1;
  min-width: 120px;
}

.image-fit-action {
  padding-block: 4px 8px;
}
.image-fit-action button {
  min-height: 44px;
}
.element-list button,
.editor-properties > h2 {
  max-width: 100%;
  overflow-wrap: anywhere;
}
.editor-settings-fields input:disabled {
  background: var(--surface-dense);
  color: var(--muted);
  -webkit-text-fill-color: currentColor;
  opacity: 1;
  cursor: not-allowed;
}
.template-sharing {
  max-width: 600px;
}
.template-history-sharing {
  margin-block: 12px;
}
.variable-fields > .section-heading:last-child {
  margin-bottom: 0;
}
.variable-limits {
  flex-basis: 100%;
}
.image-variable {
  align-items: start;
}
.variable-row > .image-value-input {
  flex: 2;
  min-width: min(240px, 100%);
}
</style>
