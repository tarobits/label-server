<script setup lang="ts">
import { computed } from 'vue'
import { useWorkspaceStore, date, metres } from '../workspace'
import { api } from '../api'
import { requestPrinting } from '../printing'
import { useAuthStore } from '../auth'
import type { Destination } from '../types'
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
    current.detected_width_mm === installed.width_mm &&
    destination(id)?.queues.some(
      (queue) => queue.profile_id === installed.id && queue.queued_copies > 0,
    )
  )
}
async function hold(id: string, held: boolean) {
  await w.action(
    () => api(`/destinations/${encodeURIComponent(id)}/automatic-printing`, 'PUT', { held }),
    `${w.destinationName(id)}: automatic printing ${held ? 'held' : 'resumed'}.`,
  )
}
async function print(id: string) {
  await w.action(
    () => requestPrinting(`/destinations/${encodeURIComponent(id)}/print`),
    `${w.destinationName(id)}: matching queued labels requested for printing.`,
  )
}
async function stopPrinter(id: string, mode: 'after_current' | 'emergency') {
  await w.action(
    () => api(`/printers/${encodeURIComponent(id)}/stop`, 'POST', { mode }),
    `${w.destinationName(id)}: ${mode === 'emergency' ? 'emergency stop' : 'stop after current label'} requested. Automatic printing is held.`,
  )
}
const printerName = (id: string) => w.printers.find((device) => device.id === id)?.name ?? id
</script>

<template>
  <div v-if="!w.printers.length && !groups.length" class="panel empty">
    <h2>
      {{ auth.can('printers.manage') ? 'Add your first printer' : 'No printers assigned yet' }}
    </h2>
    <p v-if="!auth.can('printers.manage')">
      Ask your administrator to assign you a role with access to a printer or distribution group.
    </p>
    <RouterLink v-if="auth.can('printers.manage')" class="button primary" to="/printers"
      >Set up printers</RouterLink
    >
  </div>
  <div class="stats-grid fleet-stats" :class="{ 'groups-only': !w.printers.length }">
    <article class="stat" aria-label="Queued labels">
      <span>QUEUED LABELS</span><strong>{{ w.totalQueued }}<small>copies</small></strong>
    </article>
    <template v-if="w.printers.length">
      <article class="stat" aria-label="Connected printers">
        <span>CONNECTED PRINTERS</span
        ><strong
          >{{ connected }}<small>/ {{ w.printers.length }}</small></strong
        >
      </article>
      <article class="stat" aria-label="Printing now">
        <span>PRINTING NOW</span><strong>{{ printing }}<small>printers</small></strong>
        <p>{{ pending }} manual {{ pending === 1 ? 'batch' : 'batches' }} waiting to start</p>
      </article>
      <article class="stat" aria-label="Printers needing review">
        <span>NEEDS YOUR REVIEW</span><strong>{{ reviews }}<small>printers</small></strong>
      </article>
    </template>
    <article v-else class="stat" aria-label="Distribution groups">
      <span>DISTRIBUTION GROUPS</span><strong>{{ groups.length }}</strong>
    </article>
  </div>

  <section v-if="w.printers.length" aria-labelledby="fleet-printers-title">
    <div class="section-heading">
      <div>
        <h2 id="fleet-printers-title">Your printers</h2>
      </div>
      <RouterLink v-if="auth.can('printers.manage')" to="/printers" class="text-link"
        >Manage printers →</RouterLink
      >
    </div>
    <div class="fleet-grid">
      <article
        v-for="device in w.printers"
        :key="device.id"
        class="panel fleet-card"
        :aria-label="`Printer ${device.name}`"
      >
        <div class="section-heading fleet-card-heading">
          <div class="fleet-title">
            <Icon name="printer" />
            <h3>{{ device.name }}</h3>
          </div>
          <span class="badge" :class="state(device.id)?.connected ? 'printed' : 'failed'">{{
            state(device.id)?.connected ? 'Connected' : 'Disconnected'
          }}</span>
        </div>
        <div class="row wrap fleet-state">
          <span class="badge" v-if="state(device.id)?.printing">Printing</span>
          <span class="badge failed" v-if="state(device.id)?.needs_review.length"
            >Review needed</span
          >
          <span class="badge" v-if="state(device.id)?.pending_flush">Manual batch pending</span>
          <span class="muted">{{
            state(device.id)?.automatic_printing_held
              ? 'Automatic printing held'
              : 'Automatic printing enabled'
          }}</span>
        </div>
        <div class="fleet-tape">
          <span
            class="swatch"
            :style="{
              background: profile(device.id)?.background ?? 'var(--surface-secondary)',
              color: profile(device.id)?.foreground ?? 'var(--text-secondary)',
            }"
            >Aa</span
          >
          <div>
            <small>INSTALLED TAPE</small
            ><strong>{{ profile(device.id)?.name ?? 'No cartridge selected' }}</strong
            ><span>{{
              cartridge(device.id)?.name ?? 'Install a cartridge to print matching labels'
            }}</span>
          </div>
        </div>
        <dl class="fleet-metrics">
          <div>
            <dt>Direct queue</dt>
            <dd>{{ queued(directQueue(device.id)) }} <small>copies</small></dd>
          </div>
          <div>
            <dt>Approximate tape remaining</dt>
            <dd>{{ cartridge(device.id) ? metres(cartridge(device.id)!.remaining_mm) : '—' }}</dd>
          </div>
        </dl>
        <p v-if="cartridge(device.id)?.consumption_uncertain" class="inline-warning">
          Tape remaining is uncertain until the interrupted batch is reviewed.
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
            state(device.id)?.detected_width_mm !== profile(device.id)?.width_mm
          "
          class="inline-warning"
        >
          Detected tape width does not match the installed {{ profile(device.id)?.width_mm }} mm
          profile.
        </p>
        <p v-else-if="state(device.id)?.blocker" class="inline-warning">
          {{ state(device.id)?.blocker }}
        </p>
        <div class="fleet-queue">
          <p class="help">Direct queue · copies / threshold</p>
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
          <p v-if="!queued(directQueue(device.id))" class="help">No direct copies waiting.</p>
        </div>
        <div class="fleet-actions">
          <div class="row wrap">
            <RouterLink
              v-if="auth.atLeast(device.id, 'request')"
              class="button secondary"
              :to="{ path: '/new', query: { destination: device.id } }"
              >{{
                auth.atLeast(device.id, 'print') ? 'Print a label' : 'Request printing'
              }}</RouterLink
            >
            <RouterLink
              class="button secondary"
              :to="{ path: '/queue', query: { destination: device.id } }"
              >View direct queue</RouterLink
            >
            <RouterLink
              v-if="auth.atLeast(device.id, 'full')"
              class="button secondary"
              :to="{ path: '/printers', query: { printer: device.id } }"
              >Configure</RouterLink
            >
          </div>
          <template v-if="auth.atLeast(device.id, 'moderator')">
            <div class="row wrap">
              <button
                class="primary"
                :disabled="!canPrintDirect(device.id)"
                @click="print(device.id)"
              >
                <Icon name="printer" />Print direct queue
              </button>
              <button
                class="secondary"
                :disabled="w.busy || !!state(device.id)?.stop_requested"
                @click="hold(device.id, !state(device.id)?.automatic_printing_held)"
              >
                {{
                  state(device.id)?.automatic_printing_held
                    ? 'Resume automatic printing'
                    : 'Hold automatic printing'
                }}
              </button>
            </div>
            <div v-if="device.capabilities?.supports_stop_after_current" class="row wrap">
              <button
                class="secondary"
                :disabled="
                  w.busy ||
                  !!w.connectionError ||
                  (!state(device.id)?.printing && !state(device.id)?.pending_flush) ||
                  !!state(device.id)?.stop_requested
                "
                @click="stopPrinter(device.id, 'after_current')"
              >
                Stop after current label
              </button>
              <button
                v-if="
                  auth.atLeast(device.id, 'full') && device.capabilities?.supports_emergency_stop
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
                Emergency stop
              </button>
              <button
                v-if="auth.atLeast(device.id, 'full') && device.driver === 'brother-pt-p710bt'"
                class="secondary"
                disabled
              >
                Cut tape
              </button>
            </div>
            <p v-if="state(device.id)?.stop_requested" class="alert warning" role="status">
              {{
                state(device.id)?.stop_requested === 'emergency'
                  ? 'Emergency stop requested. The current label may finish. Review the batch before printing again.'
                  : 'Stopping after the current label. The remaining batch will need review.'
              }}
            </p>
            <p
              v-if="auth.atLeast(device.id, 'full') && device.capabilities?.supports_emergency_stop"
              class="help"
            >
              Emergency stop may allow the current label to finish. Review all output before
              printing again.
            </p>
            <p
              v-if="auth.atLeast(device.id, 'full') && device.driver === 'brother-pt-p710bt'"
              class="help"
            >
              Manual cut over USB is unavailable. While idle, double-press the printer’s power
              button to feed and cut.
            </p>
            <RouterLink
              v-for="batchId in state(device.id)?.needs_review ?? []"
              :key="batchId"
              class="button secondary"
              :to="`/batches/${batchId}`"
              >Review interrupted batch</RouterLink
            >
          </template>
        </div>
      </article>
    </div>
  </section>

  <section v-if="groups.length" aria-labelledby="fleet-groups-title">
    <div class="section-heading">
      <div>
        <h2 id="fleet-groups-title">Distribution groups</h2>
      </div>
    </div>
    <div class="fleet-grid">
      <article
        v-for="group in groups"
        :key="group.id"
        class="panel fleet-card"
        :aria-label="`Distribution group ${group.name}`"
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
                ? 'Unavailable'
                : group.automatic_printing_held
                  ? 'Held'
                  : 'Automatic routing'
            }}</span
          >
        </div>
        <p v-if="group.available === false" class="help">
          No configured member printer is available. Existing labels remain queued.
        </p>
        <p class="help">
          {{ group.printer_ids.length }} member
          {{ group.printer_ids.length === 1 ? 'printer' : 'printers' }} · copies / threshold
        </p>
        <dl class="fleet-metrics">
          <div>
            <dt>Group queue</dt>
            <dd>{{ queued(group) }} <small>copies</small></dd>
          </div>
        </dl>
        <div class="fleet-queue">
          <div v-for="queue in waiting(group)" :key="queue.profile_id" class="fleet-queue-row">
            <span>{{ w.profileName(queue.profile_id) }}</span
            ><strong
              >{{ queue.queued_copies }} <small>/ {{ queue.threshold }}</small></strong
            >
          </div>
          <p v-if="!queued(group)" class="help">No group copies waiting.</p>
        </div>
        <div class="fleet-actions">
          <div class="row wrap">
            <RouterLink
              v-if="group.available !== false"
              class="button secondary"
              :to="{ path: '/new', query: { destination: group.id } }"
              >{{
                auth.atLeast(group.id, 'print') ? 'Print a label' : 'Request printing'
              }}</RouterLink
            >
            <button v-else class="secondary" disabled>
              {{ auth.atLeast(group.id, 'print') ? 'Print a label' : 'Request printing' }}
            </button>
            <RouterLink
              class="button secondary"
              :to="{ path: '/queue', query: { destination: group.id } }"
              >View group queue</RouterLink
            >
            <RouterLink
              v-if="auth.atLeast(group.id, 'full')"
              class="button secondary"
              to="/printers"
              >Configure group</RouterLink
            >
          </div>
          <div v-if="auth.atLeast(group.id, 'moderator')" class="row wrap">
            <button
              class="primary"
              :disabled="
                group.available === false || w.busy || !!w.connectionError || !queued(group)
              "
              @click="print(group.id)"
            >
              <Icon name="printer" />Print group queue
            </button>
            <button
              class="secondary"
              :disabled="w.busy"
              @click="hold(group.id, !group.automatic_printing_held)"
            >
              {{ group.automatic_printing_held ? 'Resume group' : 'Hold group' }}
            </button>
          </div>
        </div>
      </article>
    </div>
  </section>

  <section v-if="recentBatches.length" class="panel">
    <div class="section-heading">
      <h2>Recent batches</h2>
      <RouterLink class="text-link" to="/activity">All activity →</RouterLink>
    </div>
    <div v-for="batch in recentBatches" :key="batch.id" class="list-row">
      <div>
        <strong>{{ printerName(batch.printer_id) }}</strong
        ><small>{{ w.cartridgeName(batch.cartridge_id) }} · {{ date(batch.created_at) }}</small>
      </div>
      <Badge :state="batch.state" /><RouterLink :to="`/batches/${batch.id}`">{{
        batch.state === 'needs_review' ? 'Review →' : 'Details →'
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
