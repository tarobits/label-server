<script setup lang="ts">
import { t } from '../shared/i18n'
import { computed } from 'vue'
import { useWorkspaceStore, date, metres } from '../shared/workspace'
import { api } from '../shared/api'
import { requestPrinting } from '../printing/printing'
import { useAuthStore } from '../auth/auth'
import type { Destination } from '../shared/types'
import Badge from '../components/Badge.vue'
import Icon from '../components/Icon.vue'

const w = useWorkspaceStore()
const auth = useAuthStore()
const state = (id: string) => w.printerStatuses.find((item) => item.printer_id === id)
const destination = (id: string) => w.destinations.find((item) => item.id === id)
const cartridge = (id: string) =>
  w.cartridges.find((item) => item.id === state(id)?.active_cartridge_id)
const profile = (id: string) => w.profiles.find((item) => item.id === cartridge(id)?.profile_id)
const groups = computed(() => w.destinations.filter((item) => item.kind === 'group'))
const directQueue = (id: string) => destination(id) ?? state(id)
const queued = (target?: Pick<Destination, 'queues'>) =>
  target?.queues.reduce((total, queue) => total + queue.queued_copies, 0) ?? 0
const waiting = (target?: Pick<Destination, 'queues'>) =>
  target?.queues.filter((q) => q.queued_copies > 0) ?? []
const connected = computed(() => w.printerStatuses.filter((item) => item.connected).length)
const printing = computed(() => w.printerStatuses.filter((item) => item.printing).length)
const pending = computed(() => w.printerStatuses.filter((item) => item.pending_flush).length)
const reviews = computed(
  () => w.printerStatuses.filter((item) => item.needs_review.length > 0).length,
)
const recentBatches = computed(() => w.batches.slice(0, 4))
function canPrintDirect(id: string) {
  const current = state(id),
    installed = profile(id)
  return (
    !w.busy &&
    !w.connectionError &&
    current?.connected &&
    !current.printer_error &&
    !current.printing &&
    !current.pending_flush &&
    !current.needs_review.length &&
    installed &&
    (current.effective_width_mm ?? current.detected_width_mm) === installed.width_mm &&
    destination(id)?.queues.some(
      (queue) => queue.profile_id === installed.id && queue.queued_copies > 0,
    )
  )
}
async function hold(id: string, held: boolean) {
  await w.action(
    () => api(`/destinations/${encodeURIComponent(id)}/automatic-printing`, 'PUT', { held }),
    t(held ? 'uiRemainder.held' : 'uiRemainder.resumed', { name: w.destinationName(id) }),
  )
}
async function print(id: string) {
  await w.action(
    () => requestPrinting(`/destinations/${encodeURIComponent(id)}/print`),
    t('uiDetails.requestMatchingLabels', { value1: String(w.destinationName(id)) }),
  )
}
async function stopPrinter(id: string, mode: 'after_current' | 'emergency') {
  await w.action(
    () => api(`/printers/${encodeURIComponent(id)}/stop`, 'POST', { mode }),
    t(mode === 'emergency' ? 'uiRemainder.emergency' : 'uiRemainder.stop', {
      name: w.destinationName(id),
    }),
  )
}
const printerName = (id: string) => w.printers.find((device) => device.id === id)?.name ?? id
</script>

<template>
  <div v-if="!w.printers.length && !groups.length" class="panel empty">
    <h2>
      {{
        auth.can('printers.manage')
          ? $t('uiMessages.addYourFirstPrinter')
          : $t('uiMessages.noPrintersAssignedYet')
      }}
    </h2>
    <p v-if="!auth.can('printers.manage')">
      {{ $t('common.askYourAdministratorToAssignYouARoleWith') }}
    </p>
    <RouterLink v-if="auth.can('printers.manage')" class="button primary" to="/printers">{{
      $t('common.setUpPrinters')
    }}</RouterLink>
  </div>
  <div class="stats-grid fleet-stats" :class="{ 'groups-only': !w.printers.length }">
    <article class="stat" :aria-label="$t('common.queuedLabels')">
      <span>{{ $t('dashboard.queuedLabels') }}</span
      ><strong
        >{{ w.totalQueued }}<small>{{ $t('common.copies2') }}</small></strong
      >
    </article>
    <template v-if="w.printers.length">
      <article class="stat" :aria-label="$t('common.connectedPrinters')">
        <span>{{ $t('dashboard.connectedPrinters') }}</span
        ><strong
          >{{ connected }}<small>/ {{ w.printers.length }}</small></strong
        >
      </article>
      <article class="stat" :aria-label="$t('dashboard.printingNow2')">
        <span>{{ $t('dashboard.printingNow') }}</span
        ><strong
          >{{ printing }}<small>{{ $t('common.printers2') }}</small></strong
        >
        <p>
          {{ pending }} {{ $t('common.manual') }} {{ pending === 1 ? 'batch' : 'batches' }}
          {{ $t('common.waitingToStart') }}
        </p>
      </article>
      <article class="stat" :aria-label="$t('dashboard.printersNeedingReview')">
        <span>{{ $t('dashboard.needsYourReview') }}</span
        ><strong
          >{{ reviews }}<small>{{ $t('common.printers2') }}</small></strong
        >
      </article>
    </template>
    <article v-else class="stat" :aria-label="$t('dashboard.distributionGroups2')">
      <span>{{ $t('dashboard.distributionGroups') }}</span
      ><strong>{{ groups.length }}</strong>
    </article>
  </div>

  <section v-if="w.printers.length" aria-labelledby="fleet-printers-title">
    <div class="section-heading">
      <div>
        <h2 id="fleet-printers-title">{{ $t('common.yourPrinters') }}</h2>
      </div>
      <RouterLink v-if="auth.can('printers.manage')" to="/printers" class="text-link">{{
        $t('dashboard.managePrinters')
      }}</RouterLink>
    </div>
    <div class="fleet-grid">
      <article
        v-for="device in w.printers"
        :key="device.id"
        class="panel fleet-card"
        :aria-label="$t('uiDetails.printer', { value1: String(device.name) })"
      >
        <div class="section-heading fleet-card-heading">
          <div class="fleet-title">
            <Icon name="printer" />
            <h3>{{ device.name }}</h3>
          </div>
          <span class="badge" :class="state(device.id)?.connected ? 'printed' : 'failed'">{{
            state(device.id)?.connected ? $t('uiMessages.connected') : $t('uiMessages.disconnected')
          }}</span>
        </div>
        <div class="row wrap fleet-state">
          <span class="badge" v-if="state(device.id)?.printing">{{
            $t('dashboard.printing')
          }}</span>
          <span class="badge failed" v-if="state(device.id)?.needs_review.length">{{
            $t('dashboard.reviewNeeded')
          }}</span>
          <span class="badge" v-if="state(device.id)?.pending_flush">{{
            $t('dashboard.manualBatchPending')
          }}</span>
          <span class="muted">{{
            device.no_automatic_printing
              ? $t('printers.manualOnly')
              : state(device.id)?.automatic_printing_held
                ? $t('uiMessages.automaticPrintingHeld')
                : $t('uiMessages.automaticPrintingEnabled')
          }}</span>
        </div>
        <div class="fleet-tape">
          <span
            class="swatch"
            :style="{
              background: profile(device.id)?.background ?? 'var(--surface-secondary)',
              color: profile(device.id)?.foreground ?? 'var(--text-secondary)',
            }"
            >{{ $t('common.aa') }}</span
          >
          <div>
            <small>{{ $t('dashboard.installedTape') }}</small
            ><strong>{{ profile(device.id)?.name ?? $t('uiMessages.noCartridgeSelected') }}</strong
            ><span>{{
              cartridge(device.id)?.name ?? $t('uiMessages.installACartridgeToPrintMatchingLabels')
            }}</span>
          </div>
        </div>
        <dl class="fleet-metrics">
          <div>
            <dt>{{ $t('dashboard.directQueue') }}</dt>
            <dd>
              {{ queued(directQueue(device.id)) }} <small>{{ $t('common.copies2') }}</small>
            </dd>
          </div>
          <div>
            <dt>{{ $t('dashboard.approximateTapeRemaining') }}</dt>
            <dd>{{ cartridge(device.id) ? metres(cartridge(device.id)!.remaining_mm) : '—' }}</dd>
          </div>
        </dl>
        <p v-if="cartridge(device.id)?.consumption_uncertain" class="inline-warning">
          {{ $t('common.tapeRemainingIsUncertainUntilTheInterruptedBatchIs') }}
        </p>
        <p
          v-if="device.configuration_error || state(device.id)?.printer_error"
          class="inline-warning"
        >
          {{ device.configuration_error || state(device.id)?.printer_error }}
        </p>
        <p
          v-else-if="
            profile(device.id) &&
            state(device.id)?.connected &&
            state(device.id)?.detected_width_mm != null &&
            !state(device.id)?.media_confirmed &&
            state(device.id)?.detected_width_mm !== profile(device.id)?.width_mm
          "
          class="inline-warning"
        >
          {{ $t('dashboard.detectedTapeWidthDoesNotMatchTheInstalled') }}
          {{ profile(device.id)?.width_mm }} {{ $t('common.mmProfile') }}
        </p>
        <p v-else-if="state(device.id)?.blocker" class="inline-warning">
          {{ state(device.id)?.blocker }}
        </p>
        <div class="fleet-queue">
          <p class="help">{{ $t('dashboard.directQueueCopiesThreshold') }}</p>
          <div
            v-for="queue in waiting(directQueue(device.id))"
            :key="queue.profile_id"
            class="fleet-queue-row"
          >
            <span>{{ w.profileName(queue.profile_id) }}</span
            ><strong
              >{{ queue.queued_copies }} <small>/ {{ queue.threshold }}</small></strong
            >
          </div>
          <p v-if="!queued(directQueue(device.id))" class="help">
            {{ $t('dashboard.noDirectCopiesWaiting') }}
          </p>
        </div>
        <div class="fleet-actions">
          <div class="row wrap">
            <RouterLink
              v-if="auth.printer(device.id, 'view')"
              class="button secondary"
              :to="{ path: '/new', query: { destination: device.id } }"
              >{{
                auth.printer(device.id, 'submit_directly')
                  ? $t('printers.printALabel')
                  : $t('uiMessages.requestPrinting')
              }}</RouterLink
            >
            <RouterLink
              class="button secondary"
              :to="{ path: '/queue', query: { destination: device.id } }"
              >{{ $t('common.viewDirectQueue') }}</RouterLink
            >
            <RouterLink
              v-if="auth.printer(device.id, 'configure')"
              class="button secondary"
              :to="{ path: '/printers', query: { printer: device.id } }"
              >{{ $t('common.configure') }}</RouterLink
            >
          </div>
          <template
            v-if="
              ['start_any', 'hold_resume', 'stop_after_label', 'emergency_stop', 'review'].some(
                (permission) => auth.printer(device.id, permission),
              )
            "
          >
            <div class="row wrap">
              <button
                v-if="auth.printer(device.id, 'start_any')"
                class="primary"
                :disabled="!canPrintDirect(device.id)"
                @click="print(device.id)"
              >
                <Icon name="printer" />{{ $t('dashboard.printDirectQueue') }}
              </button>
              <button
                v-if="!device.no_automatic_printing && auth.printer(device.id, 'hold_resume')"
                class="secondary"
                :disabled="w.busy || !!state(device.id)?.stop_requested"
                @click="hold(device.id, !state(device.id)?.automatic_printing_held)"
              >
                {{
                  state(device.id)?.automatic_printing_held
                    ? $t('uiMessages.resumeAutomaticPrinting')
                    : $t('uiMessages.holdAutomaticPrinting')
                }}
              </button>
            </div>
            <div class="row wrap">
              <button
                v-if="
                  auth.printer(device.id, 'stop_after_label') &&
                  device.capabilities?.supports_stop_after_current
                "
                class="secondary"
                :disabled="
                  w.busy ||
                  !!w.connectionError ||
                  (!state(device.id)?.printing && !state(device.id)?.pending_flush) ||
                  !!state(device.id)?.stop_requested
                "
                @click="stopPrinter(device.id, 'after_current')"
              >
                {{ $t('common.stopAfterCurrentLabel') }}
              </button>
              <button
                v-if="
                  auth.printer(device.id, 'emergency_stop') &&
                  device.capabilities?.supports_emergency_stop
                "
                class="danger"
                :disabled="
                  w.busy ||
                  !!w.connectionError ||
                  !state(device.id)?.printing ||
                  state(device.id)?.stop_requested === 'emergency'
                "
                @click="stopPrinter(device.id, 'emergency')"
              >
                {{ $t('common.emergencyStop') }}
              </button>
              <button
                v-if="auth.printer(device.id, 'configure') && device.driver === 'brother-pt-p710bt'"
                class="secondary"
                disabled
              >
                {{ $t('dashboard.cutTape') }}
              </button>
            </div>
            <p v-if="state(device.id)?.stop_requested" class="alert warning" role="status">
              {{
                state(device.id)?.stop_requested === 'emergency'
                  ? $t(
                      'uiMessages.emergencyStopRequestedTheCurrentLabelMayFinishReviewTheBatchBeforePrintingAgain',
                    )
                  : $t('uiMessages.stoppingAfterTheCurrentLabelTheRemainingBatchWillNeedReview')
              }}
            </p>
            <p
              v-if="
                auth.printer(device.id, 'emergency_stop') &&
                device.capabilities?.supports_emergency_stop
              "
              class="help"
            >
              {{ $t('dashboard.emergencyStopMayAllowTheCurrentLabelToFinish') }}
            </p>
            <p
              v-if="auth.printer(device.id, 'configure') && device.driver === 'brother-pt-p710bt'"
              class="help"
            >
              {{ $t('dashboard.manualCutOverUsbIsUnavailableWhileIdleDouble') }}
            </p>
            <RouterLink
              v-for="batchId in state(device.id)?.needs_review ?? []"
              :key="batchId"
              class="button secondary"
              :to="`/batches/${batchId}`"
              >{{ $t('common.reviewInterruptedBatch') }}</RouterLink
            >
          </template>
        </div>
      </article>
    </div>
  </section>

  <section v-if="groups.length" aria-labelledby="fleet-groups-title">
    <div class="section-heading">
      <div>
        <h2 id="fleet-groups-title">{{ $t('dashboard.distributionGroups2') }}</h2>
      </div>
    </div>
    <div class="fleet-grid">
      <article
        v-for="group in groups"
        :key="group.id"
        class="panel fleet-card"
        :aria-label="$t('uiDetails.distributionGroup', { value1: String(group.name) })"
      >
        <div class="section-heading fleet-card-heading">
          <div class="fleet-title">
            <Icon name="overview" />
            <h3>{{ group.name }}</h3>
          </div>
          <span
            class="badge"
            :class="
              group.available === false ? '' : group.automatic_printing_held ? 'queued' : 'printed'
            "
            >{{
              group.available === false
                ? $t('common.unavailable')
                : group.automatic_printing_held
                  ? $t('uiMessages.held')
                  : $t('uiMessages.automaticRouting')
            }}</span
          >
        </div>
        <p v-if="group.available === false" class="help">
          {{ $t('dashboard.noConfiguredMemberPrinterIsAvailableExistingLabelsRemain') }}
        </p>
        <p class="help">
          {{ group.printer_ids.length }} {{ $t('common.member') }}
          {{ group.printer_ids.length === 1 ? 'printer' : $t('common.printers2') }}
          {{ $t('common.copiesThreshold') }}
        </p>
        <dl class="fleet-metrics">
          <div>
            <dt>{{ $t('dashboard.groupQueue') }}</dt>
            <dd>
              {{ queued(group) }} <small>{{ $t('common.copies2') }}</small>
            </dd>
          </div>
        </dl>
        <div class="fleet-queue">
          <div v-for="queue in waiting(group)" :key="queue.profile_id" class="fleet-queue-row">
            <span>{{ w.profileName(queue.profile_id) }}</span
            ><strong
              >{{ queue.queued_copies }} <small>/ {{ queue.threshold }}</small></strong
            >
          </div>
          <p v-if="!queued(group)" class="help">{{ $t('dashboard.noGroupCopiesWaiting') }}</p>
        </div>
        <div class="fleet-actions">
          <div class="row wrap">
            <RouterLink
              v-if="group.available !== false"
              class="button secondary"
              :to="{ path: '/new', query: { destination: group.id } }"
              >{{
                auth.printer(group.id, 'submit_directly')
                  ? $t('printers.printALabel')
                  : $t('uiMessages.requestPrinting')
              }}</RouterLink
            >
            <button v-else class="secondary" disabled>
              {{
                auth.printer(group.id, 'submit_directly')
                  ? $t('printers.printALabel')
                  : $t('uiMessages.requestPrinting')
              }}
            </button>
            <RouterLink
              class="button secondary"
              :to="{ path: '/queue', query: { destination: group.id } }"
              >{{ $t('common.viewGroupQueue') }}</RouterLink
            >
            <RouterLink
              v-if="auth.printer(group.id, 'configure')"
              class="button secondary"
              to="/printers"
              >{{ $t('dashboard.configureGroup') }}</RouterLink
            >
          </div>
          <div
            v-if="auth.printer(group.id, 'start_any') || auth.printer(group.id, 'hold_resume')"
            class="row wrap"
          >
            <button
              v-if="auth.printer(group.id, 'start_any')"
              class="primary"
              :disabled="
                group.available === false || w.busy || !!w.connectionError || !queued(group)
              "
              @click="print(group.id)"
            >
              <Icon name="printer" />{{ $t('dashboard.printGroupQueue') }}
            </button>
            <button
              v-if="!group.no_automatic_printing && auth.printer(group.id, 'hold_resume')"
              class="secondary"
              :disabled="w.busy"
              @click="hold(group.id, !group.automatic_printing_held)"
            >
              {{
                group.automatic_printing_held
                  ? $t('uiMessages.resumeGroup')
                  : $t('uiMessages.holdGroup')
              }}
            </button>
          </div>
        </div>
      </article>
    </div>
  </section>

  <section v-if="recentBatches.length" class="panel">
    <div class="section-heading">
      <h2>{{ $t('dashboard.recentBatches') }}</h2>
      <RouterLink class="text-link" to="/activity">{{ $t('dashboard.allActivity') }}</RouterLink>
    </div>
    <div v-for="batch in recentBatches" :key="batch.id" class="list-row">
      <div>
        <strong>{{ printerName(batch.printer_id) }}</strong
        ><small>{{ w.cartridgeName(batch.cartridge_id) }} · {{ date(batch.created_at) }}</small>
      </div>
      <Badge :state="batch.state" /><RouterLink :to="`/batches/${batch.id}`">{{
        batch.state === 'needs_review' ? $t('uiMessages.review') : $t('uiMessages.details')
      }}</RouterLink>
    </div>
  </section>
</template>

<style scoped>
.fleet-stats {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}
.fleet-stats.groups-only {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
.fleet-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 22px;
  margin-bottom: 24px;
}
.fleet-card {
  display: flex;
  flex-direction: column;
  min-width: 0;
  margin-bottom: 0;
}
.fleet-card-heading {
  margin-bottom: 12px;
  align-items: start;
}
.fleet-title {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.fleet-title svg {
  flex-shrink: 0;
  color: var(--accent);
}
.fleet-title h3 {
  overflow-wrap: anywhere;
}
.fleet-state {
  font-size: 11px;
  min-height: 25px;
}
.fleet-tape {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 20px 0;
}
.fleet-tape > div {
  display: grid;
  gap: 4px;
  min-width: 0;
  overflow-wrap: anywhere;
}
.fleet-tape small {
  font-size: 9px;
  color: var(--muted);
  letter-spacing: 1px;
}
.fleet-tape span:not(.swatch) {
  font-size: 11px;
  color: var(--muted);
}
.fleet-metrics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  margin: 0 0 16px;
}
.fleet-metrics dt {
  color: var(--muted);
  font-size: 11px;
}
.fleet-metrics > div {
  display: block;
}
.fleet-metrics dd {
  margin: 6px 0 0;
  font-size: 23px;
  font-weight: 600;
  white-space: nowrap;
}
.fleet-metrics small {
  font-size: 12px;
  font-weight: 400;
  color: var(--muted);
}
.fleet-queue {
  border-top: 1px solid var(--line);
  padding-top: 12px;
  margin-bottom: 20px;
}
.fleet-queue-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 12px;
  margin-top: 10px;
  font-size: 12px;
}
.fleet-queue-row span {
  overflow-wrap: anywhere;
}
.fleet-queue-row strong {
  flex-shrink: 0;
}
.fleet-queue-row small {
  color: var(--muted);
  font-weight: 400;
}
.fleet-actions {
  display: grid;
  gap: 12px;
  margin-top: auto;
}
.fleet-actions .button,
.fleet-actions button {
  font-size: 12px;
}
@media (max-width: 1300px) {
  .fleet-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 1050px) {
  .fleet-grid {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 520px) {
  .fleet-stats,
  .fleet-stats.groups-only {
    grid-template-columns: 1fr;
  }
  .fleet-card-heading {
    flex-wrap: wrap;
  }
  .fleet-metrics {
    gap: 10px;
  }
}
</style>
