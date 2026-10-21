<script setup lang="ts">
import { useAuthStore } from '../auth'
import { confirmAction } from '../confirmation'
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errorMessage } from '../api'
import { requestPrinting } from '../printing'
import { useLiveRefresh } from '../live'
import { useResourceStore } from '../stores/resources'
import type { Job } from '../types'
import { useWorkspaceStore, date } from '../workspace'
import Badge from '../components/Badge.vue'
import QueuePreview from '../components/QueuePreview.vue'
import LabelDetails from '../components/LabelDetails.vue'
import AnimatedDetails from '../components/AnimatedDetails.vue'
interface QueueGroup {
  id: string
  run_id: string | null
  name: string | null
  jobs: Job[]
}
const w = useWorkspaceStore()
const auth = useAuthStore()
const route = useRoute(),
  router = useRouter(),
  resources = useResourceStore()
const groups = ref<QueueGroup[]>([]),
  selectedIds = ref<string[]>([]),
  expanded = ref<string[]>([]),
  filter = ref('queued'),
  profileFilter = ref(''),
  destinationFilter = ref(
    typeof route.query.destination === 'string' ? route.query.destination : '',
  ),
  page = ref(0),
  error = ref(''),
  loading = ref(false)
let stopped = false,
  generation = 0,
  hasLoaded = false,
  lastResponse = ''
async function load(background = false, force = false) {
  const ticket = ++generation,
    actor = auth.user?.id
  if (!background) loading.value = true
  try {
    const data = await resources.get<QueueGroup[]>(
      `/queue/groups?limit=25&offset=${page.value * 25}${filter.value ? `&copy_state=${filter.value}` : ''}${profileFilter.value ? `&profile_id=${encodeURIComponent(profileFilter.value)}` : ''}${destinationFilter.value ? `&destination_id=${encodeURIComponent(destinationFilter.value)}` : ''}`,
      { ttl: 5000, force },
    )
    if (!stopped && ticket === generation && auth.user?.id === actor) {
      const response = JSON.stringify(data)
      if (response !== lastResponse) {
        groups.value = data
        lastResponse = response
        const available = new Set(selectable(data.flatMap((group) => group.jobs)))
        const retained = selectedIds.value.filter((id) => available.has(id))
        if (retained.length !== selectedIds.value.length) selectedIds.value = retained
      }
      hasLoaded = true
      error.value = ''
    }
  } catch (e) {
    if (!stopped && ticket === generation && auth.user?.id === actor) error.value = errorMessage(e)
  } finally {
    if (ticket === generation) loading.value = false
  }
}
useLiveRefresh(() => load(hasLoaded), 5000)
watch([filter, profileFilter, destinationFilter], () => {
  selectedIds.value = []
  if (page.value !== 0) page.value = 0
  else void load()
})
watch(destinationFilter, (destination) => {
  if (route.path === '/queue')
    void router.replace({ query: { ...route.query, destination: destination || undefined } })
})
watch(
  () => route.query.destination,
  (destination) => {
    destinationFilter.value = typeof destination === 'string' ? destination : ''
  },
)
watch(page, () => {
  selectedIds.value = []
  void load()
})
onUnmounted(() => {
  stopped = true
  generation++
})
const jobs = computed(() => groups.value.flatMap((group) => group.jobs))
const labelName = (job: Job) => job.process_name || job.template_name || 'Label'
const canCancel = (job: Job) =>
  job.can_cancel ??
  (job.owner_id === auth.user?.id || auth.atLeast(job.destination_id, 'moderator'))
const canPrintJob = (job: Job) =>
  job.access_hold?.status !== 'held' &&
  !job.labels.some((copy) => copy.state === 'printing' || copy.state === 'needs_review') &&
  (job.can_print ??
    (auth.atLeast(job.destination_id, 'moderator') ||
      (job.owner_id === auth.user?.id && auth.atLeast(job.destination_id, 'print'))))
const selectedJobs = computed(() =>
  jobs.value.filter((job) => job.labels.some((copy) => selectedIds.value.includes(copy.id))),
)
function selectable(items: Job[]) {
  return items
    .filter(canCancel)
    .flatMap((job) => job.labels.filter((copy) => copy.state === 'queued').map((copy) => copy.id))
}
const selectedDestination = computed(() => {
  const ids = new Set(
    jobs.value
      .filter((job) => job.labels.some((copy) => selectedIds.value.includes(copy.id)))
      .map((job) => job.destination_id),
  )
  return ids.size === 1 ? [...ids][0] : undefined
})
const canPrintSelection = computed(
  () =>
    !w.busy &&
    selectedIds.value.length > 0 &&
    !!selectedDestination.value &&
    selectedJobs.value.every(canPrintJob),
)
function routing(job: Job) {
  if (job.access_hold?.status === 'held')
    return `${w.destinationName(job.destination_id)} · Paused: ${job.access_hold.reason}`
  const destination = w.destinations.find((d) => d.id === job.destination_id)
  if (!destination) return job.destination_id
  if (job.assigned_printer_id)
    return `${destination.name} → ${destination.member_names?.[job.assigned_printer_id] ?? w.destinationName(job.assigned_printer_id)}`
  if (destination.kind === 'printer' || job.status !== 'queued') return destination.name
  if (destination.automatic_printing_held) return `${destination.name} · Held`
  if (
    destination.printer_ids.some(
      (id) => !w.printerStatuses.some((state) => state.printer_id === id),
    )
  )
    return `${destination.name} · Routed through this group`
  const ready = destination.printer_ids.find((id) => {
    const state = w.printerStatuses.find((s) => s.printer_id === id)
    return (
      state?.connected &&
      !state.printer_error &&
      !state.automatic_printing_held &&
      !state.printing &&
      !state.needs_review.length &&
      state.detected_width_mm === job.width_mm &&
      w.cartridges.find((c) => c.id === state.active_cartridge_id)?.profile_id === job.profile_id
    )
  })
  return `${destination.name} · ${ready ? 'Next eligible: ' + w.destinationName(ready) : 'Waiting for a matching printer'}`
}
async function removeSelected() {
  const ids = [...selectedIds.value]
  if (
    !ids.length ||
    !(await confirmAction(
      `Remove ${ids.length} queued copies? They will remain in cancelled history.`,
    ))
  )
    return
  if (
    await w.action(
      () => api('/queue/remove', 'POST', { copy_ids: ids }),
      'Selected copies removed from the queue.',
    )
  ) {
    selectedIds.value = []
    await load(false, true)
  }
}
function checked(items: Job[]) {
  const ids = selectable(items)
  return ids.length > 0 && ids.every((id) => selectedIds.value.includes(id))
}
function partial(items: Job[]) {
  return !checked(items) && selectable(items).some((id) => selectedIds.value.includes(id))
}
function toggle(items: Job[], event: Event) {
  const ids = new Set(selectable(items))
  selectedIds.value = (event.target as HTMLInputElement).checked
    ? [...new Set([...selectedIds.value, ...ids])]
    : selectedIds.value.filter((id) => !ids.has(id))
}
function expand(id: string) {
  expanded.value = expanded.value.includes(id)
    ? expanded.value.filter((value) => value !== id)
    : [...expanded.value, id]
}
async function printSelected() {
  const ids = [...selectedIds.value]
  if (!ids.length) return
  if (
    await w.action(
      () => requestPrinting(`/destinations/${selectedDestination.value}/print`, { copy_ids: ids }),
      'Selected copies reserved for printing.',
    )
  ) {
    selectedIds.value = []
    await load(false, true)
  }
}
async function cancel(job: Job) {
  if (!(await confirmAction('Remove this item’s queued copies? Printed copies stay in history.')))
    return
  if (await w.action(() => api(`/jobs/${job.id}`, 'DELETE'), 'Item removed from the queue.'))
    await load(false, true)
}
</script>
<template>
  <section class="panel">
    <div class="queue-toolbar">
      <div class="queue-filters">
        <label for="queue-filter"
          >Job status
          <select id="queue-filter" v-model="filter">
            <option value="queued">Queued</option>
            <option value="needs_review">Needs review</option>
            <option value="printed">Printed</option>
            <option value="cancelled">Cancelled</option>
            <option value="">All jobs</option>
          </select>
        </label>
        <label for="queue-profile-filter"
          >Tape profile
          <select id="queue-profile-filter" v-model="profileFilter">
            <option value="">All tape profiles</option>
            <option v-for="profile in w.profiles" :key="profile.id" :value="profile.id">
              {{ profile.name }} · {{ profile.width_mm }} mm
            </option>
          </select>
        </label>
        <label class="queue-destination-filter"
          >Destination<select v-model="destinationFilter">
            <option value="">All destinations</option>
            <option v-for="target in w.destinations" :key="target.id" :value="target.id">
              {{ target.name }}
            </option>
          </select></label
        >
      </div>
      <div class="row wrap">
        <button
          v-if="auth.any('print')"
          class="primary"
          :disabled="!canPrintSelection || loading"
          @click="printSelected"
        >
          Print selected ({{ selectedIds.length }})
        </button>
        <button
          class="secondary danger-text"
          :disabled="!selectedIds.length || w.busy || loading"
          @click="removeSelected"
        >
          Remove selected ({{ selectedIds.length }})
        </button>
      </div>
    </div>
    <p v-if="auth.any('moderator')" class="help">
      Printing requires the installed tape. Printing a selection holds automatic printing so
      unselected items stay queued. Each item selects its remaining queued copies.
    </p>
    <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
    <div class="table-scroll">
      <table class="queue-table">
        <colgroup>
          <col class="queue-selection-column" />
          <col />
          <col class="queue-tape-column" />
          <col class="queue-copies-column" />
          <col class="queue-status-column" />
          <col class="queue-actions-column" />
        </colgroup>
        <thead>
          <tr>
            <th>
              <label class="checkbox-target"
                ><input
                  type="checkbox"
                  aria-label="Select all queued items on this page"
                  :checked="checked(jobs)"
                  :indeterminate="partial(jobs)"
                  :disabled="!selectable(jobs).length || loading"
                  @change="toggle(jobs, $event)"
              /></label>
            </th>
            <th>Process</th>
            <th>Tape</th>
            <th>Copies</th>
            <th>Status</th>
            <th><span class="sr-only">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          <template v-for="group in groups" :key="group.id">
            <tr v-if="group.run_id" class="queue-run-row">
              <td>
                <div class="queue-run-controls">
                  <label class="checkbox-target"
                    ><input
                      type="checkbox"
                      :aria-label="`Select run ${group.name}`"
                      :checked="checked(group.jobs)"
                      :indeterminate="partial(group.jobs)"
                      :disabled="!selectable(group.jobs).length || loading"
                      @change="toggle(group.jobs, $event)"
                  /></label>
                  <button
                    class="queue-disclosure"
                    :aria-label="`Toggle ${group.name}`"
                    :aria-expanded="expanded.includes(group.id)"
                    @click="expand(group.id)"
                  >
                    <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
                      <path
                        d="m7 4 6 6-6 6"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="1.8"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                      />
                    </svg>
                  </button>
                </div>
              </td>
              <td>
                <strong>{{ group.name }}</strong
                ><small>{{ group.jobs.length }} matching labels</small>
              </td>
              <td>{{ w.profileName(group.jobs[0]!.profile_id) }}</td>
              <td>
                {{
                  group.jobs.reduce(
                    (total, job) =>
                      total + job.labels.filter((copy) => copy.state === 'queued').length,
                    0,
                  )
                }}
                queued
              </td>
              <td>
                <Badge
                  :state="
                    new Set(group.jobs.map((job) => job.status)).size === 1
                      ? group.jobs[0]!.status
                      : 'mixed'
                  "
                />
              </td>
              <td class="queue-run-actions">
                <RouterLink :to="`/runs/${group.run_id}`">View run</RouterLink>
              </td>
            </tr>
            <Transition v-for="job in group.jobs" :key="job.id" name="queue-expand">
              <tr
                v-if="!group.run_id || expanded.includes(group.id)"
                :class="{ 'queue-run-child': group.run_id }"
              >
                <td>
                  <div class="queue-cell">
                    <div class="queue-cell-content">
                      <label class="checkbox-target"
                        ><input
                          type="checkbox"
                          :aria-label="`Select ${job.payload.text || (job.source_row ? 'CSV record ' + job.source_row : labelName(job))}`"
                          :checked="checked([job])"
                          :indeterminate="partial([job])"
                          :disabled="!selectable([job]).length || loading"
                          @change="toggle([job], $event)"
                      /></label>
                    </div>
                  </div>
                </td>
                <td>
                  <div class="queue-cell">
                    <div class="queue-cell-content">
                      <strong class="queue-label-name">{{ labelName(job) }}</strong
                      ><small>{{ date(job.created_at) }} · {{ job.length_mm }} mm</small
                      ><small>{{ routing(job) }}</small>
                      <RouterLink v-if="job.run_id" :to="`/runs/${job.run_id}`"
                        >CSV record {{ job.source_row }}</RouterLink
                      >
                      <AnimatedDetails class="queue-label-details">
                        <template #summary>Details</template>
                        <LabelDetails :label="job" :attribution="job.attribution" />
                      </AnimatedDetails>
                      <QueuePreview
                        :job-id="job.id"
                        :text="labelName(job)"
                        :width-mm="job.width_mm"
                        :length-mm="job.length_mm"
                      />
                    </div>
                  </div>
                </td>
                <td>
                  <div class="queue-cell">
                    <div class="queue-cell-content">
                      {{ w.profileName(job.profile_id) }}<small>{{ job.width_mm }} mm</small>
                    </div>
                  </div>
                </td>
                <td>
                  <div class="queue-cell">
                    <div class="queue-cell-content">
                      {{ job.copies
                      }}<small
                        >{{ job.labels.filter((l) => l.state === 'queued').length }} queued</small
                      >
                    </div>
                  </div>
                </td>
                <td>
                  <div class="queue-cell">
                    <div class="queue-cell-content"><Badge :state="job.status" /></div>
                  </div>
                </td>
                <td class="queue-run-actions">
                  <div class="queue-cell">
                    <div class="queue-cell-content">
                      <button
                        v-if="job.labels.some((copy) => copy.state === 'queued') && canCancel(job)"
                        class="text-button danger-text"
                        :disabled="w.busy"
                        @click="cancel(job)"
                      >
                        Remove</button
                      ><RouterLink
                        v-else-if="
                          job.status === 'needs_review' &&
                          w.printers.some((p) => auth.atLeast(p.id, 'moderator'))
                        "
                        to="/activity"
                        >Review batch →</RouterLink
                      >
                    </div>
                  </div>
                </td>
              </tr>
            </Transition>
          </template>
        </tbody>
      </table>
    </div>
    <div v-if="!jobs.length && !loading" class="empty">
      <h3>No {{ filter ? filter.replaceAll('_', ' ') : '' }} labels here.</h3>
      <RouterLink class="button secondary" to="/new">Create a label</RouterLink>
    </div>
    <div class="pagination">
      <span>Page {{ page + 1 }} · Up to 25 items or runs per page</span
      ><button :disabled="page === 0 || loading" @click="page--">Previous</button
      ><button :disabled="groups.length < 25 || loading" @click="page++">Next</button>
    </div>
  </section>
</template>

<style scoped>
.queue-destination-filter {
  grid-column: 1 / -1;
}
.queue-label-name {
  white-space: normal;
}
.queue-label-details {
  margin-top: 8px;
  white-space: normal;
}
.queue-label-details :deep(summary) {
  width: fit-content;
  padding-block: 6px;
  color: var(--text-secondary);
  cursor: pointer;
}
.queue-label-details :deep(summary:hover),
.queue-label-details[data-expanded='true'] :deep(summary) {
  color: var(--ink);
}
</style>
