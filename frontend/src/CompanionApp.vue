<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api, configureSession, errorMessage } from './api'
import { ActionCancelled, ActionDeferred, confirmAction } from './confirmation'
import { installCartridge } from './cartridges'
import { requestPrinting } from './printing'
import { resolveCartridgeConsent } from './cartridgeConsent'
import { vValidateForm } from './formValidation'
import { freezeLeavingItem } from './collectionMotion'
import type { Cartridge, Job, Printer, Profile, Status } from './types'
import AdminDialog from './components/AdminDialog.vue'
import ExpandableContent from './components/ExpandableContent.vue'
import ConfirmDialog from './components/ConfirmDialog.vue'
import CartridgeConsent from './components/CartridgeConsent.vue'
import JobPreview from './components/JobPreview.vue'
import PinEntry from './components/PinEntry.vue'

interface LocalPrinter {
  local_id: string
  id: string | null
  name: string
  blocked: boolean
  printing: boolean
  can_stop: boolean
  status: { connected: boolean; tape_width_mm?: number | null; error?: string | null }
}
interface Operator {
  id: string
  username: string
  permissions: string[]
  location_id: string
  printer_permissions: Record<string, string[]>
  groups: Record<string, { name: string; printer_ids: string[] }>
}
interface Station {
  name: string
  online: boolean
  locked: boolean
  user: Operator | null
  users: { id: string; username: string }[]
  single_user_id: string | null
  pin_keypad: { enabled: boolean; shuffle: 'none' | 'once' | 'each_keypress' }
  lock_remaining_seconds: number | null
  printers: LocalPrinter[]
  removed_printers: { local_id: string; name: string }[]
  csrf_token: string
  stop_policy: Record<string, boolean>
}
const station = ref<Station>(),
  statuses = ref<Record<string, Status>>({}),
  devices = ref<Printer[]>([])
const error = ref(''),
  success = ref(''),
  busy = ref(false),
  unlocking = ref(false)
const userId = ref(''),
  pin = ref(''),
  selected = ref(''),
  destination = ref('')
const pinAttempt = ref(0)
const clock = ref(performance.now()),
  lockDeadline = ref(0)
let clockTimer: ReturnType<typeof setInterval> | undefined
const lockCountdown = computed(() => {
  const seconds = Math.max(0, Math.ceil((lockDeadline.value - clock.value) / 1000))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
})
function updateLockCountdown(remaining: number | null, started: number) {
  clock.value = performance.now()
  lockDeadline.value = started + (remaining ?? 0) * 1000
}
watch(userId, () => {
  pin.value = ''
})
const cartridges = ref<Cartridge[]>([]),
  profiles = ref<Profile[]>([]),
  allLocations = ref(false)
const cartridgeId = ref(''),
  jobs = ref<Job[]>([]),
  copyIds = ref<string[]>([])
const queuePage = ref(0),
  hasNextPage = ref(false)
const config = ref<Printer['config'] & { name: string; driver: string }>()
const newPrinterId = ref('')
const adding = ref(false),
  newName = ref(''),
  newProfile = ref(''),
  newLength = ref(8000),
  newPrice = ref(''),
  newCurrency = ref('EUR')
let timer: ReturnType<typeof setTimeout> | undefined,
  disposed = false,
  generation = 0,
  refreshBusy = false,
  lastTouch = 0,
  catalogUser = ''
const active = computed(() => station.value?.printers.find((p) => p.local_id === selected.value))
const status = computed(() => (active.value?.id ? statuses.value[active.value.id] : undefined))
const operational = computed(() => !!station.value?.online && !station.value.locked)
const can = (identifier: string | null | undefined, permission: string) =>
  !!identifier &&
  (station.value?.user?.printer_permissions[identifier] ?? []).includes(`printer.${permission}`)
const choices = computed(() =>
  cartridges.value.filter(
    (c) =>
      !c.archived &&
      (c.id === status.value?.active_cartridge_id || !c.installed) &&
      (allLocations.value ||
        c.location_id === station.value?.user?.location_id ||
        c.id === status.value?.active_cartridge_id),
  ),
)
const destinations = computed(() =>
  active.value?.id
    ? [
        { id: active.value.id, name: active.value.name },
        ...Object.entries(station.value?.user?.groups ?? {})
          .filter(([id, group]) => group.printer_ids.includes(active.value!.id!) && can(id, 'view'))
          .map(([id, group]) => ({ id, name: group.name })),
      ]
    : [],
)
const queuedCopies = (job: Job) =>
  job.labels.filter((label) => label.state === 'queued').map((label) => label.id)
function clearPrivate(clearPin = true) {
  generation++
  catalogUser = ''
  jobs.value = []
  copyIds.value = []
  statuses.value = {}
  devices.value = []
  cartridges.value = []
  profiles.value = []
  config.value = undefined
  adding.value = false
  selected.value = ''
  queuePage.value = 0
  if (clearPin) pin.value = ''
  resolveCartridgeConsent(null)
}
async function refresh() {
  if (disposed || refreshBusy) return
  refreshBusy = true
  const ticket = generation
  try {
    const started = performance.now()
    const state = await api<Station>('/station')
    if (disposed || ticket !== generation) return
    const changed = state.user?.id !== station.value?.user?.id
    station.value = state
    updateLockCountdown(state.lock_remaining_seconds, started)
    configureSession(state.csrf_token, () => {
      if (station.value) station.value.locked = true
      clearPrivate()
    })
    if (state.locked) {
      clearPrivate(changed)
      return
    }
    if (!state.online || !state.user) return
    if (changed) clearPrivate()
    if (active.value && !can(active.value.id, 'view')) {
      selected.value = ''
      jobs.value = []
      copyIds.value = []
    }
    const owner = JSON.stringify(state.user),
      requestGeneration = generation
    if (catalogUser !== owner) {
      cartridges.value = []
      profiles.value = []
      devices.value = []
      const [inventory, media, printers] = await Promise.all([
        api<Cartridge[]>('/proxy/cartridges'),
        api<Profile[]>('/proxy/tape-profiles'),
        api<Printer[]>('/proxy/printers'),
      ])
      if (disposed || requestGeneration !== generation) return
      cartridges.value = inventory
      profiles.value = media
      devices.value = printers
      catalogUser = owner
    }
    const values = await Promise.all(
      state.printers
        .filter((p) => can(p.id, 'view'))
        .map((p) => api<Status>(`/proxy/status?printer_id=${encodeURIComponent(p.id!)}`)),
    )
    if (disposed || requestGeneration !== generation) return
    statuses.value = Object.fromEntries(values.map((value) => [value.printer_id, value]))
    if (active.value && destination.value) await loadQueue(requestGeneration)
  } catch (issue) {
    if (!disposed) error.value = errorMessage(issue)
  } finally {
    refreshBusy = false
  }
}
async function loadQueue(ticket = generation) {
  if (!destination.value || !operational.value) return
  const page = queuePage.value,
    target = destination.value
  const groups = await api<{ jobs: Job[] }[]>(
    `/proxy/queue/groups?destination_id=${encodeURIComponent(target)}&copy_state=queued&limit=26&offset=${page * 25}`,
  )
  if (disposed || ticket !== generation || page !== queuePage.value || target !== destination.value)
    return
  hasNextPage.value = groups.length > 25
  jobs.value = groups.slice(0, 25).flatMap((group) => group.jobs)
  const available = new Set(jobs.value.filter((job) => job.can_print).flatMap(queuedCopies))
  copyIds.value = copyIds.value.filter((id) => available.has(id))
}
async function perform(task: () => Promise<unknown>, message: string) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  success.value = ''
  try {
    await task()
    if (!disposed) {
      success.value = message
      catalogUser = ''
      await refresh()
    }
  } catch (issue) {
    if (issue instanceof ActionDeferred && !disposed) success.value = issue.message
    if (!(issue instanceof ActionCancelled) && !disposed) error.value = errorMessage(issue)
  } finally {
    busy.value = false
  }
}
function openControls(printer: LocalPrinter) {
  selected.value = selected.value === printer.local_id ? '' : printer.local_id
  destination.value = printer.id ?? ''
  cartridgeId.value = printer.id ? (statuses.value[printer.id]?.active_cartridge_id ?? '') : ''
  allLocations.value = false
  queuePage.value = 0
  jobs.value = []
  copyIds.value = []
  if (selected.value) void loadQueue().catch((issue) => (error.value = errorMessage(issue)))
}
async function unlock() {
  await perform(async () => {
    try {
      await api('/station/unlock', 'POST', {
        user_id: station.value?.single_user_id ?? userId.value,
        pin: pin.value,
      })
    } finally {
      pin.value = ''
      pinAttempt.value++
    }
    unlocking.value = false
  }, 'Station unlocked.')
}
async function lock() {
  await perform(async () => {
    await api('/station/lock', 'POST')
    clearPrivate()
    if (station.value) station.value.locked = true
  }, 'Station locked.')
}
async function swap() {
  if (active.value?.id && cartridgeId.value)
    await perform(
      () =>
        installCartridge(active.value!.id!, cartridgeId.value, {
          explicitSelection: true,
          apiPrefix: '/proxy',
        }),
      'Cartridge installed.',
    )
}
async function start() {
  if (active.value?.id)
    await perform(
      () =>
        requestPrinting(
          `/proxy/queue/print?printer_id=${encodeURIComponent(active.value!.id!)}&destination_id=${encodeURIComponent(destination.value)}`,
          { copy_ids: copyIds.value },
        ),
      'Print request queued.',
    )
}
async function hold() {
  if (active.value?.id && status.value)
    await perform(
      () =>
        api(
          `/proxy/printer/automatic-printing?printer_id=${encodeURIComponent(active.value!.id!)}`,
          'PUT',
          { held: !status.value!.automatic_printing_held },
        ),
      status.value.automatic_printing_held ? 'Printer resumed.' : 'Printer held.',
    )
}
function allowStop(printer: LocalPrinter, mode: 'emergency' | 'after_current') {
  if (!station.value || !printer.can_stop) return false
  if (!station.value.online && !station.value.stop_policy[`offline_${mode}`]) return false
  if (station.value.locked) return !!station.value.stop_policy[`locked_${mode}`]
  return (
    !station.value.online ||
    can(printer.id, mode === 'emergency' ? 'emergency_stop' : 'stop_after_label')
  )
}
async function stop(printer: LocalPrinter, mode: 'emergency' | 'after_current') {
  await perform(
    () => api(`/station/printers/${printer.local_id}/stop`, 'POST', { mode }),
    'Stop requested.',
  )
}
async function clearBlock() {
  if (
    !active.value?.id ||
    !(await confirmAction(
      'Have you investigated the printer and resolved its error?',
      'Clear printer block',
    ))
  )
    return
  await perform(
    () => api(`/proxy/companion/printers/${active.value!.id}/clear`, 'POST'),
    'Printer cleared.',
  )
}
function editConfig() {
  newPrinterId.value = ''
  const device = devices.value.find((p) => p.id === active.value?.id)
  if (device) config.value = { ...device.config, name: device.name, driver: device.driver }
}
function addPrinter() {
  newPrinterId.value = crypto.randomUUID()
  config.value = {
    name: '',
    driver: 'brother-pt-p710bt',
    usb_serial: null,
    resolution: 'high',
    feed_mm: 2,
    leader_mm: 24.5,
    cut_each: true,
    timeout_seconds: 120,
  }
  error.value = ''
}
async function setPrinterEnabled(printer: { local_id: string; name: string }, enabled: boolean) {
  if (
    !enabled &&
    !(await confirmAction(
      `Remove ${printer.name} from this station? Its history and queued labels remain on the main server.`,
      'Remove printer',
    ))
  )
    return
  await perform(
    async () => {
      await api(`/station/printers/${printer.local_id}/enabled`, 'PUT', { enabled })
      if (selected.value === printer.local_id) selected.value = ''
    },
    enabled ? 'Printer restored.' : 'Printer removed.',
  )
}
async function saveConfig() {
  await perform(async () => {
    if (newPrinterId.value && config.value) {
      const { name, driver, ...configuration } = config.value
      await api('/station/printers', 'POST', {
        local_id: newPrinterId.value,
        name,
        driver,
        configuration: { ...configuration, usb_serial: configuration.usb_serial || null },
      })
    } else {
      await api(`/proxy/printers/${active.value!.id}`, 'PUT', {
        ...config.value,
        usb_serial: config.value?.usb_serial || null,
      })
    }
    config.value = undefined
  }, 'Printer configuration saved.')
}
async function createCartridge() {
  await perform(async () => {
    const cartridge = await api<Cartridge>('/proxy/cartridges', 'POST', {
      name: newName.value,
      profile_id: newProfile.value,
      nominal_length_mm: newLength.value,
      currency: newCurrency.value,
      price_minor: newPrice.value === '' ? null : Math.round(Number(newPrice.value) * 100),
    })
    adding.value = false
    cartridgeId.value = cartridge.id
    await installCartridge(active.value!.id!, cartridge.id, {
      explicitSelection: true,
      apiPrefix: '/proxy',
    })
  }, 'Cartridge added and installed.')
}
function toggleJob(job: Job, checked: boolean) {
  const ids = new Set(queuedCopies(job))
  copyIds.value = checked
    ? [...new Set([...copyIds.value, ...ids])]
    : copyIds.value.filter((id) => !ids.has(id))
}
function touch() {
  if (!operational.value || Date.now() - lastTouch < 15000) return
  lastTouch = Date.now()
  const ticket = generation,
    started = performance.now()
  void api<{ lock_remaining_seconds: number }>('/station/activity', 'POST')
    .then((state) => {
      if (!disposed && ticket === generation && operational.value)
        updateLockCountdown(state.lock_remaining_seconds, started)
    })
    .catch(() => {})
}
async function poll() {
  if (!document.hidden) await refresh()
  if (!disposed) timer = setTimeout(poll, 3000)
}
onMounted(() => {
  clockTimer = setInterval(() => {
    clock.value = performance.now()
  }, 1000)
  void poll()
  document.addEventListener('pointerdown', touch)
  document.addEventListener('keydown', touch)
})
onBeforeUnmount(() => {
  disposed = true
  generation++
  clearTimeout(timer)
  clearInterval(clockTimer)
  clearPrivate()
  document.removeEventListener('pointerdown', touch)
  document.removeEventListener('keydown', touch)
})
function openUnlock() {
  unlocking.value = true
  userId.value = station.value?.single_user_id ?? station.value?.users[0]?.id ?? ''
  pin.value = ''
  error.value = ''
}
function closeUnlock() {
  unlocking.value = false
  pin.value = ''
}
function openAdding() {
  adding.value = true
  newName.value = ''
  newProfile.value = profiles.value[0]?.id ?? ''
  newPrice.value = ''
}
function changeDestination() {
  queuePage.value = 0
  copyIds.value = []
  void loadQueue().catch((issue) => (error.value = errorMessage(issue)))
}
function changePage(delta: number) {
  queuePage.value += delta
  copyIds.value = []
  void loadQueue().catch((issue) => (error.value = errorMessage(issue)))
}
</script>

<template>
  <main id="main-content" class="station-shell" tabindex="-1">
    <header class="station-heading">
      <div>
        <h1>{{ station?.name ?? 'Companion' }}</h1>
        <p class="muted">
          {{ station?.online ? 'Connected to main server' : 'Main server offline'
          }}<template v-if="station?.user && !station.locked">
            · {{ station.user.username }}</template
          >
        </p>
      </div>
      <button
        v-if="station?.locked"
        class="primary"
        :disabled="!station.online || busy"
        @click="openUnlock"
      >
        Unlock
      </button>
      <div v-else-if="station" class="station-lock">
        <span class="muted lock-countdown" role="timer" aria-label="Time until station locks"
          >Locks in {{ lockCountdown }}</span
        >
        <button class="secondary" :disabled="busy" @click="lock">Lock</button>
      </div>
    </header>
    <Transition name="notice"
      ><p v-if="error" class="alert danger" role="alert">{{ error }}</p></Transition
    >
    <Transition name="notice"
      ><p v-if="success" class="alert success" role="status">{{ success }}</p></Transition
    >
    <section class="panel" aria-label="Connected printers">
      <button
        v-if="!station?.locked && station?.user?.permissions.includes('printers.manage')"
        class="secondary"
        :disabled="busy || !operational"
        @click="addPrinter"
      >
        Add printer
      </button>
      <p v-if="station && !station.printers.length" class="muted">No local printers configured.</p>
      <TransitionGroup tag="div" name="collection" @before-leave="freezeLeavingItem">
        <article
          v-for="printer in station?.printers"
          :key="printer.local_id"
          class="station-printer"
        >
          <div class="row wrap spread">
            <div>
              <h2>{{ printer.name }}</h2>
              <p :class="printer.blocked || printer.status.error ? 'danger-text' : 'muted'">
                {{
                  printer.blocked
                    ? 'Investigation required'
                    : printer.printing
                      ? 'Printing'
                      : (printer.status.error ??
                        (printer.status.connected ? 'Ready' : 'Disconnected'))
                }}<template v-if="printer.status.tape_width_mm">
                  · {{ printer.status.tape_width_mm }} mm</template
                >
              </p>
            </div>
            <div class="row wrap">
              <button
                v-if="!station?.locked && can(printer.id, 'view')"
                class="secondary"
                :disabled="!operational || busy"
                :aria-expanded="selected === printer.local_id"
                @click="openControls(printer)"
              >
                {{ selected === printer.local_id ? 'Close controls' : 'Controls' }}</button
              ><button
                v-if="allowStop(printer, 'after_current')"
                class="secondary"
                :disabled="busy"
                @click="stop(printer, 'after_current')"
              >
                Stop after label</button
              ><button
                v-if="allowStop(printer, 'emergency')"
                class="danger"
                :disabled="busy"
                @click="stop(printer, 'emergency')"
              >
                Emergency stop
              </button>
            </div>
          </div>
          <ExpandableContent :open="selected === printer.local_id && !station?.locked">
            <Transition name="notice">
              <div class="station-controls" v-if="selected === printer.local_id">
                <p v-if="status?.needs_review.length" class="alert warning">
                  Review the interrupted batch on the main server before continuing.
                </p>
                <p
                  v-else-if="status?.media_warning || status?.cartridge_check_pending"
                  class="alert warning"
                >
                  {{ status.media_warning ?? 'Confirm the installed cartridge.' }}
                </p>
                <div class="row wrap">
                  <button
                    v-if="can(printer.id, 'hold_resume')"
                    class="secondary"
                    :disabled="!operational || busy"
                    @click="hold"
                  >
                    {{
                      status?.automatic_printing_held ? 'Resume printer' : 'Hold printer'
                    }}</button
                  ><button
                    v-if="can(printer.id, 'configure')"
                    class="secondary"
                    :disabled="!operational || busy"
                    @click="editConfig"
                  >
                    Configure printer</button
                  ><button
                    v-if="station?.user?.permissions.includes('printers.manage')"
                    class="secondary"
                    :disabled="
                      !operational || busy || !!status?.printing || !!status?.needs_review.length
                    "
                    @click="setPrinterEnabled(printer, false)"
                  >
                    Remove printer</button
                  ><button
                    v-if="printer.blocked && can(printer.id, 'review')"
                    class="secondary"
                    :disabled="!operational || busy || !!status?.needs_review.length"
                    @click="clearBlock"
                  >
                    Clear block
                  </button>
                </div>
                <div v-if="can(printer.id, 'swap_cartridges')" class="station-cartridge">
                  <label
                    >Cartridge<select
                      v-model="cartridgeId"
                      :disabled="!operational || busy || !!status?.printing"
                    >
                      <option value="">Choose cartridge</option>
                      <option
                        v-for="cartridge in choices"
                        :key="cartridge.id"
                        :value="cartridge.id"
                      >
                        {{ cartridge.name }}
                      </option>
                    </select></label
                  ><label class="checkbox"
                    ><input v-model="allLocations" type="checkbox" />All accessible locations</label
                  >
                  <div class="row wrap">
                    <button
                      class="primary"
                      :disabled="!operational || busy || !cartridgeId || !!status?.printing"
                      @click="swap"
                    >
                      Install cartridge</button
                    ><button
                      v-if="station?.user?.permissions.includes('inventory.manage')"
                      class="secondary"
                      :disabled="!operational || busy || !!status?.printing"
                      @click="openAdding"
                    >
                      Add cartridge
                    </button>
                  </div>
                </div>
                <section class="station-queue" aria-label="Printer queue">
                  <div class="row wrap spread">
                    <h3>Queue</h3>
                    <label v-if="destinations.length > 1"
                      >Destination<select v-model="destination" @change="changeDestination">
                        <option v-for="choice in destinations" :key="choice.id" :value="choice.id">
                          {{ choice.name }}
                        </option>
                      </select></label
                    >
                  </div>
                  <p v-if="!jobs.length" class="muted">No queued labels.</p>
                  <div v-for="job in jobs" :key="job.id" class="station-job">
                    <label class="checkbox"
                      ><input
                        type="checkbox"
                        :checked="queuedCopies(job).every((id) => copyIds.includes(id))"
                        :disabled="!operational || busy || !job.can_print"
                        @change="toggleJob(job, ($event.target as HTMLInputElement).checked)"
                      /><span
                        >{{ job.process_name
                        }}<small
                          >{{ queuedCopies(job).length }} copies ·
                          {{ job.attribution?.requested_by?.name ?? job.owner_id }}</small
                        ></span
                      ></label
                    ><JobPreview
                      :job-id="job.id"
                      :text="job.process_name"
                      :width-mm="job.width_mm"
                      :length-mm="job.length_mm"
                      :preview-url="`/api/proxy/jobs/${job.id}/preview`"
                    />
                  </div>
                  <nav v-if="queuePage || hasNextPage" class="row wrap" aria-label="Queue pages">
                    <button
                      class="secondary"
                      :disabled="!operational || busy || !queuePage"
                      @click="changePage(-1)"
                    >
                      Previous
                    </button>
                    <span>Page {{ queuePage + 1 }}</span>
                    <button
                      class="secondary"
                      :disabled="!operational || busy || !hasNextPage"
                      @click="changePage(1)"
                    >
                      Next
                    </button>
                  </nav>
                  <button
                    v-if="can(printer.id, 'start_any') || can(printer.id, 'start_own')"
                    class="primary"
                    :disabled="
                      !operational ||
                      busy ||
                      !copyIds.length ||
                      printer.blocked ||
                      !!status?.printing
                    "
                    @click="start"
                  >
                    Print selected ({{ copyIds.length }})
                  </button>
                </section>
              </div>
            </Transition>
          </ExpandableContent>
        </article>
      </TransitionGroup>
      <ExpandableContent :open="!station?.locked && !!station?.removed_printers.length">
        <section v-if="!station?.locked" class="station-removed" aria-label="Removed printers">
          <h3>Removed printers</h3>
          <div
            v-for="printer in station?.removed_printers"
            :key="printer.local_id"
            class="row wrap spread"
          >
            <span>{{ printer.name }}</span
            ><button
              class="secondary"
              :disabled="!operational || busy"
              @click="setPrinterEnabled(printer, true)"
            >
              Restore printer
            </button>
          </div>
        </section>
      </ExpandableContent>
    </section>
  </main>
  <AdminDialog :open="unlocking" title="Unlock station" :busy="busy" @close="closeUnlock"
    ><form v-validate-form class="form-stack" @submit.prevent="unlock">
      <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
      <label v-if="!station?.single_user_id"
        >User<select v-model="userId" required :disabled="busy">
          <option v-for="user in station?.users" :key="user.id" :value="user.id">
            {{ user.username }}
          </option>
        </select></label
      >
      <PinEntry
        :key="`${userId}:${pinAttempt}`"
        v-model="pin"
        :keypad="station?.pin_keypad?.enabled"
        :shuffle="station?.pin_keypad?.shuffle"
        :disabled="busy"
      />
      <button class="primary" :disabled="busy || !station?.online">Unlock</button>
    </form></AdminDialog
  >
  <AdminDialog
    :open="!!config && !station?.locked"
    :title="newPrinterId ? 'Add printer' : 'Printer configuration'"
    :busy="busy"
    @close="config = undefined"
    ><form v-if="config" v-validate-form class="form-stack" @submit.prevent="saveConfig">
      <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
      <label>Name<input v-model="config.name" required maxlength="100" /></label
      ><label>USB serial<input v-model="config.usb_serial" maxlength="128" /></label
      ><label
        >Resolution<select v-model="config.resolution">
          <option value="normal">Normal</option>
          <option value="high">High</option>
        </select></label
      ><label
        >Feed (mm)<input
          v-model.number="config.feed_mm"
          type="number"
          min="2"
          max="127"
          step="0.1"
          required /></label
      ><label
        >Leader (mm)<input
          v-model.number="config.leader_mm"
          type="number"
          min="0"
          max="200"
          step="0.1"
          required /></label
      ><label class="checkbox"
        ><input v-model="config.cut_each" type="checkbox" />Cut each label</label
      ><button class="primary" :disabled="busy || !operational">
        {{ newPrinterId ? 'Add printer' : 'Save configuration' }}
      </button>
    </form></AdminDialog
  >
  <AdminDialog
    :open="adding && !station?.locked"
    title="Add cartridge"
    :busy="busy"
    @close="adding = false"
    ><form v-validate-form class="form-stack" @submit.prevent="createCartridge">
      <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
      <label>Name<input v-model="newName" required maxlength="100" /></label
      ><label
        >Tape profile<select v-model="newProfile" required>
          <option v-for="profile in profiles" :key="profile.id" :value="profile.id">
            {{ profile.name }}
          </option>
        </select></label
      ><label
        >Length (mm)<input
          v-model.number="newLength"
          type="number"
          min="1"
          max="1000000"
          required /></label
      ><label>Price<input v-model="newPrice" type="number" min="0" step="0.01" /></label
      ><label
        >Currency<input
          v-model="newCurrency"
          pattern="[A-Z]{3}"
          minlength="3"
          maxlength="3"
          required /></label
      ><button class="primary" :disabled="busy || !operational">Add and install</button>
    </form></AdminDialog
  >
  <ConfirmDialog /><CartridgeConsent />
</template>

<style scoped>
.station-shell {
  max-width: 1100px;
  margin: 0 auto;
  padding: 32px 24px;
}
.station-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 32px;
}
.station-heading h1 {
  margin: 0 0 8px;
}
.station-heading p {
  margin: 0;
}
.station-lock {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 12px;
}
.lock-countdown {
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.station-printer {
  padding-block: 24px;
}
.station-printer + .station-printer {
  border-top: 1px solid var(--line);
}
.station-printer h2 {
  margin: 0 0 8px;
}
.station-printer p {
  margin-block: 8px;
}
.station-controls {
  padding-top: 24px;
  display: grid;
  gap: 32px;
}
.station-cartridge {
  max-width: 560px;
  display: grid;
  gap: 16px;
}
.station-queue h3 {
  margin: 0;
}
.station-job {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 24px;
  padding-block: 16px;
  border-bottom: 1px solid var(--line);
}
.station-job small {
  display: block;
  color: var(--muted);
  margin-top: 4px;
}
.station-queue > button {
  margin-top: 24px;
}
@media (max-width: 600px) {
  .station-shell {
    padding: 24px 16px;
  }
  .station-heading {
    align-items: start;
  }
  .station-job {
    flex-wrap: wrap;
  }
}
</style>
