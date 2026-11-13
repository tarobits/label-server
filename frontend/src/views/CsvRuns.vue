<script setup lang="ts">
import { t } from '../shared/i18n'
import { confirmAction } from '../shared/confirmation'
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ApiError, errorMessage } from '../shared/api'
import { useAuthStore } from '../auth/auth'
import { useWorkspaceStore, date } from '../shared/workspace'
import { useLiveRefresh } from '../shared/live'
import { useResourceStore } from '../stores/resources'
import { randomUUID } from '../shared/uuid'
import ProcessNameInput from '../components/ProcessNameInput.vue'
import BillingPicker, { type BillingSelection } from '../components/BillingPicker.vue'
import PrintPlanNotice from '../components/PrintPlanNotice.vue'
import type { CostEstimate as CostEstimateData, PrintPlan, Template } from '../shared/types'
import TapeUsage from '../components/TapeUsage.vue'
import CostEstimate from '../components/CostEstimate.vue'
import AnimatedDetails from '../components/AnimatedDetails.vue'
import ExpandableContent from '../components/ExpandableContent.vue'
import ImageValueInput from '../components/ImageValueInput.vue'
import TemplatePicker from '../components/TemplatePicker.vue'
import TapeProfilePicker from '../components/TapeProfilePicker.vue'
import type { ImageValue, VariableValue } from '../templates/editor'
import { displayValue } from '../templates/variableInputs'
import { compatibleProfile } from '../printing/media'
interface Row {
  source_row: number
  values: string[]
  selected: boolean
  notify_on_completion: boolean
  copies: number
  maximum: string
  currency: string
}
interface Run {
  cost_estimate?: CostEstimateData | null
  destination_id: string
  id: string
  name: string
  process_name: string
  submitted_at: number | null
  created_at: number
  template_name: string
  template_revision: number
  copies: number
  label_length_mm: number
  estimated_mm: number
  print_plan?: PrintPlan | null
  warnings?: string[]
  rows: {
    cost_estimate?: CostEstimateData | null
    maximum_price?: { currency: string; micros: number } | null
    source_row: number
    copies: number
    length_mm: number
    width_mm: number
    payload: Record<string, VariableValue>
  }[]
}
interface Preview {
  png: string
  design_png: string
  warnings: string[]
  length_mm: number
  width_mm: number
}
const w = useWorkspaceStore()
const auth = useAuthStore()
const route = useRoute(),
  router = useRouter(),
  resources = useResourceStore()
const destinationId = ref(
  typeof route.query.destination === 'string' ? route.query.destination : w.selectedPrinter,
)
const availableProfileId = (id: string) =>
  w.profiles.find((profile) => profile.id === id && profile.available !== false)?.id ?? ''
const csv = ref(''),
  delimiter = ref(','),
  name = ref(t('remainingUi.cSVLabels')),
  templateId = ref(typeof route.query.template === 'string' ? route.query.template : ''),
  profileId = ref(
    typeof route.query.profile === 'string'
      ? availableProfileId(route.query.profile)
      : w.activeProfile?.available === false
        ? ''
        : (w.defaultProfile?.id ?? ''),
  )
const template = computed(() => w.templates.find((t) => t.id === templateId.value))
const processName = ref('')
const billing = ref<BillingSelection | null>(null)
watch(
  templateId,
  (_, previous) => {
    if (previous === undefined && typeof route.query.profile === 'string') return
    const profile = w.profiles.find((p) => p.id === template.value?.document.preview_tape?.id)
    if (template.value?.document.preview_tape?.id)
      profileId.value = profile?.available !== false && profile ? profile.id : ''
  },
  { immediate: true, flush: 'sync' },
)
watch([templateId, profileId, destinationId], () => {
  if (route.path === '/runs')
    void router.replace({
      query: {
        ...route.query,
        destination: destinationId.value,
        template: templateId.value || undefined,
        profile: profileId.value || undefined,
      },
    })
})
watch(
  () => route.query,
  (query) => {
    if (!route.params.id) {
      if (typeof query.destination === 'string') destinationId.value = query.destination
      if (typeof query.template === 'string') templateId.value = query.template
      if (typeof query.profile === 'string') profileId.value = availableProfileId(query.profile)
    } else if (run.value) position.value = rowPosition()
  },
)
const headers = ref<string[]>([]),
  rows = ref<Row[]>([]),
  mapping = ref<Record<string, string>>({}),
  parsedText = ref(''),
  parsedDelimiter = ref(',')
const error = ref(''),
  busy = ref(false),
  rowErrors = ref<{ source_row: number; message: string }[]>([]),
  runs = ref<Run[]>([]),
  run = ref<Run | null>(null),
  position = ref(0),
  preview = ref<Preview | null>(null),
  pixels = ref(true)
const destination = computed(() =>
  w.destinations.find((d) => d.id === (run.value?.destination_id ?? destinationId.value)),
)
const templateCompatible = (item: Template) =>
  w.profiles.some(
    (profile) =>
      profile.available !== false &&
      w.printers.some(
        (printer) =>
          destination.value?.printer_ids.includes(printer.id) &&
          compatibleProfile(
            profile,
            printer.capabilities ?? undefined,
            item.id === 'text' && item.revision === 2
              ? { ...item.document, width_mm: profile.width_mm }
              : item.document,
          ),
      ),
  )
const selected = computed(() => rows.value.filter((r) => r.selected))
const imageChoices = ref(new Map<string, ImageValue | null>())
const imageCells = computed(() =>
  (template.value?.document.fields ?? [])
    .filter((field) => field.type === 'image')
    .flatMap((field) => {
      const column = headers.value.indexOf(mapping.value[field.name] ?? '')
      if (column < 0) return []
      return [
        ...new Set(
          selected.value.map((row) => row.values[column] ?? '').filter((value) => value.trim()),
        ),
      ].map((value) => ({ field, value, key: JSON.stringify([field.name, value]) }))
    }),
)
const imageMapping = computed(() =>
  Object.fromEntries(
    (template.value?.document.fields ?? [])
      .filter((field) => field.type === 'image')
      .map((field) => [
        field.name,
        Object.fromEntries(
          imageCells.value
            .filter((cell) => cell.field.name === field.name && imageChoices.value.get(cell.key))
            .map((cell) => [cell.value, imageChoices.value.get(cell.key)]),
        ),
      ])
      .filter(([, values]) => Object.keys(values!).length),
  ),
)
let previewTicket = 0,
  generation = 0,
  stopped = false,
  previewPath = '',
  keyBody = '',
  requestKey = ''
watch([csv, delimiter], () => {
  imageChoices.value.clear()
  headers.value = []
  rows.value = []
  rowErrors.value = []
})
watch(templateId, () => {
  imageChoices.value.clear()
  mapping.value = {}
  rowErrors.value = []
})
async function perform(task: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await task()
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}
async function fileChanged(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  await perform(async () => {
    if (file.size > 1_000_000) throw new Error(t('remainingUi.cSVMustNotExceed1MB'))
    csv.value = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer())
    name.value = file.name.slice(0, 100)
  })
}
async function parse() {
  await perform(async () => {
    const result = await api<{
      headers: string[]
      rows: { source_row: number; values: string[] }[]
    }>('/csv/parse', 'POST', { csv_text: csv.value, delimiter: delimiter.value })
    headers.value = result.headers
    rows.value = result.rows.map((r) => ({
      ...r,
      selected: true,
      copies: 1,
      maximum: '',
      currency: 'EUR',
      notify_on_completion: true,
    }))
    parsedText.value = csv.value
    parsedDelimiter.value = delimiter.value
    mapping.value = Object.fromEntries(
      (template.value?.document.fields ?? [])
        .filter((f) => result.headers.includes(f.name))
        .map((f) => [f.name, f.name]),
    )
  })
}
function move(index: number, delta: number) {
  const target = index + delta
  if (target < 0 || target >= rows.value.length) return
  const [row] = rows.value.splice(index, 1)
  rows.value.splice(target, 0, row!)
}
async function prepare() {
  await perform(async () => {
    if (!template.value) throw new Error(t('uiMessages.chooseATemplateMessage'))
    if (!processName.value.trim()) throw new Error(t('uiMessages.processNameIsRequired'))
    rowErrors.value = []
    const body = {
      process_name: processName.value.trim(),
      billing: billing.value,
      destination_id: destinationId.value,
      name: name.value,
      template: templateId.value,
      expected_revision: template.value.revision,
      tape_profile: profileId.value,
      csv_text: parsedText.value,
      delimiter: parsedDelimiter.value,
      image_mapping: imageMapping.value,
      mapping: Object.fromEntries(Object.entries(mapping.value).filter(([, v]) => v)),
      rows: selected.value.map((r) => ({
        source_row: r.source_row,
        copies: r.copies,
        maximum_price:
          r.maximum === ''
            ? null
            : {
                currency: r.currency.toUpperCase(),
                micros: Math.round(Number(r.maximum) * 1000000),
              },
        notify_on_completion: r.notify_on_completion,
      })),
    }
    const signature = JSON.stringify(body)
    if (keyBody !== signature) {
      requestKey = randomUUID()
      keyBody = signature
    }
    const result = await api<{ valid: boolean; run: Run | null; errors: typeof rowErrors.value }>(
      '/runs/prepare',
      'POST',
      { ...body, request_key: requestKey },
    )
    rowErrors.value = result.errors
    if (result.run) {
      resources.invalidate(['/runs'])
      await router.push(`/runs/${result.run.id}`)
    }
  })
}
async function load(force = false) {
  const ticket = ++generation,
    actor = auth.user?.id,
    id = typeof route.params.id === 'string' ? route.params.id : ''
  const current = () => !stopped && ticket === generation && auth.user?.id === actor
  try {
    if (id) {
      const detail = await resources.get<Run>(`/runs/${encodeURIComponent(id)}`, {
        ttl: 60000,
        force,
      })
      if (!current() || detail.id !== route.params.id) return
      if (JSON.stringify(run.value) !== JSON.stringify(detail)) run.value = detail
      position.value = rowPosition()
      if (!preview.value || force) await loadPreview(force)
    } else {
      const data = await resources.get<Run[]>('/runs', { ttl: 60000, force })
      if (!current()) return
      if (JSON.stringify(runs.value) !== JSON.stringify(data)) runs.value = data
    }
    if (current()) error.value = ''
  } catch (e) {
    if (current()) error.value = errorMessage(e)
  }
}
async function loadPreview(force = false) {
  const ticket = ++previewTicket,
    actor = auth.user?.id
  if (!run.value) return
  const id = run.value.id,
    row = position.value,
    path = `/runs/${encodeURIComponent(id)}/rows/${row}/preview`
  if (path !== previewPath) preview.value = null
  previewPath = path
  const current = () =>
    !stopped &&
    ticket === previewTicket &&
    auth.user?.id === actor &&
    route.params.id === id &&
    position.value === row
  try {
    const result = await resources.get<Preview>(path, { ttl: 60000, force })
    if (current() && JSON.stringify(preview.value) !== JSON.stringify(result))
      preview.value = result
  } catch (e) {
    if (current()) error.value = errorMessage(e)
  }
}
async function deleteDraft(item: Run) {
  if (!(await confirmAction(t('uiDetails.deleteDraft', { value1: String(item.name) })))) return
  await perform(async () => {
    await api(`/runs/${item.id}`, 'DELETE')
    resources.invalidate(['/runs'])
    if (route.params.id === item.id) await router.push('/runs')
    else await load(true)
  })
}
async function submit() {
  if (!run.value) return
  const id = run.value.id
  await perform(async () => {
    if (!auth.printer(run.value!.destination_id, 'submit_directly')) {
      await api('/requests', 'POST', { kind: 'run', run_id: id })
      resources.invalidate(['/requests'])
      await router.push('/requests')
      return
    }
    let result: { run: Run }
    try {
      result = await api<{ run: Run }>(`/runs/${id}/submit`, 'POST')
    } catch (failure) {
      const detail = failure instanceof ApiError ? failure.detail : null
      if (
        !(failure instanceof ApiError) ||
        failure.status !== 409 ||
        !detail ||
        typeof detail !== 'object' ||
        !('code' in detail) ||
        detail.code !== 'owner_access_discrepancy' ||
        !('override_allowed' in detail) ||
        detail.override_allowed !== true ||
        !auth.user?.is_admin
      )
        throw failure
      if (!(await confirmAction(t('uiDetails.overrideRun', { value1: String(failure.message) }))))
        return
      result = await api<{ run: Run }>(`/runs/${id}/submit`, 'POST', {
        authorization_override: true,
      })
    }
    run.value = result.run
    resources.invalidate(['/runs'])
    await load(true)
    await w.refresh()
  })
}
function rowPosition() {
  const row = Number(route.query.row ?? 1)
  return Number.isInteger(row) && row >= 1 && row <= (run.value?.rows.length ?? 0) ? row - 1 : 0
}
watch(position, () => {
  if (run.value) void router.replace({ query: { ...route.query, row: String(position.value + 1) } })
  void loadPreview()
})
watch(
  () => route.params.id,
  () => {
    generation++
    previewTicket++
    run.value = null
    preview.value = null
    previewPath = ''
    error.value = ''
    void load()
  },
)
useLiveRefresh(async () => {
  if (!run.value || !run.value.submitted_at) await load()
}, 60000)
onUnmounted(() => {
  stopped = true
  generation++
  previewTicket++
})
</script>
<template>
  <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
  <template v-if="!route.params.id">
    <p v-if="!w.destinations.length" class="panel help">
      {{ $t('common.yourSavedRunsRemainAvailableARoleWithDestination') }}
    </p>
    <fieldset
      v-if="w.destinations.length"
      :disabled="busy || w.busy"
      class="panel form-stack csv-form"
    >
      <h2>{{ $t('csvRuns.importCsv') }}</h2>
      <label
        >{{ $t('common.printDestination')
        }}<select v-model="destinationId">
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
      <p v-if="destination?.available === false" class="help">
        {{ $t('common.thisDestinationHasNoConfiguredPrinterAvailableUpdateIts') }}
      </p>
      <TemplatePicker
        v-model="templateId"
        :templates="w.templates"
        :compatible="templateCompatible"
      />
      <TapeProfilePicker
        v-model="profileId"
        :profiles="w.profiles"
        :disabled="busy || w.busy"
        :compatible="
          (p) =>
            compatibleProfile(
              p,
              w.destinationPrinter(destinationId)?.capabilities,
              template?.id === 'text' ? undefined : template?.document,
            )
        "
      />
      <label>{{ $t('csvRuns.runName') }}<input v-model="name" maxlength="100" /></label>
      <ProcessNameInput v-model="processName" :template-name="template?.name ?? ''" />
      <BillingPicker v-model="billing" />
      <label
        >{{ $t('csvRuns.csvFile')
        }}<input type="file" accept=".csv,text/csv,text/plain" @change="fileChanged"
      /></label>
      <label
        >{{ $t('csvRuns.csvContent')
        }}<textarea v-model="csv" rows="6" placeholder="text,location&#10;Network cable,Office" />
      </label>
      <label
        >{{ $t('csvRuns.delimiter')
        }}<select v-model="delimiter">
          <option value=",">{{ $t('csvRuns.comma') }}</option>
          <option value=";">{{ $t('common.semicolon') }}</option>
          <option :value="'\t'">{{ $t('common.tab') }}</option>
        </select></label
      >
      <p class="help">
        {{ $t('common.utf8CsvWithAHeaderUpTo250') }}
      </p>
      <button :disabled="!csv || !templateId || !profileId" @click="parse">
        {{ $t('csvRuns.readCsv') }}
      </button>
      <template v-if="headers.length">
        <h2>{{ $t('csvRuns.mapColumns') }}</h2>
        <div class="field-row">
          <label v-for="field in template?.document.fields" :key="field.name"
            >{{ field.label
            }}<select v-model="mapping[field.name]">
              <option value="">{{ $t('common.useFieldDefault') }}</option>
              <option v-for="header in headers" :key="header" :value="header">{{ header }}</option>
            </select></label
          >
        </div>
        <ExpandableContent :open="imageCells.length > 0">
          <div class="form-stack">
            <h2>{{ $t('csvRuns.mapImages') }}</h2>
            <ImageValueInput
              v-for="cell in imageCells"
              :key="`${templateId}:${cell.key}`"
              :model-value="imageChoices.get(cell.key) ?? null"
              :label="`${cell.field.label}: ${cell.value}`"
              @update:model-value="imageChoices.set(cell.key, $event)"
            />
          </div>
        </ExpandableContent>
        <p class="help">{{ $t('csvRuns.rowOrderBelowIsPrintOrder') }}</p>
        <div class="row wrap">
          <button @click="rows.forEach((r) => (r.selected = true))">
            {{ $t('common.selectAll') }}</button
          ><button @click="rows.forEach((r) => (r.selected = false))">
            {{ $t('common.selectNone') }}</button
          ><span
            >{{ selected.length }} {{ $t('common.records') }}
            {{ selected.reduce((n, r) => n + r.copies, 0) }}
            {{ $t('common.copiesMaximum1000') }}</span
          >
        </div>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>{{ $t('common.use') }}</th>
                <th>{{ $t('common.record') }}</th>
                <th>{{ $t('common.maximumTotalPrice') }}</th>
                <th>{{ $t('common.values') }}</th>
                <th>{{ $t('common.copies') }}</th>
                <th>{{ $t('common.notifyWhenPrinted') }}</th>
                <th>{{ $t('csvRuns.order') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, index) in rows" :key="row.source_row">
                <td>
                  <label class="checkbox-target"
                    ><input
                      v-model="row.selected"
                      type="checkbox"
                      :aria-label="
                        $t('uiDetails.selectRecord', { value1: String(row.source_row) })
                      "
                  /></label>
                </td>
                <td>{{ row.source_row }}</td>
                <td>
                  <input
                    v-model="row.maximum"
                    type="number"
                    min="0"
                    step="0.01"
                    :placeholder="$t('common.noMaximum')"
                    :aria-label="$t('uiDetails.recordMaximum', { value1: String(row.source_row) })"
                  /><input
                    v-model="row.currency"
                    maxlength="3"
                    :aria-label="$t('uiDetails.recordCurrency', { value1: String(row.source_row) })"
                  />
                </td>
                <td class="csv-values">{{ row.values.join(' · ') }}</td>
                <td>
                  <input
                    v-model.number="row.copies"
                    type="number"
                    min="1"
                    max="1000"
                    :aria-label="$t('uiDetails.recordCopies', { value1: String(row.source_row) })"
                  />
                </td>
                <td>
                  <label class="checkbox-target"
                    ><input
                      v-model="row.notify_on_completion"
                      type="checkbox"
                      :aria-label="
                        $t('uiDetails.recordNotification', { value1: String(row.source_row) })
                      "
                  /></label>
                </td>
                <td>
                  <div class="row">
                    <button
                      :disabled="index === 0"
                      :aria-label="$t('uiDetails.moveRecordUp', { value1: String(row.source_row) })"
                      @click="move(index, -1)"
                    >
                      ↑</button
                    ><button
                      :disabled="index === rows.length - 1"
                      :aria-label="
                        $t('uiDetails.moveRecordDown', { value1: String(row.source_row) })
                      "
                      @click="move(index, 1)"
                    >
                      ↓
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-for="issue in rowErrors" :key="issue.source_row" class="alert danger" role="alert">
          {{ $t('common.record') }} {{ issue.source_row }}: {{ issue.message }}
        </p>
        <button
          class="primary"
          :disabled="
            !selected.length ||
            destination?.available === false ||
            !profileId ||
            w.profiles.find((p) => p.id === profileId)?.available === false
          "
          @click="prepare"
        >
          {{ $t('common.validateAndPreviewRun') }}
        </button>
        <p class="help">{{ $t('common.thisSavesADraftForReviewNothingIsQueued') }}</p>
      </template>
    </fieldset>
    <section class="panel">
      <h2>{{ $t('csvRuns.recentRuns') }}</h2>
      <p v-if="!runs.length" class="help">{{ $t('csvRuns.noSavedRunsYet') }}</p>
      <div v-for="item in runs" :key="item.id" class="section-heading">
        <RouterLink :to="`/runs/${item.id}`">{{ item.name }}</RouterLink
        ><span
          >{{ item.submitted_at ? $t('uiMessages.submitted') : $t('uiMessages.draft') }} ·
          {{ date(item.created_at) }}</span
        >
        <button
          v-if="!item.submitted_at"
          class="text-button danger-text"
          :disabled="busy"
          @click="deleteDraft(item)"
        >
          {{ $t('csvRuns.deleteDraft') }}
        </button>
      </div>
    </section>
  </template>
  <template v-else-if="run">
    <section class="panel form-stack">
      <div class="section-heading">
        <h2>{{ run.name }}</h2>
        <RouterLink to="/runs">{{ $t('csvRuns.importAnotherCsv') }}</RouterLink>
      </div>
      <p>
        {{ run.template_name }} {{ $t('common.revision2') }} {{ run.template_revision }} ·
        {{ run.rows.length }} {{ $t('common.records') }} {{ run.copies }} {{ $t('common.copies2') }}
      </p>
      <p>
        {{ $t('csvRuns.labels') }} {{ run.label_length_mm.toFixed(2) }}
        {{ $t('common.mmEstimatedTape') }} {{ run.estimated_mm.toFixed(2) }}
        {{ $t('common.mmAsOneBatchActualUseDependsOnFeed') }}
      </p>
      <CostEstimate v-if="!run.submitted_at" :estimate="run.cost_estimate" />
      <p v-if="run.rows.some((row) => row.maximum_price)" class="muted">
        {{ $t('csvRuns.eachRowSMaximumCoversItsCopiesAndTape') }}
      </p>
      <div v-if="run.print_plan" class="inset">
        <strong>{{ $t('csvRuns.plannedTapeSequence') }}</strong>
        <p v-for="warning in run.warnings ?? []" :key="warning" class="alert warning" role="status">
          {{ warning }}
        </p>
        <PrintPlanNotice :plan="run.print_plan" />
        <AnimatedDetails>
          <template #summary>{{ $t('common.tapeDetails') }}</template>
          <TapeUsage :plan="run.print_plan" caption="Saved estimate for this draft" />
        </AnimatedDetails>
        <p>
          {{ run.print_plan.leader_mm.toFixed(1) }} {{ $t('common.mmBatchOverhead') }}
          {{ run.print_plan.feed_per_label_mm.toFixed(1) }} {{ $t('common.mmFeedPerLabel') }}
          {{
            run.print_plan.cut_each
              ? $t('uiMessages.cutAfterEachLabel')
              : $t('uiMessages.continuousStripFinalFeedAndCut')
          }}
        </p>
        <div class="row wrap">
          <span
            v-for="(length, index) in run.print_plan.label_lengths_mm"
            :key="index"
            class="badge"
          >
            {{ index + 1 }}: {{ length.toFixed(1) }} {{ $t('common.mm') }}
            {{ run.print_plan.cut_each ? '✂' : '→' }}
          </span>
        </div>
        <p class="help">
          {{ $t('csvRuns.planSavedWhenThisDraftWasPreparedCurrentPrinter') }}
        </p>
      </div>
      <p v-if="run.submitted_at" class="alert success">
        {{ $t('csvRuns.runSubmitted') }}
        <RouterLink to="/queue">{{ $t('common.viewPrintQueue') }}</RouterLink>
      </p>
      <template v-else
        ><p class="help">
          {{ $t('common.theEntireRunEntersTheQueueTogetherItMay') }}
        </p>
        <p v-if="!auth.printer(run.destination_id, 'submit_directly')" class="help">
          {{ $t('common.theEntireRunWillWaitForApprovalBeforeEntering') }}
        </p>
        <p v-if="destination?.available === false" class="help">
          {{ $t('common.thisDestinationHasNoConfiguredPrinterAvailableYourSaved') }}
        </p>
        <button
          class="primary"
          :disabled="
            busy || destination?.available === false || !auth.canSubmit(run.destination_id)
          "
          @click="submit"
        >
          {{
            auth.printer(run.destination_id, 'submit_directly')
              ? $t('uiMessages.submitEntireRun')
              : $t('uiMessages.requestPrintingForRun')
          }}
        </button>
        <button class="text-button danger-text" :disabled="busy" @click="deleteDraft(run)">
          {{ $t('csvRuns.deleteDraft') }}
        </button></template
      >
    </section>
    <section class="panel form-stack">
      <div class="section-heading">
        <h2>{{ $t('csvRuns.runPreview') }}</h2>
        <label class="checkbox"
          ><span class="checkbox-target"><input v-model="pixels" type="checkbox" /></span
          >{{ $t('common.showPrintPixels') }}</label
        >
      </div>
      <div class="row wrap">
        <button :disabled="position === 0" @click="position--">
          {{ $t('common.previousLabel') }}</button
        ><span
          >{{ $t('common.label') }} {{ position + 1 }} {{ $t('common.of') }} {{ run.rows.length }}
          {{ $t('common.csvRecord2') }} {{ run.rows[position]?.source_row }}</span
        ><button :disabled="position === run.rows.length - 1" @click="position++">
          {{ $t('common.nextLabel') }}
        </button>
      </div>
      <div class="label-stage">
        <img
          v-if="preview"
          class="raster-preview"
          :src="pixels ? preview.png : preview.design_png"
          :style="{
            imageRendering: pixels ? 'pixelated' : 'auto',
            aspectRatio: `${preview.length_mm} / ${preview.width_mm}`,
          }"
          :alt="$t('csvRuns.csvLabelPreview')"
        />
        <p v-else>{{ $t('common.loadingPreview') }}</p>
        <span
          >{{ run.rows[position]?.length_mm }} × {{ run.rows[position]?.width_mm }}
          {{ $t('common.mm2') }} {{ run.rows[position]?.copies }} {{ $t('common.copies2') }}</span
        >
      </div>
      <p v-for="warning in preview?.warnings ?? []" :key="warning" class="alert warning">
        {{ warning }}
      </p>
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>{{ $t('common.printOrder') }}</th>
              <th>{{ $t('common.csvRecord') }}</th>
              <th>{{ $t('common.values') }}</th>
              <th>{{ $t('csvRuns.length') }}</th>
              <th>{{ $t('common.copies') }}</th>
              <th>{{ $t('csvRuns.rowPrice') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, index) in run.rows" :key="row.source_row">
              <td>
                <button :aria-pressed="position === index" @click="position = index">
                  {{ index + 1 }}
                </button>
              </td>
              <td>{{ row.source_row }}</td>
              <td class="csv-values">
                {{ Object.values(row.payload).map(displayValue).join(' · ') }}
              </td>
              <td>{{ row.length_mm }} {{ $t('common.mm') }}</td>
              <td>{{ row.copies }}</td>
              <td>
                <CostEstimate :estimate="row.cost_estimate" /><span v-if="row.maximum_price"
                  >{{ $t('csvRuns.maximum') }} {{ (row.maximum_price.micros / 1000000).toFixed(2) }}
                  {{ row.maximum_price.currency }}</span
                >
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </template>
</template>
