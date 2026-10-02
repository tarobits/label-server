<script setup lang="ts">
import { confirmAction } from '../confirmation'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api, errorMessage } from '../api'
import type { Job } from '../types'
import { workspace as w, date } from '../workspace'
import Badge from '../components/Badge.vue'
interface QueueGroup {
  id: string
  run_id: string | null
  name: string | null
  jobs: Job[]
}
const groups = ref<QueueGroup[]>([]),
  selectedIds = ref<string[]>([]),
  expanded = ref<string[]>([]),
  filter = ref('queued'),
  profileFilter = ref(''),
  page = ref(0),
  error = ref(''),
  loading = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined,
  stopped = false,
  generation = 0,
  hasLoaded = false,
  lastResponse = ''
async function load(background = false) {
  const ticket = ++generation
  if (!background) loading.value = true
  try {
    const data = await api<QueueGroup[]>(
      `/queue/groups?limit=25&offset=${page.value * 25}${filter.value ? `&copy_state=${filter.value}` : ''}${profileFilter.value ? `&profile_id=${encodeURIComponent(profileFilter.value)}` : ''}`,
    )
    if (ticket === generation) {
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
    if (ticket === generation) error.value = errorMessage(e)
  } finally {
    if (ticket === generation) loading.value = false
  }
}
async function poll() {
  await load(hasLoaded)
  if (!stopped) timer = setTimeout(poll, 2500)
}
watch([filter, profileFilter], () => {
  selectedIds.value = []
  if (page.value !== 0) page.value = 0
  else void load()
})
watch(page, () => {
  selectedIds.value = []
  void load()
})
watch(
  () => w.activeProfile.value?.id,
  () => {
    selectedIds.value = []
  },
)
onMounted(poll)
onUnmounted(() => {
  stopped = true
  generation++
  clearTimeout(timer)
})
const jobs = computed(() => groups.value.flatMap((group) => group.jobs))
function selectable(items: Job[]) {
  return items
    .filter(
      (job) =>
        !job.labels.some((copy) => copy.state === 'printing' || copy.state === 'needs_review'),
    )
    .flatMap((job) => job.labels.filter((copy) => copy.state === 'queued').map((copy) => copy.id))
}
const canPrintSelection = computed(() => {
  const compatible = new Set(
    selectable(jobs.value.filter((job) => job.profile_id === w.activeProfile.value?.id)),
  )
  return (
    w.canPrint.value &&
    selectedIds.value.length > 0 &&
    selectedIds.value.every((id) => compatible.has(id))
  )
})
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
    await load()
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
      () => api('/queue/print', 'POST', { copy_ids: ids }),
      'Selected copies reserved. Automatic printing is held so the rest stays queued.',
    )
  ) {
    selectedIds.value = []
    await load()
  }
}
async function cancel(job: Job) {
  if (!(await confirmAction('Remove this item’s queued copies? Printed copies stay in history.')))
    return
  if (await w.action(() => api(`/jobs/${job.id}`, 'DELETE'), 'Item removed from the queue.'))
    await load()
}
</script>
<template>
  <section class="panel">
    <div class="section-heading">
      <div class="row wrap">
        <h2>Labels</h2>
        <label class="sr-only" for="queue-filter">Filter jobs</label
        ><select id="queue-filter" v-model="filter">
          <option value="queued">Queued</option>
          <option value="needs_review">Needs review</option>
          <option value="printed">Printed</option>
          <option value="cancelled">Cancelled</option>
          <option value="">All jobs</option>
        </select>
        <label class="sr-only" for="queue-profile-filter">Filter by tape profile</label>
        <select id="queue-profile-filter" v-model="profileFilter">
          <option value="">All tape profiles</option>
          <option v-for="profile in w.profiles.value" :key="profile.id" :value="profile.id">
            {{ profile.name }} · {{ profile.width_mm }} mm
          </option>
        </select>
      </div>
      <div class="row wrap">
        <button class="primary" :disabled="!canPrintSelection || loading" @click="printSelected">
          Print selected ({{ selectedIds.length }})
        </button>
        <button
          class="secondary danger-text"
          :disabled="!selectedIds.length || w.busy.value || loading"
          @click="removeSelected"
        >
          Remove selected ({{ selectedIds.length }})
        </button>
        <button class="secondary" :disabled="!w.canPrint.value" @click="w.printNow">
          Print compatible queue now
        </button>
      </div>
    </div>
    <p class="help">
      Select queued items to print or remove. Printing requires the installed tape. Printing a
      selection holds automatic printing so unselected items stay queued. Each item selects its
      remaining queued copies.
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
              <input
                type="checkbox"
                aria-label="Select all queued items on this page"
                :checked="checked(jobs)"
                :indeterminate="partial(jobs)"
                :disabled="!selectable(jobs).length || loading"
                @change="toggle(jobs, $event)"
              />
            </th>
            <th>Label</th>
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
                  <input
                    type="checkbox"
                    :aria-label="`Select run ${group.name}`"
                    :checked="checked(group.jobs)"
                    :indeterminate="partial(group.jobs)"
                    :disabled="!selectable(group.jobs).length || loading"
                    @change="toggle(group.jobs, $event)"
                  />
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
                      <input
                        type="checkbox"
                        :aria-label="`Select ${job.payload.text || (job.source_row ? 'CSV record ' + job.source_row : job.template_id)}`"
                        :checked="checked([job])"
                        :indeterminate="partial([job])"
                        :disabled="!selectable([job]).length || loading"
                        @change="toggle([job], $event)"
                      />
                    </div>
                  </div>
                </td>
                <td>
                  <div class="queue-cell">
                    <div class="queue-cell-content">
                      <strong class="truncate">{{ job.payload.text || job.template_id }}</strong
                      ><small>{{ date(job.created_at) }} · {{ job.length_mm }} mm</small>
                      <RouterLink v-if="job.run_id" :to="`/runs/${job.run_id}`"
                        >CSV record {{ job.source_row }}</RouterLink
                      >
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
                        v-if="job.status === 'queued'"
                        class="text-button danger-text"
                        :disabled="w.busy.value"
                        @click="cancel(job)"
                      >
                        Remove</button
                      ><RouterLink v-else-if="job.status === 'needs_review'" to="/activity"
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
      <p>Add a label and let the queue take care of the rest.</p>
      <RouterLink class="button secondary" to="/new">Create a label</RouterLink>
    </div>
    <div class="pagination">
      <span>Page {{ page + 1 }} · Up to 25 items or runs per page</span
      ><button :disabled="page === 0 || loading" @click="page--">Previous</button
      ><button :disabled="groups.length < 25 || loading" @click="page++">Next</button>
    </div>
  </section>
</template>
