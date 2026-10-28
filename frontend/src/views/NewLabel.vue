<script setup lang="ts">
import { vValidateForm, apiFieldErrors, focusFormErrors, type FieldErrors } from '../formValidation'
import { storeToRefs } from 'pinia'
import { computed, nextTick, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errorMessage } from '../api'
import { useAuthStore } from '../auth'
import { useWorkspaceStore } from '../workspace'
import { useResourceStore } from '../stores/resources'
import { randomUUID } from '../uuid'
import type { Preview } from '../editor'
import ProcessNameInput from '../components/ProcessNameInput.vue'
import PrintPlanNotice from '../components/PrintPlanNotice.vue'
import CostEstimate from '../components/CostEstimate.vue'
import { decodeLabel } from '../labelPreview'
import { templateLength } from '../templateDimensions'
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
const template = computed(() => templates.value.find((t) => t.id === form.template))
const processName = ref('')
watch(
  () => form.template,
  (_, previous) => {
    if (previous === undefined && typeof route.query.profile === 'string') return
    const profile = profiles.value.find((p) => p.id === template.value?.document.preview_tape?.id)
    if (profile) form.tape_profile = profile.id
  },
  { immediate: true, flush: 'sync' },
)
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
const labelForm = ref<HTMLFormElement | null>(null)
const previewPanel = ref<HTMLElement | null>(null)
const previewSpace = ref(600)
const previewImageSpace = ref(300)
watch(
  previewPanel,
  (panel, _, cleanup) => {
    if (!panel) return
    function fitPreview() {
      if (!panel) return
      const viewportHeight = window.visualViewport?.height ?? window.innerHeight
      // Stacked mobile panels use a full screen once scrolled into view.
      const top = window.matchMedia('(min-width: 851px)').matches
        ? Math.max(24, panel.getBoundingClientRect().top)
        : 24
      const space = Math.max(160, viewportHeight - top - 24)
      previewSpace.value = space
      const image = panel.querySelector<HTMLImageElement>('.raster-preview')
      const overhead = panel.scrollHeight - (image?.getBoundingClientRect().height ?? 0)
      previewImageSpace.value = Math.max(40, Math.min(viewportHeight * 0.36, space - overhead - 2))
    }
    const observer = new ResizeObserver(fitPreview)
    observer.observe(panel)
    panel
      .querySelectorAll('.preview-feedback, .label-stage')
      .forEach((element) => observer.observe(element))
    if (panel.closest('main')) observer.observe(panel.closest('main')!)
    window.addEventListener('resize', fitPreview)
    window.addEventListener('scroll', fitPreview, { passive: true })
    window.visualViewport?.addEventListener('resize', fitPreview)
    fitPreview()
    cleanup(() => {
      observer.disconnect()
      window.removeEventListener('resize', fitPreview)
      window.removeEventListener('scroll', fitPreview)
      window.visualViewport?.removeEventListener('resize', fitPreview)
    })
  },
  { flush: 'post' },
)
const previewFieldErrors = ref<FieldErrors>({})
const submissionFieldErrors = ref<FieldErrors>({})
const fieldErrors = computed(() => ({
  ...previewFieldErrors.value,
  ...submissionFieldErrors.value,
}))
function clearSubmissionError(event: Event) {
  const name = (event.target as HTMLInputElement).name
  if (!(name in submissionFieldErrors.value)) return
  const errors = { ...submissionFieldErrors.value }
  delete errors[name]
  submissionFieldErrors.value = errors
}
const selected = computed(() => profiles.value.find((p) => p.id === form.tape_profile))
const destination = computed(() => w.destinations.find((d) => d.id === form.destination_id))
const planningConfig = computed(() =>
  w.printers
    .filter((printer) => destination.value?.printer_ids.includes(printer.id))
    .map((printer) => printer.config),
)
const pricingConfig = computed(() => ({
  cartridges: w.cartridges.map((c) => [
    c.id,
    c.profile_id,
    c.price_minor,
    c.currency,
    c.nominal_length_mm,
    c.remaining_mm,
    c.installed,
  ]),
  mounted: w.printerStatuses.map((p) => [p.printer_id, p.active_cartridge_id]),
}))
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
    const errors: FieldErrors = {}
    if (document.value.width_mm !== selected.value?.width_mm)
      errors.tape_profile = 'Template and tape widths do not match.'
    const missing = document.value.fields.filter(
      (field) => field.required && !(data.value[field.name] ?? field.default).trim(),
    )
    for (const field of missing) errors[`data.${field.name}`] = `${field.label} is required`
    previewFieldErrors.value = errors
    if (Object.keys(errors).length) {
      preview.value = null
      error.value = ''
      return
    }
    const result = await resources.preview<Preview>(
      {
        destination_id: form.destination_id,
        tape_profile: form.tape_profile,
        copies: form.copies,
        document: document.value,
        data: data.value,
        foreground: selected.value?.foreground ?? '#000000',
        background: selected.value?.background ?? '#ffffff',
      },
      {
        capabilities: w.destinationPrinter(form.destination_id)?.capabilities,
        config: planningConfig.value,
        pricing: pricingConfig.value,
      },
    )
    if (ticket !== serial || stopped) return
    await decodeLabel(result)
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
let initialRender = true
watch(
  [document, data, selected, destination, planningConfig, pricingConfig, () => form.copies],
  () => {
    serial++
    previewFieldErrors.value = {}
    clearTimeout(timer)
    rendering.value = true
    timer = setTimeout(render, initialRender ? 0 : 300)
    initialRender = false
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
  let fieldErrorsHandled = false
  const body = {
    process_name: processName.value.trim(),
    destination_id: form.destination_id,
    template: form.template,
    tape_profile: form.tape_profile,
    copies: form.copies,
    data: data.value,
  }
  const signature = JSON.stringify(body)
  const direct = auth.atLeast(body.destination_id, 'print')
  if (signature !== submissionBody) {
    submissionKey = randomUUID()
    submissionBody = signature
  }
  if (
    await w.action(
      () =>
        api(direct ? '/jobs' : '/requests', 'POST', direct ? body : { kind: 'job', input: body }, {
          'Idempotency-Key': submissionKey,
        }).catch(async (issue: unknown) => {
          const errors = apiFieldErrors(issue, direct ? ['body'] : ['body', 'job', 'input'])
          const entries = Object.entries(errors)
          submissionFieldErrors.value = Object.fromEntries(
            entries.filter(([name]) => labelForm.value?.elements.namedItem(name)),
          )
          fieldErrorsHandled =
            entries.length > 0 && entries.length === Object.keys(submissionFieldErrors.value).length
          await nextTick()
          focusFormErrors(labelForm.value)
          throw issue
        }),
      direct
        ? `${body.copies} ${body.copies === 1 ? 'copy' : 'copies'} added to the queue.`
        : 'Label sent for approval. Nothing has been queued yet.',
    )
  ) {
    submissionBody = ''
    submissionKey = ''
    if (route.path === '/new') await router.push(direct ? '/queue' : '/requests')
  } else if (fieldErrorsHandled) w.actionError = ''
}
</script>
<template>
  <div v-if="!profiles.length" class="panel empty">
    <h2>No tape profiles</h2>
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
    <form
      ref="labelForm"
      v-validate-form="fieldErrors"
      class="panel form-stack"
      @input="clearSubmissionError"
      @change="clearSubmissionError"
      @submit.prevent="submit"
    >
      <h2>Label details</h2>
      <label
        >Print destination<select v-model="form.destination_id" name="destination_id">
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
        >Template<select v-model="form.template" name="template">
          <option v-for="item in templates" :key="item.id" :value="item.id">
            {{ item.name }} · revision {{ item.revision }}
          </option>
        </select></label
      >
      <ProcessNameInput v-model="processName" :template-name="template?.name ?? ''" />
      <label
        >Tape profile<select v-model="form.tape_profile" name="tape_profile" required>
          <option v-for="profile in profiles" :key="profile.id" :value="profile.id">
            {{ profile.name }} · {{ profile.width_mm }} mm
          </option>
        </select></label
      ><label v-for="field in template?.document.fields" :key="field.name"
        >{{ field.label
        }}<textarea
          v-model="data[field.name]"
          :name="`data.${field.name}`"
          :required="field.required"
          maxlength="2000"
          rows="2"
        ></textarea>
      </label>
      <div class="field-row">
        <label
          >Copies<input
            v-model.number="form.copies"
            name="copies"
            type="number"
            min="1"
            max="1000"
            required
        /></label>
      </div>
      <CostEstimate :estimate="preview?.cost_estimate" :pending="rendering && !error" />
      <p class="help">{{ routingHint }}</p>
      <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
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
    <section
      ref="previewPanel"
      class="panel preview-panel"
      :style="{
        '--preview-space': `${previewSpace}px`,
        '--preview-image-space': `${previewImageSpace}px`,
      }"
    >
      <div class="section-heading">
        <h2>Print preview</h2>
        <span class="badge">{{ showPrintPixels ? '1-bit raster' : 'Smooth design' }}</span>
      </div>
      <label class="checkbox"
        ><input v-model="showPrintPixels" type="checkbox" />Show print pixels</label
      >
      <div class="preview-feedback">
        <TransitionGroup name="notice">
          <p
            v-for="warning in preview?.warnings ?? []"
            :key="warning"
            class="alert warning"
            role="status"
          >
            {{ warning }}
          </p>
        </TransitionGroup>
        <PrintPlanNotice :plan="preview?.print_plan" :copies="form.copies" />
      </div>
      <div class="label-stage">
        <img
          v-if="preview"
          class="raster-preview"
          :src="showPrintPixels ? preview.png : preview.design_png"
          :style="{
            imageRendering: showPrintPixels ? 'pixelated' : 'auto',
            aspectRatio: `${preview.length_mm} / ${preview.width_mm}`,
            '--label-aspect': preview.length_mm / preview.width_mm,
          }"
          alt="Rendered label preview"
        />
        <p v-else-if="rendering" class="help">Rendering…</p>
        <span
          >{{ selected?.width_mm }} mm tape ·
          <template v-if="preview">{{ preview.length_mm }} mm label</template>
          <template v-else-if="template">{{ templateLength(template) }}</template></span
        >
      </div>
    </section>
  </div>
</template>

<style scoped>
.preview-panel {
  position: sticky;
  top: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-height: var(--preview-space);
  overflow: auto;
}
.preview-panel > *,
.preview-feedback > :deep(*) {
  flex-shrink: 0;
  margin-block: 0;
}
.preview-feedback {
  display: grid;
  gap: 12px;
}
.preview-feedback:empty {
  display: none;
}
.label-stage {
  min-height: 0;
}
.raster-preview {
  width: min(100%, calc(var(--preview-image-space) * var(--label-aspect)));
  height: auto;
}
</style>
