<script setup lang="ts">
import { t } from '../shared/i18n'

import { useAuthStore } from '../auth/auth'
import { confirmAction } from '../shared/confirmation'
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errorMessage } from '../shared/api'
import { requestPrinting } from '../printing/printing'
import { useLiveRefresh } from '../shared/live'
import { useResourceStore } from '../stores/resources'
import type { CostEstimate as CostEstimateData, Job, PrintPlan } from '../shared/types'
import { useWorkspaceStore, date } from '../shared/workspace'
import Badge from '../components/Badge.vue'
import QueuePreview from '../components/QueuePreview.vue'
import LabelDetails from '../components/LabelDetails.vue'
import AnimatedDetails from '../components/AnimatedDetails.vue'
import TapeUsage from '../components/TapeUsage.vue'
import CostEstimate from '../components/CostEstimate.vue'
import ChangeQueuePrinter from '../components/ChangeQueuePrinter.vue'
import ChangeCopies from '../components/ChangeCopies.vue'
import PaymentAttribution from '../components/PaymentAttribution.vue'
interface QueueGroup {
  cost_estimate?: CostEstimateData | null
  print_plan?: PrintPlan | null
  print_plan_scope?: 'queued' | 'submission'
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
  filter = ref(route.query.state === 'printed' ? 'printed' : t('common.queued')),
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
watch(
  () => route.query.state,
  (state) => {
    filter.value = state === 'printed' ? 'printed' : t('common.queued')
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
const labelName = (job: Job) => job.process_name || job.template_name || t('common.label')
async function changeCompletionNotification(job: Job, event: Event) {
  const input = event.target as HTMLInputElement
  const enabled = input.checked
  const previous = job.notify_on_completion
  job.notify_on_completion = enabled
  if (
    await w.action(
      () =>
        api(`/jobs/${job.id}/completion-notification`, 'PUT', { notify_on_completion: enabled }),
      '',
    )
  )
    await load(false, true)
  else job.notify_on_completion = previous
}
const canCancel = (job: Job) =>
  job.can_cancel ??
  (job.owner_id === auth.user?.id || auth.printer(job.destination_id, 'manage_queue'))
const canPrintJob = (job: Job) =>
  !job.billing_held &&
  job.access_hold?.status !== 'held' &&
  !job.labels.some((copy) => copy.state === 'printing' || copy.state === 'needs_review') &&
  (job.can_print ??
    (auth.printer(job.destination_id, 'start_any') ||
      (job.owner_id === auth.user?.id && auth.printer(job.destination_id, 'start_own'))))
const selectedJobs = computed(() =>
  jobs.value.filter((job) => job.labels.some((copy) => selectedIds.value.includes(copy.id))),
)
function selectable(items: Job[]) {
  return items
    .filter((job) => canCancel(job) || canPrintJob(job))
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
function displayState(job: Job) {
  if (job.status !== 'queued' || !job.billing_held) return job.status
  if (job.billing_request?.status === 'pending') return 'waiting_for_group_approval'
  if (job.billing_request?.status === 'rejected') return 'group_funding_rejected'
  return 'group_funding_on_hold'
}
function routing(job: Job) {
  if (job.billing_held)
    return t('uiDetails.groupFundingHeld', {
      value1: String(w.destinationName(job.destination_id)),
    })
  if (
    job.billing_request?.mode === 'wait' &&
    ['pending', 'rejected'].includes(job.billing_request.status)
  )
    return t('uiDetails.fundingPending', { value1: String(w.destinationName(job.destination_id)) })
  if (job.access_hold?.status === 'held')
    return t('uiDetails.paused', {
      value1: String(w.destinationName(job.destination_id)),
      value2: String(job.access_hold.reason),
    })
  const destination = w.destinations.find((d) => d.id === job.destination_id)
  if (!destination) return job.destination_id
  if (destination.no_automatic_printing && job.status === 'queued')
    return t('uiDetails.manualOnly', { value1: String(destination.name) })
  if (job.assigned_printer_id)
    return `${destination.name} → ${destination.member_names?.[job.assigned_printer_id] ?? w.destinationName(job.assigned_printer_id)}`
  if (destination.kind === 'printer' || job.status !== 'queued') return destination.name
  if (destination.automatic_printing_held)
    return t('uiDetails.held', { value1: String(destination.name) })
  if (
    destination.printer_ids.some(
      (id) => !w.printerStatuses.some((state) => state.printer_id === id),
    )
  )
    return t('uiDetails.routedThroughGroup', { value1: String(destination.name) })
  const ready = destination.printer_ids.find((id) => {
    const state = w.printerStatuses.find((s) => s.printer_id === id)
    return (
      state?.connected &&
      !state.printer_error &&
      !state.automatic_printing_held &&
      !state.no_automatic_printing &&
      !state.printing &&
      !state.needs_review.length &&
      (state.effective_width_mm ?? state.detected_width_mm) === job.width_mm &&
      w.cartridges.find((c) => c.id === state.active_cartridge_id)?.profile_id === job.profile_id
    )
  })
  return `${destination.name} · ${ready ? t('uiRemainder.nextPrinter', { name: w.destinationName(ready) }) : t('uiMessages.waitingForAMatchingPrinter')}`
}
async function printerChanged() {
  selectedIds.value = []
  await load(false, true)
}
async function removeSelected() {
  const ids = [...selectedIds.value]
  if (
    !ids.length ||
    !(await confirmAction(t('uiDetails.removeQueuedCopies', { value1: String(ids.length) })))
  )
    return
  if (
    await w.action(
      () => api('/queue/remove', 'POST', { copy_ids: ids }),
      t('uiMessages.selectedCopiesRemovedFromTheQueue'),
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
      t('uiMessages.selectedCopiesReservedForPrinting'),
    )
  ) {
    selectedIds.value = []
    await load(false, true)
  }
}
async function cancel(job: Job) {
  if (!(await confirmAction(t('uiMessages.removeThisItemSQueuedCopiesPrintedCopiesStayInHistory'))))
    return
  if (
    await w.action(() => api(`/jobs/${job.id}`, 'DELETE'), t('uiMessages.itemRemovedFromTheQueue'))
  )
    await load(false, true)
}
</script>
<template>
  <section class="panel">
    <div class="queue-toolbar">
      <div class="queue-filters">
        <label for="queue-filter"
          >{{ $t('jobs.jobStatus') }}
          <select id="queue-filter" v-model="filter">
            <option value="queued">{{ $t('jobs.queued') }}</option>
            <option value="needs_review">{{ $t('jobs.needsReview') }}</option>
            <option value="printed">{{ $t('common.printed') }}</option>
            <option value="cancelled">{{ $t('jobs.cancelled') }}</option>
            <option value="">{{ $t('jobs.allJobs') }}</option>
          </select>
        </label>
        <label for="queue-profile-filter"
          >{{ $t('common.tapeProfile') }}
          <select id="queue-profile-filter" v-model="profileFilter">
            <option value="">{{ $t('jobs.allTapeProfiles') }}</option>
            <option v-for="profile in w.profiles" :key="profile.id" :value="profile.id">
              {{ profile.name }} · {{ profile.width_mm }} {{ $t('common.mm') }}
            </option>
          </select>
        </label>
        <label class="queue-destination-filter"
          >{{ $t('common.destination')
          }}<select v-model="destinationFilter">
            <option value="">{{ $t('jobs.allDestinations') }}</option>
            <option v-for="target in w.destinations" :key="target.id" :value="target.id">
              {{ target.name }}
            </option>
          </select></label
        >
      </div>
      <div class="row wrap">
        <ChangeQueuePrinter
          v-if="auth.can('queue.change_printer') && auth.anyPrinter('manage_queue')"
          :jobs="selectedJobs"
          :copy-ids="selectedIds"
          :loading="loading"
          @changed="printerChanged"
        />
        <button
          v-if="auth.anyPrinter('start_own') || auth.anyPrinter('start_any')"
          class="primary"
          :disabled="!canPrintSelection || loading"
          @click="printSelected"
        >
          {{ $t('common.printSelected') }}{{ selectedIds.length }})
        </button>
        <button
          class="secondary danger-text"
          :disabled="!selectedIds.length || !selectedJobs.every(canCancel) || w.busy || loading"
          @click="removeSelected"
        >
          {{ $t('jobs.removeSelected') }}{{ selectedIds.length }})
        </button>
      </div>
    </div>
    <p
      v-if="
        selectedDestination &&
        auth.printer(selectedDestination, 'start_any') &&
        auth.printer(selectedDestination, 'hold_resume')
      "
      class="help"
    >
      {{ $t('jobs.printingRequiresTheInstalledTapePrintingASelectionHolds') }}
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
                  :aria-label="$t('common.selectAllQueuedItemsOnThisPage')"
                  :checked="checked(jobs)"
                  :indeterminate="partial(jobs)"
                  :disabled="!selectable(jobs).length || loading"
                  @change="toggle(jobs, $event)"
              /></label>
            </th>
            <th>{{ $t('jobs.process') }}</th>
            <th>{{ $t('common.tape') }}</th>
            <th>{{ $t('common.copies') }}</th>
            <th>{{ $t('common.status') }}</th>
            <th>
              <span class="sr-only">{{ $t('common.actions') }}</span>
            </th>
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
                      :aria-label="$t('uiDetails.selectRun', { value1: String(group.name) })"
                      :checked="checked(group.jobs)"
                      :indeterminate="partial(group.jobs)"
                      :disabled="!selectable(group.jobs).length || loading"
                      @change="toggle(group.jobs, $event)"
                  /></label>
                  <button
                    class="queue-disclosure"
                    :aria-label="$t('uiDetails.toggle', { value1: String(group.name) })"
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
                ><small>{{ group.jobs.length }} {{ $t('common.matchingLabels') }}</small>
                <PaymentAttribution :payers="group.jobs.flatMap((job) => job.payers ?? [])" />
                <CostEstimate :estimate="group.cost_estimate" />
                <AnimatedDetails class="queue-label-details">
                  <template #summary>{{ $t('common.details') }}</template>
                  <TapeUsage
                    :plan="group.print_plan"
                    :caption="
                      group.print_plan_scope === 'queued'
                        ? $t('uiMessages.queuedCopiesIfPrintedAsOneBatch')
                        : $t('uiMessages.savedSubmissionEstimate')
                    "
                  />
                </AnimatedDetails>
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
                {{ $t('common.queued') }}
              </td>
              <td>
                <Badge
                  :state="
                    new Set(group.jobs.map(displayState)).size === 1
                      ? displayState(group.jobs[0]!)
                      : 'mixed'
                  "
                />
              </td>
              <td class="queue-run-actions">
                <RouterLink :to="`/runs/${group.run_id}`">{{ $t('common.viewRun') }}</RouterLink>
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
                          :aria-label="
                            $t('uiDetails.select', {
                              value1: String(
                                job.payload.text ||
                                  (job.source_row
                                    ? $t('uiRemainder.csvRecord', { record: job.source_row })
                                    : labelName(job)),
                              ),
                            })
                          "
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
                      ><small
                        >{{ date(job.created_at) }} · {{ job.length_mm }}
                        {{ $t('common.mm') }}</small
                      ><small>{{ routing(job) }}</small>
                      <PaymentAttribution :payers="job.payers" />
                      <RouterLink
                        v-if="job.billing_request"
                        :to="{
                          path: '/group-accounts',
                          query: {
                            account: job.billing_request.account_id,
                            request: job.billing_request.id,
                          },
                        }"
                        >{{ $t('jobs.groupFunding') }}</RouterLink
                      >
                      <CostEstimate v-if="!group.run_id" :estimate="group.cost_estimate" />
                      <RouterLink v-if="job.run_id" :to="`/runs/${job.run_id}`"
                        >{{ $t('common.csvRecord') }} {{ job.source_row }}</RouterLink
                      >
                      <AnimatedDetails class="queue-label-details">
                        <template #summary>{{ $t('common.details') }}</template>
                        <LabelDetails :label="job" :attribution="job.attribution" />
                        <label v-if="job.owner_id === auth.user?.id" class="checkbox">
                          <input
                            type="checkbox"
                            :checked="job.notify_on_completion"
                            :disabled="w.busy"
                            @change="changeCompletionNotification(job, $event)"
                          />{{ $t('common.notifyWhenPrinted') }}
                        </label>
                        <TapeUsage
                          v-if="!group.run_id"
                          :plan="group.print_plan"
                          :caption="
                            group.print_plan_scope === 'queued'
                              ? $t('uiMessages.queuedCopiesIfPrintedAsOneBatch')
                              : $t('uiMessages.savedSubmissionEstimate')
                          "
                        />
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
                      {{ w.profileName(job.profile_id)
                      }}<small>{{ job.width_mm }} {{ $t('common.mm') }}</small>
                    </div>
                  </div>
                </td>
                <td>
                  <div class="queue-cell">
                    <div class="queue-cell-content">
                      {{ job.copies
                      }}<small
                        >{{ job.labels.filter((l) => l.state === 'queued').length }}
                        {{ $t('common.queued') }}</small
                      >
                      <ChangeCopies
                        v-if="job.can_change_copies"
                        :url="`/jobs/${job.id}/copies`"
                        :copies="job.copies"
                        :disabled="loading"
                        @changed="load(false, true)"
                      />
                    </div>
                  </div>
                </td>
                <td>
                  <div class="queue-cell">
                    <div class="queue-cell-content"><Badge :state="displayState(job)" /></div>
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
                        {{ $t('common.remove') }}</button
                      ><RouterLink
                        v-else-if="
                          job.status === 'needs_review' &&
                          w.printers.some((p) => auth.printer(p.id, 'manage_queue'))
                        "
                        to="/activity"
                        >{{ $t('common.reviewBatch') }}</RouterLink
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
      <h3>
        {{ $t('common.no') }} {{ filter ? filter.replaceAll('_', ' ') : '' }}
        {{ $t('common.labelsHere') }}
      </h3>
      <RouterLink class="button secondary" to="/new">{{ $t('jobs.createALabel') }}</RouterLink>
    </div>
    <div class="pagination">
      <span>{{ $t('common.page') }} {{ page + 1 }} {{ $t('common.upTo25ItemsOrRunsPerPage') }}</span
      ><button :disabled="page === 0 || loading" @click="page--">{{ $t('common.previous') }}</button
      ><button :disabled="groups.length < 25 || loading" @click="page++">
        {{ $t('common.next') }}
      </button>
    </div>
  </section>
</template>

<style scoped>
.queue-table :deep(.status-badge) {
  max-width: 100%;
  white-space: normal;
  overflow-wrap: anywhere;
}
.queue-cell-content {
  min-width: 0;
}
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
