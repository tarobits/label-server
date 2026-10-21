<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errorMessage } from '../api'
import { useAuthStore } from '../auth'
import { useWorkspaceStore } from '../workspace'
import { useResourceStore } from '../stores/resources'
import { randomUUID } from '../uuid'
import type { Preview } from '../editor'
const w = useWorkspaceStore()
const resources = useResourceStore()
const auth = useAuthStore()
const router = useRouter(),
  route = useRoute()
const { profiles, activeProfile, busy, templates } = storeToRefs(w)
const form = reactive({
  destination_id:
    typeof route.query.destination === 'string' ? route.query.destination : w.selectedPrinter,
  tape_profile:
    typeof route.query.profile === 'string'
      ? route.query.profile
      : (activeProfile.value?.id ?? profiles.value[0]?.id ?? ''),
  copies: 1,
  template:
    typeof route.query.template === 'string'
      ? route.query.template
      : (templates.value[0]?.id ?? ''),
})
watch(
  () => [form.template, form.tape_profile, form.destination_id],
  () => {
    if (route.path === '/new')
      void router.replace({
        query: {
          ...route.query,
          destination: form.destination_id,
          template: form.template || undefined,
          profile: form.tape_profile || undefined,
        },
      })
  },
)
watch(
  () => route.query,
  (query) => {
    if (typeof query.destination === 'string') form.destination_id = query.destination
    if (typeof query.template === 'string') form.template = query.template
    if (typeof query.profile === 'string') form.tape_profile = query.profile
  },
)
const data = ref<Record<string, string>>({}),
  preview = ref<Preview | null>(null),
  error = ref(''),
  rendering = ref(false),
  showPrintPixels = ref(true)
const selected = computed(() => profiles.value.find((p) => p.id === form.tape_profile))
const destination = computed(() => w.destinations.find((d) => d.id === form.destination_id))
const matchingPrinters = computed(() =>
  w.printerStatuses.filter(
    (s) =>
      destination.value?.printer_ids.includes(s.printer_id) &&
      w.cartridges.some(
        (c) => c.id === s.active_cartridge_id && c.profile_id === form.tape_profile,
      ),
  ),
)
const routingHint = computed(() => {
  if (destination.value?.available === false)
    return 'No configured printer is available. Check the destination’s printer settings.'
  if (!auth.atLeast(form.destination_id, 'print'))
    return 'Approval is required before this label enters the queue.'
  if (destination.value?.automatic_printing_held)
    return 'Automatic printing is held. Print manually or resume to print these copies.'
  if (
    destination.value?.kind === 'group' &&
    destination.value.printer_ids.some(
      (id) => !w.printerStatuses.some((state) => state.printer_id === id),
    )
  )
    return 'Labels wait for a ready group member with matching tape and enough copies to reach the threshold.'
  if (!matchingPrinters.value.length)
    return 'Waiting for this tape to be installed at the destination.'
  if (matchingPrinters.value.every((s) => s.automatic_printing_held))
    return 'Matching printers are held. Print manually or resume to print these copies.'
  return 'Tape installed. Automatic printing starts when a matching printer is ready and the threshold is reached.'
})
const template = computed(() => templates.value.find((t) => t.id === form.template))
const adaptiveText = computed(() => template.value?.id === 'text' && template.value.revision === 2)
const document = computed(() => {
  if (!template.value) return null
  const doc = JSON.parse(JSON.stringify(template.value.document)) as typeof template.value.document
  if (adaptiveText.value) {
    doc.width_mm = selected.value?.width_mm ?? 24
    if (doc.elements[0]) {
      const band = w.destinationPrinter(form.destination_id)?.capabilities?.printable_widths_mm?.[
        String(doc.width_mm)
      ]
      const side = band
        ? (doc.width_mm - band) / 2
        : Math.max(
            w.destinationPrinter(form.destination_id)?.capabilities?.printable_margin_mm ?? 1,
            Math.min(2, doc.width_mm / 4),
          )
      doc.elements[0].width = doc.length_mm - 4
      doc.elements[0].y = side
      doc.elements[0].height = doc.width_mm - 2 * side
    }
  }
  return doc
})
let timer: ReturnType<typeof setTimeout> | undefined,
  serial = 0,
  stopped = false
watch(
  () => form.template,
  () => {
    data.value = Object.fromEntries(
      (template.value?.document.fields ?? []).map((f) => [f.name, f.default]),
    )
  },
  { immediate: true },
)
async function render() {
  const ticket = ++serial
  if (destination.value?.available === false) {
    preview.value = null
    error.value = ''
    rendering.value = false
    return
  }
  if (!document.value) return
  rendering.value = true
  try {
    if (document.value.width_mm !== selected.value?.width_mm)
      throw new Error('Template and tape widths do not match.')
    const missing = document.value.fields.find(
      (field) => field.required && !(data.value[field.name] ?? field.default).trim(),
    )
    if (missing) throw new Error(`${missing.label} is required`)
    const result = await resources.preview<Preview>(
      {
        destination_id: form.destination_id,
        document: document.value,
        data: data.value,
        foreground: selected.value?.foreground ?? '#000000',
        background: selected.value?.background ?? '#ffffff',
      },
      w.destinationPrinter(form.destination_id)?.capabilities,
    )
    if (ticket === serial && !stopped) {
      preview.value = result
      error.value = ''
    }
  } catch (e) {
    if (ticket === serial && !stopped) {
      preview.value = null
      error.value = errorMessage(e)
    }
  } finally {
    if (ticket === serial) rendering.value = false
  }
}
watch(
  [document, data, selected, destination],
  () => {
    serial++
    clearTimeout(timer)
    rendering.value = true
    timer = setTimeout(render, 300)
  },
  { deep: true, immediate: true },
)
onUnmounted(() => {
  stopped = true
  serial++
  clearTimeout(timer)
})
let submissionBody = '',
  submissionKey = ''
async function submit() {
  const body = {
    destination_id: form.destination_id,
    template: form.template,
    tape_profile: form.tape_profile,
    copies: form.copies,
    data: data.value,
  }
  const signature = JSON.stringify(body)
  if (signature !== submissionBody) {
    submissionKey = randomUUID()
    submissionBody = signature
  }
  if (
    await w.action(
      () =>
        api(
          auth.atLeast(form.destination_id, 'print') ? '/jobs' : '/requests',
          'POST',
          auth.atLeast(form.destination_id, 'print') ? body : { kind: 'job', input: body },
          { 'Idempotency-Key': submissionKey },
        ),
      auth.atLeast(form.destination_id, 'print')
        ? `${form.copies} copies added to the queue.`
        : 'Label sent for approval. Nothing has been queued yet.',
    )
  ) {
    submissionBody = ''
    submissionKey = ''
    if (route.path === '/new')
      await router.push(auth.atLeast(form.destination_id, 'print') ? '/queue' : '/requests')
  }
}
</script>
<template>
  <div v-if="!profiles.length" class="panel empty">
    <h2>No tape profiles</h2>
    <p>Add a tape profile before submitting a label.</p>
    <RouterLink v-if="auth.can('inventory.manage')" class="button primary" to="/profiles"
      >Create tape profile</RouterLink
    >
    <p v-else class="help">Ask an administrator to create a tape profile.</p>
  </div>
  <div v-else-if="!templates.length" class="panel empty">
    <h2>No templates</h2>
    <RouterLink class="button primary" to="/templates/new">Open visual editor</RouterLink>
  </div>
  <div v-else class="two-column">
    <form class="panel form-stack" @submit.prevent="submit">
      <h2>Label details</h2>
      <label
        >Print destination<select v-model="form.destination_id">
          <option
            v-for="destination in w.destinations"
            :key="destination.id"
            :value="destination.id"
            :disabled="destination.available === false"
          >
            {{ destination.name }}{{ destination.kind === 'group' ? ' (Group)' : ''
            }}{{ destination.available === false ? ' — Unavailable' : '' }}
          </option>
        </select></label
      >
      <label
        >Template<select v-model="form.template">
          <option v-for="item in templates" :key="item.id" :value="item.id">
            {{ item.name }} · revision {{ item.revision }}
          </option>
        </select></label
      ><label
        >Tape profile<select v-model="form.tape_profile" required>
          <option v-for="profile in profiles" :key="profile.id" :value="profile.id">
            {{ profile.name }} · {{ profile.width_mm }} mm
          </option>
        </select></label
      ><label v-for="field in template?.document.fields" :key="field.name"
        >{{ field.label
        }}<textarea
          v-model="data[field.name]"
          :required="field.required"
          maxlength="2000"
          rows="2"
        ></textarea>
      </label>
      <div class="field-row">
        <label
          >Copies<input v-model.number="form.copies" type="number" min="1" max="1000" required
        /></label>
      </div>
      <p class="help">{{ routingHint }}</p>
      <button
        class="primary"
        :disabled="
          busy ||
          rendering ||
          !!error ||
          !preview ||
          preview.printable === false ||
          destination?.available === false ||
          !auth.atLeast(form.destination_id, 'request')
        "
        type="submit"
      >
        {{ auth.atLeast(form.destination_id, 'print') ? 'Add to queue' : 'Request printing' }}
      </button>
    </form>
    <section class="panel preview-panel">
      <div class="section-heading">
        <h2>Print preview</h2>
        <span class="badge">{{ showPrintPixels ? '1-bit raster' : 'Smooth design' }}</span>
      </div>
      <label class="checkbox"
        ><input v-model="showPrintPixels" type="checkbox" />Show print pixels</label
      >
      <div class="label-stage">
        <img
          v-if="preview"
          class="raster-preview"
          :src="showPrintPixels ? preview.png : preview.design_png"
          :style="{
            imageRendering: showPrintPixels ? 'pixelated' : 'auto',
            aspectRatio: `${preview.length_mm} / ${preview.width_mm}`,
          }"
          alt="Rendered label preview"
        />
        <p v-else class="help">
          {{ rendering ? 'Rendering…' : 'Enter valid label values to preview.' }}
        </p>
        <span
          >{{ selected?.width_mm }} mm tape ·
          {{ preview?.length_mm ?? template?.document.length_mm }} mm label</span
        >
      </div>
      <p v-if="error" class="inline-warning">{{ error }}</p>
      <p v-for="warning in preview?.warnings ?? []" :key="warning" class="alert warning">
        {{ warning }}
      </p>
    </section>
  </div>
</template>
