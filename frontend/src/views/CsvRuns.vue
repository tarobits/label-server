<script setup lang="ts">
import { confirmAction } from '../confirmation'
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ApiError, errorMessage } from '../api'
import { useAuthStore } from '../auth'
import { useWorkspaceStore, date } from '../workspace'
import { useLiveRefresh } from '../live'
import { useResourceStore } from '../stores/resources'
import { randomUUID } from '../uuid'
interface Row {
  source_row: number
  values: string[]
  selected: boolean
  copies: number
}
interface Run {
  destination_id: string
  id: string
  name: string
  submitted_at: number | null
  created_at: number
  template_name: string
  template_revision: number
  copies: number
  label_length_mm: number
  estimated_mm: number
  print_plan?: {
    leader_mm: number
    feed_per_label_mm: number
    cut_each: boolean
    label_lengths_mm: number[]
  } | null
  rows: {
    source_row: number
    copies: number
    length_mm: number
    width_mm: number
    payload: Record<string, string>
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
const csv = ref(''),
  delimiter = ref(','),
  name = ref('CSV labels'),
  templateId = ref(
    typeof route.query.template === 'string' ? route.query.template : (w.templates[0]?.id ?? ''),
  ),
  profileId = ref(
    typeof route.query.profile === 'string'
      ? route.query.profile
      : (w.activeProfile?.id ?? w.profiles[0]?.id ?? ''),
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
      if (typeof query.profile === 'string') profileId.value = query.profile
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
const template = computed(() => w.templates.find((t) => t.id === templateId.value))
const destination = computed(() =>
  w.destinations.find((d) => d.id === (run.value?.destination_id ?? destinationId.value)),
)
const selected = computed(() => rows.value.filter((r) => r.selected))
let previewTicket = 0,
  generation = 0,
  stopped = false,
  previewPath = '',
  keyBody = '',
  requestKey = ''
watch([csv, delimiter], () => {
  headers.value = []
  rows.value = []
  rowErrors.value = []
})
watch(templateId, () => {
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
    if (file.size > 1_000_000) throw new Error('CSV must not exceed 1 MB.')
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
    rows.value = result.rows.map((r) => ({ ...r, selected: true, copies: 1 }))
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
    if (!template.value) throw new Error('Choose a template.')
    rowErrors.value = []
    const body = {
      destination_id: destinationId.value,
      name: name.value,
      template: templateId.value,
      expected_revision: template.value.revision,
      tape_profile: profileId.value,
      csv_text: parsedText.value,
      delimiter: parsedDelimiter.value,
      mapping: Object.fromEntries(Object.entries(mapping.value).filter(([, v]) => v)),
      rows: selected.value.map((r) => ({ source_row: r.source_row, copies: r.copies })),
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
  if (!(await confirmAction(`Delete draft “${item.name}”? This cannot be undone.`))) return
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
    if (!auth.atLeast(run.value!.destination_id, 'print')) {
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
      if (
        !(await confirmAction(
          `${failure.message}\nOverride and print this run with your administrator authorization?`,
        ))
      )
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
      Your saved runs remain available. A role with destination access is needed to prepare or
      submit new labels.
    </p>
    <fieldset v-if="w.destinations.length" :disabled="busy" class="panel form-stack csv-form">
      <h2>Import CSV</h2>
      <label
        >Print destination<select v-model="destinationId">
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
        This destination has no configured printer available. Update its printers before preparing
        labels.
      </p>
      <div class="field-row">
        <label>Run name<input v-model="name" maxlength="100" /></label>
        <label
          >Template<select v-model="templateId">
            <option v-for="t in w.templates" :key="t.id" :value="t.id">{{ t.name }}</option>
          </select></label
        >
        <label
          >Tape profile<select v-model="profileId">
            <option v-for="p in w.profiles" :key="p.id" :value="p.id">
              {{ p.name }} · {{ p.width_mm }} mm
            </option>
          </select></label
        >
      </div>
      <label
        >CSV file<input type="file" accept=".csv,text/csv,text/plain" @change="fileChanged"
      /></label>
      <label
        >CSV content<textarea
          v-model="csv"
          rows="6"
          placeholder="text,location&#10;Network cable,Office"
        />
      </label>
      <label
        >Delimiter<select v-model="delimiter">
          <option value=",">Comma</option>
          <option value=";">Semicolon</option>
          <option :value="'\t'">Tab</option>
        </select></label
      >
      <p class="help">
        UTF-8 CSV with a header, up to 250 data records / 1 MB. Quoted commas and multiline values
        are supported. Record numbers include the header.
      </p>
      <button :disabled="!csv || !templateId || !profileId" @click="parse">Read CSV</button>
      <template v-if="headers.length">
        <h2>Map columns</h2>
        <div class="field-row">
          <label v-for="field in template?.document.fields" :key="field.name"
            >{{ field.label
            }}<select v-model="mapping[field.name]">
              <option value="">Use field default</option>
              <option v-for="header in headers" :key="header" :value="header">{{ header }}</option>
            </select></label
          >
        </div>
        <p class="help">
          Missing required values will be reported for each selected record. Row order below is
          print order.
        </p>
        <div class="row wrap">
          <button @click="rows.forEach((r) => (r.selected = true))">Select all</button
          ><button @click="rows.forEach((r) => (r.selected = false))">Select none</button
          ><span
            >{{ selected.length }} records · {{ selected.reduce((n, r) => n + r.copies, 0) }} copies
            (maximum 1000)</span
          >
        </div>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Use</th>
                <th>Record</th>
                <th>Values</th>
                <th>Copies</th>
                <th>Order</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, index) in rows" :key="row.source_row">
                <td>
                  <input
                    v-model="row.selected"
                    type="checkbox"
                    :aria-label="`Select record ${row.source_row}`"
                  />
                </td>
                <td>{{ row.source_row }}</td>
                <td class="csv-values">{{ row.values.join(' · ') }}</td>
                <td>
                  <input
                    v-model.number="row.copies"
                    type="number"
                    min="1"
                    max="1000"
                    :aria-label="`Copies for record ${row.source_row}`"
                  />
                </td>
                <td>
                  <div class="row">
                    <button
                      :disabled="index === 0"
                      :aria-label="`Move record ${row.source_row} up`"
                      @click="move(index, -1)"
                    >
                      ↑</button
                    ><button
                      :disabled="index === rows.length - 1"
                      :aria-label="`Move record ${row.source_row} down`"
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
          Record {{ issue.source_row }}: {{ issue.message }}
        </p>
        <button
          class="primary"
          :disabled="!selected.length || destination?.available === false"
          @click="prepare"
        >
          Validate and preview run
        </button>
        <p class="help">This saves a draft for review. Nothing is queued or printed yet.</p>
      </template>
    </fieldset>
    <section class="panel">
      <h2>Recent runs</h2>
      <p v-if="!runs.length" class="help">No saved runs yet.</p>
      <div v-for="item in runs" :key="item.id" class="section-heading">
        <RouterLink :to="`/runs/${item.id}`">{{ item.name }}</RouterLink
        ><span>{{ item.submitted_at ? 'Submitted' : 'Draft' }} · {{ date(item.created_at) }}</span>
        <button
          v-if="!item.submitted_at"
          class="text-button danger-text"
          :disabled="busy"
          @click="deleteDraft(item)"
        >
          Delete draft
        </button>
      </div>
    </section>
  </template>
  <template v-else-if="run">
    <section class="panel form-stack">
      <div class="section-heading">
        <h2>{{ run.name }}</h2>
        <RouterLink to="/runs">Import another CSV</RouterLink>
      </div>
      <p>
        {{ run.template_name }} · Revision {{ run.template_revision }} ·
        {{ run.rows.length }} records · {{ run.copies }} copies
      </p>
      <p>
        Labels: {{ run.label_length_mm.toFixed(2) }} mm · Estimated tape:
        {{ run.estimated_mm.toFixed(2) }} mm as one batch. Actual use depends on feed, cuts, and
        retries.
      </p>
      <div v-if="run.print_plan" class="inset">
        <strong>Planned tape sequence</strong>
        <p>
          {{ run.print_plan.leader_mm.toFixed(1) }} mm batch overhead ·
          {{ run.print_plan.feed_per_label_mm.toFixed(1) }} mm feed per label ·
          {{
            run.print_plan.cut_each
              ? 'Cut after each label'
              : 'Continuous strip, final feed and cut'
          }}
        </p>
        <div class="row wrap">
          <span
            v-for="(length, index) in run.print_plan.label_lengths_mm"
            :key="index"
            class="badge"
          >
            {{ index + 1 }}: {{ length.toFixed(1) }} mm {{ run.print_plan.cut_each ? '✂' : '→' }}
          </span>
        </div>
        <p class="help">
          Plan saved when this draft was prepared. Current printer settings apply when printing.
        </p>
      </div>
      <p v-if="run.submitted_at" class="alert success">
        Run submitted. <RouterLink to="/queue">View print queue</RouterLink>
      </p>
      <template v-else
        ><p class="help">
          The entire run enters the queue together. It may print immediately if the threshold is
          reached and automatic printing is enabled.
        </p>
        <p v-if="!auth.atLeast(run.destination_id, 'print')" class="help">
          The entire run will wait for approval before entering the queue.
        </p>
        <p v-if="destination?.available === false" class="help">
          This destination has no configured printer available. Your saved draft remains available.
        </p>
        <button
          class="primary"
          :disabled="
            busy || destination?.available === false || !auth.atLeast(run.destination_id, 'request')
          "
          @click="submit"
        >
          {{
            auth.atLeast(run.destination_id, 'print')
              ? 'Submit entire run'
              : 'Request printing for run'
          }}
        </button>
        <button class="text-button danger-text" :disabled="busy" @click="deleteDraft(run)">
          Delete draft
        </button></template
      >
    </section>
    <section class="panel form-stack">
      <div class="section-heading">
        <h2>Run preview</h2>
        <label class="checkbox"><input v-model="pixels" type="checkbox" />Show print pixels</label>
      </div>
      <div class="row wrap">
        <button :disabled="position === 0" @click="position--">Previous label</button
        ><span
          >Label {{ position + 1 }} of {{ run.rows.length }} · CSV record
          {{ run.rows[position]?.source_row }}</span
        ><button :disabled="position === run.rows.length - 1" @click="position++">
          Next label
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
          alt="CSV label preview"
        />
        <p v-else>Loading preview…</p>
        <span
          >{{ run.rows[position]?.length_mm }} × {{ run.rows[position]?.width_mm }} mm ·
          {{ run.rows[position]?.copies }} copies</span
        >
      </div>
      <p v-for="warning in preview?.warnings ?? []" :key="warning" class="alert warning">
        {{ warning }}
      </p>
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Print order</th>
              <th>CSV record</th>
              <th>Values</th>
              <th>Length</th>
              <th>Copies</th>
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
              <td class="csv-values">{{ Object.values(row.payload).join(' · ') }}</td>
              <td>{{ row.length_mm }} mm</td>
              <td>{{ row.copies }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </template>
</template>
