<script setup lang="ts">
import { confirmAction } from '../confirmation'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { api, errorMessage } from '../api'
import { workspace as w } from '../workspace'
import {
  newDocument,
  newElement,
  type Element,
  type Preview,
  type TemplateDocument,
} from '../editor'
import type { ImageAsset, Template } from '../types'
const route = useRoute(),
  router = useRouter()
const document = ref<TemplateDocument>(newDocument()),
  name = ref('Untitled label'),
  id = ref<string | null>(null),
  revision = ref(0)
const imageFile = ref<File | null>(null)
const imageInput = ref<HTMLInputElement | null>(null)
const selectedId = ref(''),
  zoom = ref(100),
  snap = ref(true),
  showGrid = ref(true),
  showPrintPixels = ref(false)
const preview = ref<Preview | null>(null),
  error = ref(''),
  rendering = ref(false),
  ready = ref(false)
const sampleProfile = ref(''),
  saved = ref(''),
  history = ref<string[]>([]),
  cursor = ref(0),
  margin = ref(1)
const selected = computed(() => document.value.elements.find((e) => e.id === selectedId.value))
const snapshot = () => JSON.stringify({ name: name.value, document: document.value })
const dirty = computed(() => ready.value && snapshot() !== saved.value)
const canvasLength = computed(() =>
  document.value.auto_length
    ? (preview.value?.length_mm ?? document.value.length_mm)
    : document.value.length_mm,
)
const canvasElements = computed(() =>
  document.value.elements.map((element) => {
    const resolved = preview.value?.resolved_elements.find((e) => e.id === element.id)
    return element.auto_width && resolved ? { ...element, width: resolved.width } : element
  }),
)
const scale = computed(() => (zoom.value / 100) * 8)
let timer: ReturnType<typeof setTimeout> | undefined,
  serial = 0,
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
  const value = JSON.parse(history.value[position]) as { name: string; document: TemplateDocument }
  name.value = value.name
  document.value = value.document
}
async function load() {
  ready.value = false
  try {
    const printers = await api<{ capabilities: { printable_margin_mm: number } }[]>('/printers')
    margin.value = printers[0]?.capabilities.printable_margin_mm ?? 1
    if (route.params.id) {
      const template = await api<Template>(`/templates/${route.params.id}`)
      id.value = template.id
      revision.value = template.revision
      name.value = template.name
      document.value = structuredClone(template.document)
    } else {
      id.value = null
      revision.value = 0
      name.value = 'Untitled label'
      document.value = newDocument()
    }
    saved.value = snapshot()
    history.value = [snapshot()]
    cursor.value = 0
    ready.value = true
    await updatePreview()
  } catch (e) {
    error.value = errorMessage(e)
  }
}
async function updatePreview() {
  const ticket = ++serial
  rendering.value = true
  try {
    const profile = w.profiles.value.find((p) => p.id === sampleProfile.value)
    const result = await api<Preview>('/preview', 'POST', {
      document: document.value,
      use_samples: true,
      foreground: profile?.foreground ?? '#000000',
      background: profile?.background ?? '#ffffff',
    })
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
  [document, name, sampleProfile],
  () => {
    serial++
    clearTimeout(timer)
    rendering.value = true
    timer = setTimeout(updatePreview, 300)
  },
  { deep: true },
)
watch(() => route.params.id, load)
function add(kind: Element['kind']) {
  const element = newElement(kind)
  element.width = Math.min(element.width, document.value.length_mm - 4)
  element.height = Math.min(element.height, document.value.width_mm - 4)
  if (kind === 'qr') element.width = element.height
  document.value.elements.push(element)
  selectedId.value = element.id
  record()
}
function remove() {
  document.value.elements = document.value.elements.filter((e) => e.id !== selectedId.value)
  selectedId.value = ''
  record()
}
function duplicate() {
  if (selected.value) {
    const e = structuredClone({ ...selected.value })
    e.id = crypto.randomUUID()
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
  if (axis === 'middle') e.y = (document.value.width_mm - e.height) / 2
  else
    e.x =
      axis === 'left'
        ? margin.value
        : axis === 'right'
          ? canvasLength.value - margin.value - e.width
          : (canvasLength.value - e.width) / 2
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
  if (!drag || !selected.value) return
  const p = point(event),
    dx = p.x - drag.x,
    dy = p.y - drag.y
  const round = (value: number) =>
    Math.round(value * (snap.value ? 2 : 100)) / (snap.value ? 2 : 100)
  if (drag.mode === 'move') {
    selected.value.x = Math.max(0, round(drag.element.x + dx))
    selected.value.y = Math.max(0, round(drag.element.y + dy))
  } else {
    selected.value.auto_width = false
    selected.value.width = Math.max(1, round(drag.element.width + dx))
    if (selected.value.kind === 'image' && selected.value.preserve_aspect) {
      const ratio = imageRatio(selected.value) ?? drag.element.width / drag.element.height
      // Snap the actively dragged dimension; derive the other without rounding.
      if (Math.abs(dy / drag.element.height) > Math.abs(dx / drag.element.width)) {
        selected.value.height = Math.max(1, round(drag.element.height + dy))
        selected.value.width = selected.value.height * ratio
      } else {
        selected.value.height = selected.value.width / ratio
      }
      return
    }
    selected.value.height =
      selected.value.kind === 'qr'
        ? selected.value.width
        : Math.max(1, round(drag.element.height + dy))
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
function chooseImageFile(event: Event) {
  imageFile.value = (event.target as HTMLInputElement).files?.[0] ?? null
}
async function uploadImage() {
  const file = imageFile.value,
    target = selected.value
  if (!file || target?.kind !== 'image') return
  if (file.size > 5_000_000) {
    w.actionError.value = 'Upload an image of at most 5 MB.'
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
  const asset = w.images.value.find((asset) => asset.id === element.image_asset)
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
    if (event.key === 'ArrowLeft') selected.value.x = Math.max(0, selected.value.x - delta)
    if (event.key === 'ArrowRight') selected.value.x += delta
    if (event.key === 'ArrowUp') selected.value.y = Math.max(0, selected.value.y - delta)
    if (event.key === 'ArrowDown') selected.value.y += delta
    record()
  }
}
async function save() {
  let result: Template | undefined
  const ok = await w.action(async () => {
    result = await api<Template>(
      `/templates${id.value ? `/${id.value}` : ''}`,
      id.value ? 'PUT' : 'POST',
      {
        name: name.value,
        document: document.value,
        expected_revision: id.value ? revision.value : null,
      },
    )
  }, 'Template revision saved. Existing queued labels keep their original layout.')
  if (ok && result) {
    saved.value = snapshot()
    revision.value = result.revision
    id.value = result.id
    await router.replace(`/templates/${result.id}/edit`)
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
  serial++
  clearTimeout(timer)
  window.removeEventListener('beforeunload', beforeUnload)
})
</script>
<template>
  <section class="panel editor-toolbar">
    <label>Template name<input v-model="name" maxlength="100" required @change="record" /></label>
    <label
      >Tape width (mm)<select v-model.number="document.width_mm" @change="record">
        <option v-for="width in [6, 9, 12, 18, 24]" :key="width">{{ width }}</option>
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
    <label class="checkbox"
      ><input v-model="document.auto_length" type="checkbox" @change="record" />Automatic label
      length</label
    >
    <label class="checkbox"
      ><input
        :checked="document.out_of_bounds === 'clip'"
        type="checkbox"
        @change="setClipping"
      />Ignore out-of-bounds objects</label
    >
    <button :disabled="cursor === 0" @click="restore(-1)">Undo</button
    ><button :disabled="cursor >= history.length - 1" @click="restore(1)">Redo</button>
    <button
      class="primary"
      :disabled="w.busy.value || !ready || rendering || !!error || !name.trim()"
      @click="save"
    >
      Save template
    </button>
    <span class="help">{{
      dirty ? 'Unsaved changes' : revision ? `Revision ${revision}` : 'New document'
    }}</span>
  </section>
  <div class="editor-layout">
    <section class="panel editor-workspace">
      <div class="row wrap">
        <button @click="add('image')">Add image</button
        ><button @click="add('text')">Add text</button
        ><button @click="add('qr')">Add QR code</button
        ><button @click="add('rectangle')">Add rectangle</button
        ><button @click="add('line')">Add line</button>
      </div>
      <div class="editor-options row wrap">
        <label class="checkbox"
          ><input v-model="showPrintPixels" type="checkbox" />Show print pixels</label
        >
        <label>Zoom<input v-model.number="zoom" type="range" min="50" max="250" step="10" /></label
        ><label class="checkbox"><input v-model="showGrid" type="checkbox" />Grid</label
        ><label class="checkbox"><input v-model="snap" type="checkbox" />Snap 0.5 mm</label
        ><label
          >Preview tape<select v-model="sampleProfile">
            <option value="">Black on white</option>
            <option v-for="p in w.profiles.value" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select></label
        >
      </div>
      <div class="editor-canvas-scroll">
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
            style="pointer-events: none"
            :style="{ imageRendering: showPrintPixels ? 'pixelated' : 'auto' }"
          />
          <rect
            v-if="showGrid"
            width="100%"
            height="100%"
            fill="url(#editor-grid)"
            style="pointer-events: none"
          />
          <rect
            :x="margin"
            :y="margin"
            :width="canvasLength - margin * 2"
            :height="document.width_mm - margin * 2"
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
              :stroke="selectedId === element.id ? '#6366f1' : 'transparent'"
              stroke-width="0.2"
              @pointerdown.stop="start($event, element, 'move')"
            />
            <circle
              v-if="selectedId === element.id && element.rotation === 0"
              :cx="element.x + element.width"
              :cy="element.y + element.height"
              r="0.6"
              fill="#6366f1"
              @pointerdown.stop="start($event, element, 'size')"
            />
          </g>
        </svg>
      </div>
      <p class="help">
        {{ canvasLength }} × {{ document.width_mm }} mm · {{ margin }} mm printable-area guides ·
        {{
          rendering
            ? 'Rendering…'
            : showPrintPixels
              ? 'Device raster preview'
              : 'Smooth design preview'
        }}. Drag elements or use arrow keys; resize with the corner handle.
      </p>
      <p v-if="document.auto_length || document.out_of_bounds === 'clip'" class="help">
        Automatic length fits element boxes and margins (10–300 mm); tape width stays fixed.
        Ignoring bounds clips the print to the guides. Hidden objects remain in the layer list.
      </p>
      <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
      <p v-for="warning in preview?.warnings ?? []" :key="warning" class="alert warning">
        {{ warning }}
      </p>
      <div class="row wrap">
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
    <section class="panel form-stack">
      <h2>Element properties</h2>
      <p v-if="!selected" class="help">Add or select an element to edit it.</p>
      <template v-else>
        <div class="field-row">
          <label
            >X (mm)<input
              v-model.number="selected.x"
              type="number"
              min="0"
              step="0.5"
              @change="record" /></label
          ><label
            >Y (mm)<input
              v-model.number="selected.y"
              type="number"
              min="0"
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
        <label v-if="selected.kind === 'text' || selected.kind === 'qr'"
          >Content<textarea
            aria-label="Content"
            v-model="selected.content"
            maxlength="2000"
            rows="3"
            @change="record"
          ></textarea
          ><span class="help"
            >Bind variables using double braces, for example <code v-pre>{{ name }}</code
            >.</span
          ></label
        >
        <template v-if="selected.kind === 'image'">
          <label
            >Image<select v-model="selected.image_asset" @change="fitImageBox">
              <option :value="null" disabled>Select an uploaded image</option>
              <option
                v-for="asset in w.images.value.filter(
                  (a) => !a.archived || a.id === selected?.image_asset,
                )"
                :key="asset.id"
                :value="asset.id"
              >
                {{ asset.name }}{{ asset.archived ? ' (hidden)' : '' }}
              </option>
            </select></label
          >
          <label
            >Upload image file<input
              ref="imageInput"
              type="file"
              accept=".png,.jpg,.jpeg,.webp,.bmp,.gif,.svg"
              :disabled="w.busy.value"
              @change="chooseImageFile"
          /></label>
          <button class="secondary" :disabled="!imageFile || w.busy.value" @click="uploadImage">
            Upload and use image
          </button>
          <label class="checkbox"
            ><input
              type="checkbox"
              v-model="selected.preserve_aspect"
              @change="setPreserveAspect"
            />Preserve aspect ratio</label
          >
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
            Brightness and contrast: 1 keeps the original. Dithering represents shading with ink
            dots. The preview uses your tape colors.
          </p>
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
              Margin on each side, inside the box. Use 0 to fill to the edges, or leave blank for
              the automatic clear border. Leave clear space around the code for scanning.
            </p>
          </template>
        </template>
        <template v-if="selected.kind === 'text'"
          ><label class="checkbox"
            ><input v-model="selected.auto_width" type="checkbox" @change="record" />Fit text box
            width to content</label
          >
          <p class="help" v-if="selected.auto_width">
            Fits each value without wrapping. Combine with automatic label length for
            variable-length labels.
          </p>
          <label
            >Font<select v-model="selected.font" @change="record">
              <option>Noto Sans</option>
              <option
                v-for="font in w.fonts.value.filter((f) => !f.archived || f.id === selected?.font)"
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
          <p class="help">Font size is the maximum. Text shrinks automatically to fit its box.</p>
          <label
            >Text alignment<select v-model="selected.align" @change="record">
              <option>left</option>
              <option>center</option>
              <option>right</option>
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
          Uploaded fonts use the chosen face’s own weight. Upload a bold face to use bold text.
        </p>
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
      </template>
    </section>
  </div>
  <section class="panel">
    <div class="section-heading">
      <h2>Variable fields</h2>
      <button @click="addField">Add variable</button>
    </div>
    <p class="help">
      These fields become the submission form. Sample values are used only in the editor; defaults
      are used when submitting labels.
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
