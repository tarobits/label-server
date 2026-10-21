<script setup lang="ts">
import { confirmAction } from '../confirmation'
import EditorRuler from '../components/EditorRuler.vue'
import PropertySection from '../components/PropertySection.vue'
import { PhotoIcon, LanguageIcon, QrCodeIcon, StopIcon, MinusIcon } from '@heroicons/vue/24/outline'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { api, errorMessage } from '../api'
import { useAuthStore } from '../auth'
import { useWorkspaceStore } from '../workspace'
import { useResourceStore } from '../stores/resources'
import { randomUUID } from '../uuid'
import {
  newDocument,
  newElement,
  type Element,
  type Preview,
  type TemplateDocument,
} from '../editor'
import type { ImageAsset, Template } from '../types'
const w = useWorkspaceStore()
const resources = useResourceStore()
const auth = useAuthStore()
const route = useRoute(),
  router = useRouter()
const document = ref<TemplateDocument>(newDocument()),
  name = ref('Untitled label'),
  id = ref<string | null>(null),
  revision = ref(0)
const scope = ref<'personal' | 'group' | 'global'>('personal'),
  groupId = ref<string | null>(null)
const userGroups = ref<{ id: string; name: string }[]>([])
const availableGroups = computed(() =>
  userGroups.value.filter(
    (group) =>
      auth.user?.is_admin ||
      group.id === groupId.value ||
      auth.user?.group_memberships?.[group.id]?.can_create,
  ),
)
const editable = ref(true)
const imageFile = ref<File | null>(null)
const imageInput = ref<HTMLInputElement | null>(null)
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
const sampleProfile = computed({
  get: () => document.value.preview_tape?.id ?? '',
  set: (id: string) => {
    const profile = w.profiles.find((p) => p.id === id)
    if (!profile) return
    document.value.preview_tape = {
      id: profile.id,
      name: profile.name,
      foreground: profile.foreground,
      background: profile.background,
    }
    document.value.width_mm = profile.width_mm
    record()
  },
})
const selectedProfile = computed(() => w.profiles.find((p) => p.id === sampleProfile.value))
const saved = ref(''),
  history = ref<string[]>([]),
  cursor = ref(0),
  margin = ref(1)
const printableWidths = ref<Record<string, number>>({})
const verticalMargin = computed(() => {
  const band = printableWidths.value[String(document.value.width_mm)]
  return band ? (document.value.width_mm - band) / 2 : margin.value
})
const selected = computed(() => document.value.elements.find((e) => e.id === selectedId.value))
const snapshot = () =>
  JSON.stringify({
    name: name.value,
    document: document.value,
    scope: scope.value,
    group_id: groupId.value,
  })
const dirty = computed(() => ready.value && snapshot() !== saved.value)
const canvasLength = computed(() =>
  document.value.auto_length
    ? (preview.value?.length_mm ?? document.value.length_mm)
    : document.value.length_mm,
)
const canvasElements = computed(() =>
  document.value.elements.map((element) => {
    const resolved = preview.value?.resolved_elements.find((e) => e.id === element.id)
    return resolved
      ? {
          ...element,
          x: element.distance_holder?.axis === 'horizontal' ? resolved.x : element.x,
          y: element.distance_holder?.axis === 'vertical' ? resolved.y : element.y,
          width: element.auto_width ? resolved.width : element.width,
        }
      : element
  }),
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
  if (selected.value && !positionLocked(axis))
    selected.value[axis] = Number((event.target as HTMLInputElement).value)
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
  const rotated = e.rotation === 90 || e.rotation === 270
  const width = rotated ? e.height : e.width,
    height = rotated ? e.width : e.height
  return { x: e.x + (e.width - width) / 2, y: e.y + (e.height - height) / 2, width, height }
})
watch(
  () => w.selectedPrinter,
  () => {
    const capabilities = w.destinationPrinter(w.selectedPrinter)?.capabilities
    if (!capabilities) return
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
let drag: { mode: 'move' | 'size'; x: number; y: number; element: Element } | null = null
function record() {
  const state = snapshot()
  if (history.value[cursor.value] === state) return
  history.value = history.value.slice(0, cursor.value + 1)
  history.value.push(state)
  if (history.value.length > 100) history.value.shift()
  cursor.value = history.value.length - 1
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
      scope.value = template.scope ?? 'global'
      groupId.value = template.group_id ?? null
      if (groupId.value && !userGroups.value.some((g) => g.id === groupId.value))
        userGroups.value.push({ id: groupId.value, name: 'Current template group' })
      editable.value =
        template.can_edit ?? (!!auth.user?.is_admin || template.owner_id === auth.user?.id)
      document.value = { print_resolution: 'printer', ...structuredClone(template.document) }
    } else {
      id.value = null
      revision.value = 0
      name.value = 'Untitled label'
      scope.value = 'personal'
      groupId.value = null
      editable.value = true
      document.value = newDocument()
    }
    if (!document.value.preview_tape) {
      const profile =
        (!id.value && (w.profiles.find((p) => p.id === route.query.profile) || w.activeProfile)) ||
        w.profiles.find((p) => p.width_mm === document.value.width_mm) ||
        w.profiles[0]
      if (profile) sampleProfile.value = profile.id
    } else if (selectedProfile.value) {
      document.value.width_mm = selectedProfile.value.width_mm
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
        document: document.value,
        use_samples: true,
      },
      w.destinationPrinter(w.selectedPrinter)?.capabilities,
    )
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
  [document, sampleProfile, () => w.selectedPrinter],
  () => {
    serial++
    clearTimeout(timer)
    rendering.value = true
    timer = setTimeout(updatePreview, 300)
  },
  { deep: true },
)
watch(() => route.params.id, load)
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
function add(kind: Element['kind']) {
  const element = newElement(kind)
  element.x = margin.value
  element.y = verticalMargin.value
  element.width = Math.min(element.width, document.value.length_mm - 2 * margin.value)
  element.height = Math.min(element.height, document.value.width_mm - 2 * verticalMargin.value)
  if (kind === 'qr') element.width = element.height
  document.value.elements.push(element)
  selectedId.value = element.id
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
  selectedId.value = ''
  record()
}
function duplicate() {
  if (selected.value) {
    const e = structuredClone({ ...selected.value })
    e.id = randomUUID()
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
  const drawn = positionedElement(e)
  const rotatedWidth = e.rotation % 180 ? drawn.height : drawn.width
  const inset = (drawn.width - rotatedWidth) / 2
  if (axis === 'middle' && !positionLocked('y')) e.y = (document.value.width_mm - e.height) / 2
  else if (axis !== 'middle' && !positionLocked('x'))
    e.x =
      axis === 'left'
        ? margin.value - inset
        : axis === 'right'
          ? canvasLength.value - margin.value - rotatedWidth - inset
          : (canvasLength.value - drawn.width) / 2
  record()
}
function point(event: PointerEvent) {
  const box = canvas.value!.getBoundingClientRect()
  return { x: (event.clientX - box.left) / scale.value, y: (event.clientY - box.top) / scale.value }
}
function start(event: PointerEvent, element: Element, mode: 'move' | 'size') {
  event.preventDefault()
  selectedId.value = element.id
  drag = { mode, ...point(event), element: { ...element } }
  canvas.value?.setPointerCapture(event.pointerId)
}
function move(event: PointerEvent) {
  const p = point(event)
  pointer.value =
    p.x >= 0 && p.x <= canvasLength.value && p.y >= 0 && p.y <= document.value.width_mm ? p : null
  if (!drag || !selected.value) return
  const dx = p.x - drag.x,
    dy = p.y - drag.y
  const round = (value: number) =>
    Math.round(value * (snap.value ? 2 : 100)) / (snap.value ? 2 : 100)
  if (drag.mode === 'move') {
    if (!positionLocked('x'))
      selected.value.x = Math.max(
        drag.element.rotation % 180 ? (drag.element.height - drag.element.width) / 2 : 0,
        round(drag.element.x + dx),
      )
    if (!positionLocked('y'))
      selected.value.y = Math.max(
        drag.element.rotation % 180 ? (drag.element.width - drag.element.height) / 2 : 0,
        round(drag.element.y + dy),
      )
  } else {
    const angle = (drag.element.rotation * Math.PI) / 180
    const cos = Math.round(Math.cos(angle)),
      sin = Math.round(Math.sin(angle))
    const localX = cos * dx + sin * dy
    const localY = -sin * dx + cos * dy
    selected.value.auto_width = false
    selected.value.width = Math.max(1, round(drag.element.width + localX))
    if (selected.value.kind === 'image' && selected.value.preserve_aspect) {
      const ratio = imageRatio(selected.value) ?? drag.element.width / drag.element.height
      // Snap the actively dragged dimension; derive the other without rounding.
      if (Math.abs(localY / drag.element.height) > Math.abs(localX / drag.element.width)) {
        selected.value.height = Math.max(1, round(drag.element.height + localY))
        selected.value.width = selected.value.height * ratio
      } else {
        selected.value.height = selected.value.width / ratio
      }
    } else
      selected.value.height =
        selected.value.kind === 'qr'
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
function finish() {
  if (drag) {
    drag = null
    record()
  }
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
    w.actionError = 'Upload an image of at most 5 MB.'
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
  }, 'Image uploaded and added to the template.')
  if (ok && asset && document.value.elements.includes(target)) {
    target.image_asset = asset.id
    selectedId.value = target.id
    fitImageBox()
    imageFile.value = null
    if (imageInput.value) imageInput.value.value = ''
  }
}
function imageRatio(element: Element): number | undefined {
  const asset = w.images.find((asset) => asset.id === element.image_asset)
  return asset ? asset.width / asset.height : undefined
}
function fitImageBox() {
  const element = selected.value
  if (!element || element.kind !== 'image') return
  const ratio = imageRatio(element)
  if (ratio) {
    // Fit within the existing box so selecting artwork does not enlarge the label.
    element.width = Math.min(element.width, element.height * ratio)
    element.height = element.width / ratio
  }
  record()
}
function setPreserveAspect() {
  if (selected.value?.preserve_aspect) fitImageBox()
  else record()
}
function resize(axis: 'width' | 'height', event: Event) {
  const element = selected.value
  if (!element) return
  const value = Number((event.target as HTMLInputElement).value)
  if (!Number.isFinite(value) || value <= 0) return
  element[axis] = value
  if (element.kind === 'qr') element.height = element.width
  if (element.kind === 'image' && element.preserve_aspect) {
    const ratio = imageRatio(element)
    if (ratio) {
      if (axis === 'width') element.height = element.width / ratio
      else element.width = element.height * ratio
    }
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
  }, 'Template revision saved. Existing queued labels keep their original layout.')
  if (ok && result) {
    saved.value = snapshot()
    revision.value = result.revision
    id.value = result.id
    await router.replace({ path: `/templates/${result.id}/edit`, query: route.query })
  }
}
function removeField(index: number) {
  document.value.fields.splice(index, 1)
  record()
}
function addField() {
  let index = document.value.fields.length + 1
  while (document.value.fields.some((f) => f.name === `field${index}`)) index++
  document.value.fields.push({
    name: `field${index}`,
    label: `Field ${index}`,
    required: true,
    default: '',
    sample: 'Example',
  })
  record()
}
function beforeUnload(event: BeforeUnloadEvent) {
  if (dirty.value) {
    event.preventDefault()
    event.returnValue = ''
  }
}
onBeforeRouteLeave(() => !dirty.value || confirmAction('Discard unsaved template changes?'))
onMounted(() => {
  void load()
  window.addEventListener('beforeunload', beforeUnload)
})
onUnmounted(() => {
  stopped = true
  loadGeneration++
  serial++
  clearTimeout(timer)
  window.removeEventListener('beforeunload', beforeUnload)
})
</script>
<template>
  <div v-if="!w.profiles.length" class="panel empty">
    <h2>No tape profiles</h2>
    <RouterLink v-if="auth.can('inventory.manage')" class="button primary" to="/profiles"
      >Create tape profile</RouterLink
    >
    <p v-else class="help">Ask an administrator to create a tape profile.</p>
  </div>
  <div v-if="w.profiles.length && !editable" class="alert warning">
    This shared template is read-only. Duplicate it in the template library to create your own
    version.
  </div>
  <section v-if="w.profiles.length" class="panel editor-toolbar">
    <div class="editor-settings-fields">
      <label>Template name<input v-model="name" maxlength="100" required @change="record" /></label>
      <label class="resolution-choice"
        >Print resolution<select v-model="document.print_resolution" @change="record">
          <option value="printer">
            Printer default ({{ defaultResolution[1] }} × {{ defaultResolution[0] }} dpi)
          </option>
          <option v-for="(dpi, mode) in resolutionModes" :key="mode" :value="mode">
            {{ mode === 'high' ? 'High' : 'Normal' }} · {{ dpi[1] }} × {{ dpi[0] }} dpi
          </option>
        </select></label
      >
      <label
        >Tape profile<select v-model="sampleProfile" :disabled="!editable" required>
          <option v-if="!selectedProfile" :value="sampleProfile" disabled>
            {{
              document.preview_tape
                ? `Saved: ${document.preview_tape.name}`
                : 'Choose a tape profile'
            }}
          </option>
          <option v-for="p in w.profiles" :key="p.id" :value="p.id">
            {{ p.name }} · {{ p.width_mm }} mm
          </option>
        </select></label
      >
      <label
        >Label length (mm)<input
          :value="document.auto_length ? canvasLength : document.length_mm"
          @input="setManualLength"
          :disabled="document.auto_length"
          type="number"
          min="10"
          max="300"
          @change="record"
      /></label>
    </div>
    <div class="template-sharing field-row">
      <label
        >Template visibility<select v-model="scope" :disabled="!editable" @change="record">
          <option value="personal">Personal</option>
          <option v-if="availableGroups.length" value="group">User group</option>
          <option
            v-if="auth.user?.is_admin || scope === 'global'"
            value="global"
            :disabled="!auth.user?.is_admin"
          >
            Global
          </option>
        </select></label
      >
      <label v-if="scope === 'group'"
        >User group<select v-model="groupId" :disabled="!editable" required @change="record">
          <option :value="null" disabled>Choose a group</option>
          <option v-for="group in availableGroups" :key="group.id" :value="group.id">
            {{ group.name }}
          </option>
        </select></label
      >
    </div>
    <div class="editor-settings-footer">
      <div class="editor-settings-toggles">
        <label class="checkbox"
          ><input v-model="document.auto_length" type="checkbox" @change="record" /><span
            >Automatic label length</span
          ></label
        >
        <label class="checkbox"
          ><input
            :checked="document.out_of_bounds === 'clip'"
            type="checkbox"
            @change="setClipping"
          /><span>Ignore out-of-bounds objects</span></label
        >
      </div>
      <div class="editor-settings-actions">
        <button :disabled="cursor === 0" @click="restore(-1)">Undo</button
        ><button :disabled="cursor >= history.length - 1" @click="restore(1)">Redo</button>
        <button
          class="primary"
          :disabled="
            w.busy ||
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
          Save template
        </button>
        <span class="help">{{
          dirty ? 'Unsaved changes' : revision ? `Revision ${revision}` : 'New document'
        }}</span>
      </div>
    </div>
  </section>
  <div v-if="w.profiles.length" class="editor-layout" :class="{ 'no-selection': !selected }">
    <section class="panel editor-workspace">
      <div class="editor-tools">
        <div class="editor-add-buttons" role="group" aria-label="Add elements">
          <button aria-label="Add image" @click="add('image')"><PhotoIcon />Image</button>
          <button aria-label="Add text" @click="add('text')"><LanguageIcon />Text</button>
          <button aria-label="Add QR code" @click="add('qr')"><QrCodeIcon />QR code</button>
          <button aria-label="Add rectangle" @click="add('rectangle')">
            <StopIcon />Rectangle
          </button>
          <button aria-label="Add line" @click="add('line')"><MinusIcon />Line</button>
        </div>
      </div>
      <div class="editor-options">
        <label class="checkbox"
          ><input v-model="showPrintPixels" type="checkbox" />Show print pixels</label
        >
        <label class="checkbox"><input v-model="snap" type="checkbox" />Snap 0.5 mm</label>
        <label class="checkbox"
          ><input v-model="showBounds" type="checkbox" />Object boundaries</label
        >
        <label class="editor-zoom"
          >Zoom
          <input
            aria-label="Zoom"
            v-model.number="zoom"
            type="range"
            min="50"
            max="250"
            step="10"
          />
          <output>{{ zoom }}%</output>
        </label>
      </div>
      <div class="editor-canvas-scroll">
        <div class="editor-board">
          <div class="ruler-corner">mm</div>
          <EditorRuler
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
            aria-label="Label design canvas"
            :width="canvasLength * scale"
            :height="document.width_mm * scale"
            :viewBox="`0 0 ${canvasLength} ${document.width_mm}`"
            @pointermove="move"
            @pointerup="finish"
            @pointercancel="finish"
            @pointerleave="pointer = null"
            @keydown="key"
          >
            <defs>
              <pattern id="editor-grid" width="1" height="1" patternUnits="userSpaceOnUse">
                <path d="M1 0H0V1" fill="none" stroke="#818cf8" stroke-width="0.03" />
              </pattern>
            </defs>
            <rect width="100%" height="100%" fill="white" @pointerdown="selectedId = ''" />
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
              :x="margin"
              :y="verticalMargin"
              :width="canvasLength - margin * 2"
              :height="document.width_mm - verticalMargin * 2"
              fill="none"
              stroke="#ef4444"
              stroke-width="0.1"
              stroke-dasharray="0.5 0.5"
              style="pointer-events: none"
            />
            <g
              v-for="element in canvasElements"
              :key="element.id"
              :transform="`rotate(${element.rotation},${element.x + element.width / 2},${element.y + element.height / 2})`"
            >
              <rect
                :x="element.x"
                :y="element.y"
                :width="element.width"
                :height="element.height"
                :fill="selectedId === element.id ? '#6366f11a' : 'transparent'"
                class="object-boundary"
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
                :cy="element.y + element.height"
                r="0.6"
                fill="#6366f1"
                :style="{ cursor: element.rotation % 180 ? 'nesw-resize' : 'nwse-resize' }"
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
      <p v-if="pointer" class="help cursor-position">
        Cursor: {{ pointer.x.toFixed(2) }} × {{ pointer.y.toFixed(2) }} mm
      </p>
      <p class="help">
        {{ canvasLength }} × {{ document.width_mm }} mm · {{ margin }} mm end /
        {{ verticalMargin.toFixed(2) }} mm side guides ·
        {{
          rendering
            ? 'Rendering…'
            : showPrintPixels
              ? 'Device raster preview'
              : 'Smooth design preview'
        }}
      </p>
      <p v-if="document.auto_length || document.out_of_bounds === 'clip'" class="help">
        <span v-if="document.auto_length">Automatic length: 10–300 mm.</span>
        <span v-if="document.out_of_bounds === 'clip'">
          Objects outside the guides are clipped.
        </span>
      </p>
      <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
      <p v-for="warning in preview?.warnings ?? []" :key="warning" class="alert warning">
        {{ warning }}
      </p>
      <div v-if="document.elements.length" class="row wrap">
        <button
          v-for="(element, index) in document.elements"
          :key="element.id"
          class="small"
          :aria-pressed="selectedId === element.id"
          @click="selectedId = element.id"
        >
          {{ index + 1 }}. {{ element.kind }}
        </button>
      </div>
    </section>
    <section
      v-if="selected"
      class="panel editor-properties"
      aria-labelledby="element-properties-heading"
    >
      <h2 id="element-properties-heading">Element properties</h2>
      <div class="editor-property-sections">
        <PropertySection title="Position &amp; size" initially-open>
          <div class="field-row">
            <label
              >X (mm)<input
                :value="positionLocked('x') ? positionedElement(selected).x : selected.x"
                :disabled="positionLocked('x')"
                @input="setPosition('x', $event)"
                type="number"
                min="-1000"
                step="0.5"
                @change="record" /></label
            ><label
              >Y (mm)<input
                :value="positionLocked('y') ? positionedElement(selected).y : selected.y"
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
              >Width (mm)<input
                :value="selected.width"
                :disabled="selected.kind === 'text' && selected.auto_width"
                type="number"
                min="1"
                step="0.5"
                @input="resize('width', $event)"
                @change="record" /></label
            ><label
              >Height (mm)<input
                :value="selected.height"
                :disabled="selected.kind === 'qr'"
                type="number"
                min="1"
                step="0.5"
                @input="resize('height', $event)"
                @change="record"
            /></label>
          </div>
          <label
            >Rotation<select v-model.number="selected.rotation" @change="record">
              <option v-for="angle in [0, 90, 180, 270]" :key="angle">{{ angle }}</option>
            </select></label
          >
        </PropertySection>
        <PropertySection
          v-if="['text', 'qr', 'image'].includes(selected.kind)"
          title="Content"
          initially-open
        >
          <label v-if="selected.kind === 'text' || selected.kind === 'qr'"
            >Content<textarea
              aria-label="Content"
              v-model="selected.content"
              maxlength="2000"
              rows="3"
              @change="record"
            ></textarea
            ><span class="help"
              >Use <code v-pre>{{ name }}</code> for a variable.</span
            ></label
          >
          <template v-if="selected.kind === 'image'">
            <label
              >Image<select v-model="selected.image_asset" @change="fitImageBox">
                <option :value="null" disabled>Select an uploaded image</option>
                <option
                  v-if="preview?.missing_assets?.[selected.id] === 'image'"
                  :value="selected.image_asset"
                  disabled
                >
                  Missing image — choose a replacement
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
            <label v-if="auth.can('assets.write')"
              >Upload image file<input
                ref="imageInput"
                type="file"
                accept=".png,.jpg,.jpeg,.webp,.bmp,.gif,.svg"
                :disabled="w.busy"
                @change="chooseImageFile"
            /></label>
            <button
              v-if="auth.can('assets.write')"
              class="secondary"
              :disabled="!imageFile || w.busy"
              @click="uploadImage"
            >
              Upload and use image
            </button>
            <label class="checkbox"
              ><input
                type="checkbox"
                v-model="selected.preserve_aspect"
                @change="setPreserveAspect"
              />Preserve aspect ratio</label
            >
          </template>
          <template v-if="selected.kind === 'qr'">
            <label class="checkbox">
              <input v-model="selected.qr_fill_box" type="checkbox" @change="record" />
              Scale up to bounding box
            </label>
            <template v-if="selected.qr_fill_box">
              <label
                >QR margin (mm)<input
                  type="number"
                  min="0"
                  step="0.1"
                  :value="selected.qr_margin_mm ?? ''"
                  placeholder="Auto (4 modules)"
                  @change="setQrMargin"
              /></label>
              <p class="help">
                Inset on each side: 0 fills the box; blank adds a four-module border. Leave clear
                space around the code for scanning.
              </p>
            </template>
          </template>
        </PropertySection>
        <PropertySection v-if="selected.kind === 'image'" title="Image adjustments">
          <label
            >Brightness<input
              type="number"
              min="0"
              max="3"
              step="0.1"
              v-model.number="selected.brightness"
              @change="record"
          /></label>
          <label
            >Contrast<input
              type="number"
              min="0"
              max="3"
              step="0.1"
              v-model.number="selected.contrast"
              @change="record"
          /></label>
          <label
            >Image conversion<select v-model="selected.image_mode" @change="record">
              <option value="threshold">Black and white (threshold)</option>
              <option value="dither">Dithered shading</option>
            </select></label
          >
          <label v-if="selected.image_mode !== 'dither'"
            >Threshold<input
              type="number"
              min="1"
              max="255"
              step="1"
              v-model.number="selected.image_threshold"
              @change="record"
          /></label>
          <p class="help">
            Brightness and contrast: 1 keeps the original. Dithering creates shading with ink dots.
          </p>
        </PropertySection>
        <PropertySection v-if="selected.kind === 'text'" title="Typography">
          <template v-if="selected.kind === 'text'"
            ><label class="checkbox"
              ><input v-model="selected.auto_width" type="checkbox" @change="record" />Fit text box
              width to content</label
            >
            <p class="help" v-if="selected.auto_width">Fits each value without wrapping.</p>
            <label
              >Font<select v-model="selected.font" @change="record">
                <option>Noto Sans</option>
                <option
                  v-if="preview?.missing_assets?.[selected.id] === 'font'"
                  :value="selected.font"
                  disabled
                >
                  Missing font — choose a replacement
                </option>
                <option
                  v-for="font in w.fonts.filter((f) => !f.archived || f.id === selected?.font)"
                  :key="font.id"
                  :value="font.id"
                >
                  {{ font.family }} · {{ font.style }}{{ font.archived ? ' (hidden)' : '' }}
                </option>
              </select></label
            ><label
              >Font size (mm)<input
                v-model.number="selected.font_size"
                type="number"
                min="1"
                max="24"
                step="0.1"
                @change="record"
            /></label>
            <p class="help">Text shrinks to fit; this is its maximum size.</p>
            <div class="row">
              <label class="checkbox"
                ><input
                  v-model="selected.bold"
                  :disabled="selected.font !== 'Noto Sans'"
                  type="checkbox"
                  @change="record"
                />Bold</label
              ><label class="checkbox"
                ><input v-model="selected.wrap" type="checkbox" @change="record" />Wrap text</label
              >
            </div></template
          >
          <p v-if="selected.kind === 'text' && selected.font !== 'Noto Sans'" class="help">
            For bold text, select an uploaded bold face.
          </p>
        </PropertySection>
        <PropertySection v-if="selected.kind === 'text'" title="Spacing &amp; alignment">
          <fieldset class="text-padding">
            <legend>Text spacing (mm)</legend>
            <div class="field-row">
              <label
                >Horizontal<input
                  aria-label="Horizontal character spacing (mm)"
                  :value="selected.character_spacing ?? 0"
                  type="number"
                  min="0"
                  max="20"
                  step="0.1"
                  @input="setTextSpacing('character_spacing', $event)"
              /></label>
              <label
                >Vertical<input
                  aria-label="Vertical line spacing (mm)"
                  :value="selected.line_spacing ?? 0"
                  type="number"
                  min="0"
                  max="20"
                  step="0.1"
                  @input="setTextSpacing('line_spacing', $event)"
              /></label>
            </div>
          </fieldset>
          <p class="help">Zero uses normal spacing; gaps shrink with text.</p>
          <fieldset class="text-padding">
            <legend>Text padding (mm)</legend>
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
          <label
            >Horizontal text alignment<select v-model="selected.align" @change="record">
              <option value="left">Left</option>
              <option value="center">Center</option>
              <option value="right">Right</option>
            </select></label
          >
          <label
            >Vertical text alignment<select
              :value="selected.vertical_align ?? 'top'"
              @change="setVerticalAlign"
            >
              <option value="top">Top</option>
              <option value="center">Center</option>
              <option value="bottom">Bottom</option>
            </select></label
          >
        </PropertySection>
        <PropertySection
          v-if="selected.kind === 'rectangle' || selected.kind === 'line'"
          title="Appearance"
          initially-open
        >
          <template v-if="selected.kind === 'rectangle' || selected.kind === 'line'"
            ><label
              >Stroke (mm)<input
                v-model.number="selected.stroke"
                type="number"
                min="0.1"
                max="3"
                step="0.1"
                @change="record" /></label
            ><label v-if="selected.kind === 'rectangle'" class="checkbox"
              ><input v-model="selected.filled" type="checkbox" @change="record" />Filled
              rectangle</label
            ></template
          >
        </PropertySection>
        <PropertySection title="Distance holder">
          <label
            >Follow element
            <select :value="selected.distance_holder?.element_id ?? ''" @change="setDistanceTarget">
              <option value="">None (free position)</option>
              <option v-for="element in distanceTargets" :key="element.id" :value="element.id">
                {{ document.elements.indexOf(element) + 1 }}. {{ element.kind
                }}{{ element.content ? ` · ${element.content.slice(0, 40)}` : '' }}
              </option>
            </select>
          </label>
          <template v-if="selected.distance_holder">
            <label
              >Placement<select v-model="selected.distance_holder.axis" @change="record">
                <option value="horizontal">Right of element</option>
                <option value="vertical">Below element</option>
              </select></label
            >
            <label
              >Gap (mm)<input
                v-model.number="selected.distance_holder.gap_mm"
                type="number"
                min="0"
                max="300"
                step="0.5"
                @change="record"
            /></label>
          </template>
          <p class="help">
            Gap between element bounds, including rotation and padding. Deleting the anchor detaches
            this element at its current position.
          </p>
        </PropertySection>
        <PropertySection title="Arrange">
          <div class="row wrap">
            <button class="small" @click="align('left')">Align left</button
            ><button class="small" @click="align('center')">Center horizontally</button
            ><button class="small" @click="align('right')">Align right</button
            ><button class="small" @click="align('middle')">Center vertically</button>
          </div>
          <div class="row wrap">
            <button class="small" @click="order(-1)">Send backward</button
            ><button class="small" @click="order(1)">Bring forward</button
            ><button class="small" @click="duplicate">Duplicate element</button
            ><button class="small danger-text" @click="remove">Delete element</button>
          </div>
        </PropertySection>
      </div>
    </section>
  </div>
  <section v-if="w.profiles.length" class="panel variable-fields">
    <div class="section-heading">
      <h2>Variable fields</h2>
      <button @click="addField">Add variable</button>
    </div>
    <p v-if="document.fields.length" class="help">
      Samples are used in the editor. Defaults prefill the label submission form.
    </p>
    <div v-for="(field, index) in document.fields" :key="index" class="variable-row">
      <label
        >Variable name<input
          v-model="field.name"
          pattern="[A-Za-z][A-Za-z0-9_]*"
          @change="record" /></label
      ><label>Field label<input v-model="field.label" @change="record" /></label
      ><label>Sample value<input v-model="field.sample" @change="record" /></label
      ><label>Default value<input v-model="field.default" @change="record" /></label
      ><label class="checkbox"
        ><input v-model="field.required" type="checkbox" @change="record" />Required</label
      ><button class="danger-text" @click="removeField(index)">Remove variable</button>
    </div>
  </section>
</template>
<style scoped>
.template-sharing {
  max-width: 600px;
}
.variable-fields > .section-heading:last-child {
  margin-bottom: 0;
}
</style>
