<script setup lang="ts">
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errorMessage } from '../api'
import { workspace as w } from '../workspace'
import type { Preview } from '../editor'
const router = useRouter(),
  route = useRoute()
const { profiles, activeProfile, busy, templates } = w
const form = reactive({
  tape_profile: activeProfile.value?.id ?? profiles.value[0]?.id ?? '',
  copies: 1,
  template:
    typeof route.query.template === 'string'
      ? route.query.template
      : (templates.value[0]?.id ?? ''),
})
const data = ref<Record<string, string>>({}),
  preview = ref<Preview | null>(null),
  error = ref(''),
  rendering = ref(false),
  showPrintPixels = ref(false)
const selected = computed(() => profiles.value.find((p) => p.id === form.tape_profile))
const template = computed(() => templates.value.find((t) => t.id === form.template))
const adaptiveText = computed(() => template.value?.id === 'text' && template.value.revision === 2)
const document = computed(() => {
  if (!template.value) return null
  const doc = JSON.parse(JSON.stringify(template.value.document)) as typeof template.value.document
  if (adaptiveText.value) {
    doc.width_mm = selected.value?.width_mm ?? 24
    if (doc.elements[0]) {
      doc.elements[0].width = doc.length_mm - 4
      doc.elements[0].height = doc.width_mm - 4
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
  if (!document.value) return
  rendering.value = true
  try {
    if (document.value.width_mm !== selected.value?.width_mm)
      throw new Error('Template and tape widths do not match.')
    const result = await api<Preview>('/preview', 'POST', {
      document: document.value,
      data: data.value,
      foreground: selected.value?.foreground ?? '#000000',
      background: selected.value?.background ?? '#ffffff',
    })
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
  [document, data, selected],
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
async function submit() {
  if (
    await w.action(
      () =>
        api('/jobs', 'POST', {
          template: form.template,
          tape_profile: form.tape_profile,
          copies: form.copies,
          data: data.value,
        }),
      `${form.copies} copies added to the queue.`,
    )
  )
    await router.push('/queue')
}
</script>
<template>
  <div v-if="!profiles.length" class="panel empty">
    <h2>First, choose your tape.</h2>
    <p>Add a tape profile before submitting a label.</p>
    <RouterLink class="button primary" to="/profiles">Create tape profile</RouterLink>
  </div>
  <div v-else-if="!templates.length" class="panel empty">
    <h2>Create your first template.</h2>
    <RouterLink class="button primary" to="/templates/new">Open visual editor</RouterLink>
  </div>
  <div v-else class="two-column">
    <form class="panel form-stack" @submit.prevent="submit">
      <h2>Label details</h2>
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
      <p class="help">
        {{
          w.status.value?.automatic_printing_held
            ? 'Automatic printing is held. These copies will wait for a manual flush or resume.'
            : selected?.id === activeProfile?.id
              ? 'This tape is installed. An eligible batch can print automatically.'
              : 'This label will wait until its tape is installed.'
        }}
      </p>
      <button class="primary" :disabled="busy || rendering || !!error || !preview" type="submit">
        Add to queue
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
          :style="{ imageRendering: showPrintPixels ? 'pixelated' : 'auto' }"
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
      <div class="note">
        <strong>Design and print views share the same layout.</strong>
        <p>
          The smooth view renders the design at higher resolution. Enable Show print pixels to
          inspect the actual monochrome raster. Physical print quality still needs verification on
          the Brother printer.
        </p>
      </div>
    </section>
  </div>
</template>
