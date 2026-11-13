<script setup lang="ts">
import { t } from './shared/i18n'

import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api, configureSession, errorMessage } from './shared/api'
import { ActionCancelled, ActionDeferred, confirmAction } from './shared/confirmation'
import { installCartridge } from './printing/cartridges'
import { requestPrinting } from './printing/printing'
import { resolveCartridgeConsent } from './accounts/cartridgeConsent'
import { vValidateForm } from './shared/formValidation'
import { freezeLeavingItem } from './shared/collectionMotion'
import type { Cartridge, Job, Printer, Profile, Status } from './shared/types'
import AdminDialog from './components/AdminDialog.vue'
import ExpandableContent from './components/ExpandableContent.vue'
import ConfirmDialog from './components/ConfirmDialog.vue'
import CartridgeConsent from './components/CartridgeConsent.vue'
import JobPreview from './components/JobPreview.vue'
import PinEntry from './components/PinEntry.vue'
import UserAvatar from './components/UserAvatar.vue'
import SourceLink from './components/SourceLink.vue'
import PaymentAttribution from './components/PaymentAttribution.vue'
import StationTelemetry, { type StationDashboard } from './components/StationTelemetry.vue'
import CompanionPacking from './components/CompanionPacking.vue'
import MotionSurface from './components/MotionSurface.vue'
import AnimatedDetails from './components/AnimatedDetails.vue'
import {
  PrinterIcon,
  LockClosedIcon,
  ExclamationTriangleIcon,
  PauseIcon,
  SignalSlashIcon,
  CheckCircleIcon,
} from '@heroicons/vue/24/outline'
import { checkServer, serverUnavailable } from './shared/serverConnection'
import { mediaLabel, compatibleProfile } from './printing/media'
import { reloadUpdatedCompanion } from './companion/companionUpdates'
import {
  accountLanguage,
  browserLanguage,
  deploymentLanguage,
  validPreference,
  type Language,
  type LanguagePreference,
} from './shared/i18n'
import LanguagePicker from './components/LanguagePicker.vue'

interface LocalPrinter {
  no_automatic_printing?: boolean | null
  dashboard?: StationDashboard | null
  snapshot_age_seconds?: number | null
  local_id: string
  id: string | null
  name: string
  blocked: boolean
  printing: boolean
  can_stop: boolean
  status: { connected: boolean; tape_width_mm?: number | null; error?: string | null }
}
interface Operator {
  language?: LanguagePreference
  id: string
  username: string
  permissions: string[]
  location_id: string
  printer_permissions: Record<string, string[]>
  groups: Record<string, { name: string; printer_ids: string[] }>
}
interface QueueGroup {
  id: string
  run_id: string | null
  name: string | null
  jobs: Job[]
}
interface Station {
  default_language?: Language
  version?: string
  update?: { version: string; url: string } | null
  frontend_build?: string | null
  name: string
  online: boolean
  locked: boolean
  user: Operator | null
  users: { id: string; username: string; avatar_version?: string | null }[]
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
const stationReachable = ref(false),
  refreshError = ref('')
const selectedUser = computed(() => station.value?.users.find((user) => user.id === userId.value))
const connectionLabel = computed(() =>
  !stationReachable.value || serverUnavailable.value
    ? t('common.reconnectingToCompanion')
    : station.value?.online
      ? t('common.mainServerConnected')
      : t('common.mainServerOfflineReconnecting'),
)
const unlockPanel = ref<HTMLElement>()
const error = ref(''),
  success = ref(''),
  busy = ref(false),
  unlocking = ref(false)
watch(
  success,
  (message, _previous, onCleanup) => {
    if (!message) return
    const timeout = setTimeout(() => {
      success.value = ''
    }, 5000)
    onCleanup(() => clearTimeout(timeout))
  },
  { flush: 'sync' },
)
const userId = ref(''),
  pin = ref(''),
  selected = ref(''),
  destination = ref('')
const pinAttempt = ref(0)
const expandedPrinter = ref('')
watch(selected, (value) => {
  if (value) expandedPrinter.value = value
})
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
  queueGroups = ref<QueueGroup[]>([]),
  copyIds = ref<string[]>([])
const jobs = computed(() => queueGroups.value.flatMap((group) => group.jobs))
const packingPrinter = ref<LocalPrinter | null>(null)
const queuePage = ref(0),
  hasNextPage = ref(false)
const config = ref<
  Printer['config'] & { name: string; driver: string; no_automatic_printing?: boolean }
>()
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
const installedProfile = computed(() => {
  const cartridge = cartridges.value.find((item) => item.id === status.value?.active_cartridge_id)
  return profiles.value.find((item) => item.id === cartridge?.profile_id)
})
const profileName = (id: string) =>
  profiles.value.find((profile) => profile.id === id)?.name ??
  t('uiMessages.unavailableTapeProfile')
const jobProfileName = (job: Job) => job.profile_name || profileName(job.profile_id)
const groupCopies = (group: QueueGroup) => group.jobs.flatMap(queuedCopies)
const selectableCopies = (group: QueueGroup) =>
  group.jobs.filter((job) => job.can_print).flatMap(queuedCopies)
function toggleGroup(group: QueueGroup, checked: boolean) {
  const ids = new Set(selectableCopies(group))
  copyIds.value = checked
    ? [...new Set([...copyIds.value, ...ids])]
    : copyIds.value.filter((id) => !ids.has(id))
}
async function closePacking() {
  const id = packingPrinter.value?.local_id
  packingPrinter.value = null
  await nextTick()
  document.getElementById(`pack-${id}`)?.focus()
}
async function openPacking(printer: LocalPrinter) {
  packingPrinter.value = printer
  await nextTick()
  document.querySelector<HTMLElement>('.station-packing h2')?.focus()
}
const operational = computed(
  () =>
    stationReachable.value &&
    !serverUnavailable.value &&
    !!station.value?.online &&
    !station.value.locked,
)
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
const fleetSummary = computed(() => {
  const printers = station.value?.printers ?? []
  const connected = printers.filter((printer) => printer.status.connected).length
  const attention = printers.filter((printer) => printer.blocked || printer.status.error).length
  return t(attention ? 'actionMessages.connectedAttention' : 'actionMessages.connected', {
    connected,
    total: printers.length,
    attention,
  })
})
function printerState(printer: LocalPrinter) {
  if (!stationReachable.value || serverUnavailable.value)
    return {
      get label() {
        return t('uiMessages.statusUnavailable')
      },
      tone: 'muted',
      icon: SignalSlashIcon,
    }
  if (printer.blocked)
    return {
      get label() {
        return t('uiMessages.investigationRequired')
      },
      tone: 'danger',
      icon: ExclamationTriangleIcon,
    }
  if (printer.status.error)
    return {
      get label() {
        return t('uiMessages.printerError')
      },
      tone: 'danger',
      icon: ExclamationTriangleIcon,
    }
  if (printer.printing)
    return {
      get label() {
        return t('dashboard.printing')
      },
      tone: 'printing',
      icon: PrinterIcon,
    }
  if (!printer.status.connected)
    return {
      get label() {
        return t('uiMessages.disconnected')
      },
      tone: 'muted',
      icon: SignalSlashIcon,
    }
  if (printer.dashboard?.cartridge_check_pending)
    return {
      get label() {
        return t('uiMessages.checkCartridge')
      },
      tone: 'warning',
      icon: ExclamationTriangleIcon,
    }
  if (!printer.no_automatic_printing && printer.dashboard?.held)
    return {
      get label() {
        return t('uiMessages.onHold')
      },
      tone: 'warning',
      icon: PauseIcon,
    }
  return {
    label: printer.no_automatic_printing ? t('uiMessages.ready') : t('uiMessages.connected'),
    tone: 'ready',
    icon: CheckCircleIcon,
  }
}
const queuedCopies = (job: Job) =>
  job.labels.filter((label) => label.state === 'queued').map((label) => label.id)
function clearPrivate(clearPin = true) {
  generation++
  catalogUser = ''
  queueGroups.value = []
  packingPrinter.value = null
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
    if (serverUnavailable.value && !(await checkServer())) {
      stationReachable.value = false
      return
    }
    const started = performance.now()
    const state = await api<Station>('/station').catch((issue) => {
      stationReachable.value = false
      throw issue
    })
    if (disposed || ticket !== generation) return
    if (
      await reloadUpdatedCompanion(
        state.frontend_build,
        () =>
          !disposed &&
          ticket === generation &&
          state.locked &&
          !busy.value &&
          !unlocking.value &&
          !adding.value &&
          !config.value &&
          !document.hidden &&
          !document.querySelector('dialog[open], [role="dialog"][aria-modal="true"]'),
      )
    )
      return
    if (disposed || ticket !== generation) return
    const changed = state.user?.id !== station.value?.user?.id
    station.value = state
    deploymentLanguage.value = state.default_language === 'de' ? 'de' : 'en'
    accountLanguage.value = state.user ? validPreference(state.user.language) : null
    stationReachable.value = true
    refreshError.value = ''
    if (
      !state.single_user_id &&
      userId.value &&
      !state.users.some((user) => user.id === userId.value)
    ) {
      userId.value = ''
      pin.value = ''
    }
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
      queueGroups.value = []
      copyIds.value = []
    }
    if (packingPrinter.value && !can(packingPrinter.value.id, 'view_activity'))
      packingPrinter.value = null
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
    if (!disposed) refreshError.value = errorMessage(issue)
  } finally {
    refreshBusy = false
  }
}
async function loadQueue(ticket = generation) {
  if (!destination.value || !operational.value) return
  const page = queuePage.value,
    target = destination.value
  const groups = await api<QueueGroup[]>(
    `/proxy/queue/groups?destination_id=${encodeURIComponent(target)}&copy_state=queued&limit=26&offset=${page * 25}`,
  )
  if (disposed || ticket !== generation || page !== queuePage.value || target !== destination.value)
    return
  hasNextPage.value = groups.length > 25
  queueGroups.value = groups.slice(0, 25)
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
  queueGroups.value = []
  copyIds.value = []
  if (selected.value) void loadQueue().catch((issue) => (error.value = errorMessage(issue)))
}
async function unlock() {
  if (!userId.value || !stationReachable.value || !station.value?.online) return
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
  }, t('uiMessages.stationUnlocked'))
}
async function lock() {
  await perform(async () => {
    await api('/station/lock', 'POST')
    clearPrivate()
    if (station.value) station.value.locked = true
  }, t('uiMessages.stationLocked'))
}
async function saveLanguage(language: Language) {
  const user = station.value?.user
  if (!user) return
  const ticket = generation
  await api('/station/language', 'PUT', { language, browser_language: browserLanguage.value })
  if (disposed || ticket !== generation || station.value?.user?.id !== user.id) return
  generation++
  station.value.user = { ...station.value.user, language }
  accountLanguage.value = language
}
async function swap() {
  if (active.value?.id && cartridgeId.value)
    await perform(
      () =>
        installCartridge(active.value!.id!, cartridgeId.value, {
          explicitSelection: true,
          apiPrefix: '/proxy',
        }),
      t('uiMessages.cartridgeInstalled'),
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
      t('uiMessages.printRequestQueued'),
    )
}
async function printProfileQueue() {
  if (active.value?.id && installedProfile.value)
    await perform(
      () =>
        requestPrinting(
          `/proxy/queue/print?printer_id=${encodeURIComponent(active.value!.id!)}&destination_id=${encodeURIComponent(destination.value)}`,
        ),
      t('uiMessages.printRequestQueued'),
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
      status.value.automatic_printing_held
        ? t('uiMessages.printerResumed')
        : t('uiMessages.printerHeld'),
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
    t('uiMessages.stopRequested'),
  )
}
async function clearBlock() {
  if (
    !active.value?.id ||
    !(await confirmAction(
      t('uiMessages.haveYouInvestigatedThePrinterAndResolvedItsError'),
      t('uiMessages.clearPrinterBlock'),
    ))
  )
    return
  await perform(
    () => api(`/proxy/companion/printers/${active.value!.id}/clear`, 'POST'),
    t('uiMessages.printerCleared'),
  )
}
function editConfig() {
  newPrinterId.value = ''
  const device = devices.value.find((p) => p.id === active.value?.id)
  if (device)
    config.value = {
      ...device.config,
      name: device.name,
      driver: device.driver,
      no_automatic_printing: device.no_automatic_printing ?? false,
    }
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
      t('uiDetails.removeStationPrinter', { value1: String(printer.name) }),
      t('companionApp.removePrinter'),
    ))
  )
    return
  await perform(
    async () => {
      await api(`/station/printers/${printer.local_id}/enabled`, 'PUT', { enabled })
      if (selected.value === printer.local_id) selected.value = ''
    },
    enabled ? t('uiMessages.printerRestored') : t('uiMessages.printerRemoved'),
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
  }, t('uiMessages.printerConfigurationSaved'))
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
  }, t('uiMessages.cartridgeAddedAndInstalled'))
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
  window.addEventListener('online', reconnectNow)
  document.addEventListener('visibilitychange', reconnectNow)
  document.addEventListener('pointerdown', touch)
  document.addEventListener('keydown', touch)
})
onBeforeUnmount(() => {
  disposed = true
  generation++
  clearTimeout(timer)
  clearInterval(clockTimer)
  clearPrivate()
  window.removeEventListener('online', reconnectNow)
  document.removeEventListener('visibilitychange', reconnectNow)
  document.removeEventListener('pointerdown', touch)
  document.removeEventListener('keydown', touch)
})
function openUnlock() {
  unlocking.value = true
  userId.value = station.value?.single_user_id ?? ''
  pin.value = ''
  error.value = ''
}
async function chooseUser(identifier: string) {
  userId.value = identifier
  pin.value = ''
  error.value = ''
  await nextTick()
  unlockPanel.value?.querySelector<HTMLElement>(identifier ? 'input' : '.station-user')?.focus()
}
function reconnectNow() {
  if (!document.hidden) void refresh()
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
      <div class="station-title">
        <h1>{{ station?.name ?? $t('common.companion') }}</h1>
        <p class="muted">
          {{
            stationReachable && !serverUnavailable
              ? fleetSummary
              : $t('common.waitingForStationStatus')
          }}
          <Transition name="notice">
            <span v-if="station?.update" class="station-update" role="status">
              ·
              <a :href="station.update.url" target="_blank" rel="noopener noreferrer"
                >{{ $t('common.updateAvailable2') }} {{ station.update.version }}</a
              >
            </span>
          </Transition>
        </p>
      </div>
      <div v-if="!station || station.locked" class="station-unlock">
        <button
          class="primary"
          :disabled="!stationReachable || serverUnavailable || !station?.online || busy"
          @click="openUnlock"
        >
          {{ $t('common.unlock') }}
        </button>
      </div>
      <div v-if="station && !station.locked" class="station-lock">
        <span class="station-operator">{{ station.user?.username }}</span>
        <span
          class="muted lock-countdown"
          role="timer"
          :aria-label="$t('common.timeUntilStationLocks')"
          >{{ $t('companionApp.locksIn') }} {{ lockCountdown }}</span
        >
        <button class="secondary" :disabled="busy" @click="lock">
          {{ $t('companionApp.lock') }}
        </button>
      </div>
      <span v-else class="station-locked"
        ><LockClosedIcon aria-hidden="true" />{{ $t('companionApp.locked') }}</span
      >
      <LanguagePicker
        :key="station?.user?.id ?? 'device'"
        :save="station?.user ? saveLanguage : undefined"
      />
    </header>
    <Transition name="notice"
      ><p
        v-if="refreshError && stationReachable && station?.online && !serverUnavailable"
        class="alert danger"
        role="alert"
      >
        {{ refreshError }}
      </p></Transition
    >
    <Transition name="notice"
      ><p v-if="error" class="alert danger" role="alert">{{ error }}</p></Transition
    >
    <Transition name="notice"
      ><p v-if="success" class="alert success" role="status">{{ success }}</p></Transition
    >
    <MotionSurface :identity="packingPrinter?.local_id ?? 'printers'">
      <CompanionPacking
        v-if="packingPrinter?.id && operational && can(packingPrinter.id, 'view_activity')"
        :key="`${station?.user?.id}:${packingPrinter.id}`"
        :printer-id="packingPrinter.id"
        :printer-name="packingPrinter.name"
        @close="closePacking"
      />
      <section v-else class="station-fleet" :aria-label="$t('common.connectedPrinters')">
        <div class="fleet-toolbar">
          <h2>{{ $t('common.printers') }}</h2>
          <button
            v-if="!station?.locked && station?.user?.permissions.includes('printers.manage')"
            class="secondary"
            :disabled="busy || !operational"
            @click="addPrinter"
          >
            {{ $t('common.addPrinter') }}
          </button>
        </div>
        <p v-if="station && !station.printers.length" class="panel muted">
          {{ $t('companionApp.noLocalPrintersConfigured') }}
        </p>
        <TransitionGroup
          tag="div"
          class="printer-grid"
          name="collection"
          @before-leave="freezeLeavingItem"
        >
          <article
            v-for="printer in station?.printers"
            :key="printer.local_id"
            class="station-printer"
            :class="{ expanded: expandedPrinter === printer.local_id }"
            :aria-label="printer.name"
          >
            <div class="printer-card-heading">
              <div class="printer-identity">
                <PrinterIcon class="printer-icon" aria-hidden="true" />
                <div>
                  <div class="row wrap printer-name-mode">
                    <h2>{{ printer.name }}</h2>
                    <span v-if="printer.no_automatic_printing != null" class="muted printer-mode">{{
                      printer.no_automatic_printing
                        ? $t('printers.manualOnly')
                        : $t('uiMessages.automatic')
                    }}</span>
                  </div>
                  <p class="muted">
                    {{
                      printer.status.tape_width_mm
                        ? $t('uiDetails.tapeWidth', {
                            value1: String(printer.status.tape_width_mm),
                          })
                        : $t('uiMessages.tapeNotDetected')
                    }}
                  </p>
                </div>
              </div>
              <span class="printer-state" :class="printerState(printer).tone"
                ><component :is="printerState(printer).icon" aria-hidden="true" />{{
                  printerState(printer).label
                }}</span
              >
            </div>
            <p v-if="printer.status.error" class="printer-problem">{{ printer.status.error }}</p>
            <StationTelemetry
              v-if="printer.dashboard?.queued_labels != null"
              :details="printer.dashboard"
              :stale="
                !station?.online ||
                !stationReachable ||
                serverUnavailable ||
                (printer.snapshot_age_seconds ?? 0) > 20
              "
              :printing="printer.printing"
            />
            <div class="printer-actions">
              <div class="row wrap">
                <button
                  v-if="!station?.locked && can(printer.id, 'view')"
                  class="secondary"
                  :disabled="!operational || busy"
                  :aria-expanded="selected === printer.local_id"
                  @click="openControls(printer)"
                >
                  {{
                    selected === printer.local_id
                      ? $t('uiMessages.closeControls')
                      : $t('uiMessages.controls')
                  }}
                </button>
                <button
                  v-if="!station?.locked && can(printer.id, 'view_activity')"
                  :id="`pack-${printer.local_id}`"
                  class="secondary"
                  :disabled="!operational || busy"
                  @click="openPacking(printer)"
                >
                  {{ $t('companionApp.packLabels') }}
                </button>
                <button
                  v-if="allowStop(printer, 'after_current')"
                  class="secondary"
                  :disabled="busy"
                  @click="stop(printer, 'after_current')"
                >
                  {{ $t('common.stopAfterLabel') }}</button
                ><button
                  v-if="allowStop(printer, 'emergency')"
                  class="danger"
                  :disabled="busy"
                  @click="stop(printer, 'emergency')"
                >
                  {{ $t('common.emergencyStop') }}
                </button>
              </div>
            </div>
            <ExpandableContent
              :open="selected === printer.local_id && !station?.locked"
              @closed="expandedPrinter === printer.local_id && (expandedPrinter = '')"
            >
              <Transition name="notice">
                <div class="station-controls" v-if="selected === printer.local_id">
                  <p v-if="status?.needs_review.length" class="alert warning">
                    {{ $t('companionApp.reviewTheInterruptedBatchOnTheMainServerBefore') }}
                  </p>
                  <p
                    v-else-if="status?.media_warning || status?.cartridge_check_pending"
                    class="alert warning"
                  >
                    {{ status.media_warning ?? $t('uiMessages.confirmTheInstalledCartridge') }}
                  </p>
                  <div class="row wrap">
                    <button
                      v-if="
                        !status?.no_automatic_printing &&
                        !printer.no_automatic_printing &&
                        can(printer.id, 'hold_resume')
                      "
                      class="secondary"
                      :disabled="!operational || busy"
                      @click="hold"
                    >
                      {{
                        status?.automatic_printing_held
                          ? $t('uiMessages.resumePrinter')
                          : $t('uiMessages.holdPrinter')
                      }}</button
                    ><button
                      v-if="can(printer.id, 'configure')"
                      class="secondary"
                      :disabled="!operational || busy"
                      @click="editConfig"
                    >
                      {{ $t('companionApp.configurePrinter') }}</button
                    ><button
                      v-if="station?.user?.permissions.includes('printers.manage')"
                      class="secondary"
                      :disabled="
                        !operational || busy || !!status?.printing || !!status?.needs_review.length
                      "
                      @click="setPrinterEnabled(printer, false)"
                    >
                      {{ $t('companionApp.removePrinter') }}</button
                    ><button
                      v-if="printer.blocked && can(printer.id, 'review')"
                      class="secondary"
                      :disabled="!operational || busy || !!status?.needs_review.length"
                      @click="clearBlock"
                    >
                      {{ $t('common.clearBlock') }}
                    </button>
                  </div>
                  <div v-if="can(printer.id, 'swap_cartridges')" class="station-cartridge">
                    <label
                      >{{ $t('common.cartridge')
                      }}<select
                        v-model="cartridgeId"
                        :disabled="!operational || busy || !!status?.printing"
                      >
                        <option value="">{{ $t('companionApp.chooseCartridge') }}</option>
                        <option
                          v-for="cartridge in choices"
                          :key="cartridge.id"
                          :value="cartridge.id"
                          :disabled="
                            !compatibleProfile(
                              profiles.find((profile) => profile.id === cartridge.profile_id),
                              devices.find((device) => device.id === printer.id)?.capabilities,
                            )
                          "
                        >
                          {{ cartridge.name }} ·
                          {{
                            mediaLabel(
                              profiles.find((profile) => profile.id === cartridge.profile_id),
                            )
                          }}
                        </option>
                      </select></label
                    ><label class="checkbox"
                      ><input v-model="allLocations" type="checkbox" />{{
                        $t('companionApp.allAccessibleLocations')
                      }}</label
                    >
                    <div class="row wrap">
                      <button
                        class="primary"
                        :disabled="!operational || busy || !cartridgeId || !!status?.printing"
                        @click="swap"
                      >
                        {{ $t('common.installCartridge') }}</button
                      ><button
                        v-if="station?.user?.permissions.includes('inventory.manage')"
                        class="secondary"
                        :disabled="!operational || busy || !!status?.printing"
                        @click="openAdding"
                      >
                        {{ $t('companionApp.addCartridge') }}
                      </button>
                    </div>
                  </div>
                  <section class="station-queue" :aria-label="$t('companionApp.printerQueue')">
                    <div class="row wrap spread">
                      <h3>{{ $t('companionApp.queue') }}</h3>
                      <label v-if="destinations.length > 1"
                        >{{ $t('common.destination')
                        }}<select v-model="destination" @change="changeDestination">
                          <option
                            v-for="choice in destinations"
                            :key="choice.id"
                            :value="choice.id"
                          >
                            {{ choice.name }}
                          </option>
                        </select></label
                      >
                    </div>
                    <p v-if="!jobs.length" class="muted">{{ $t('companionApp.noQueuedLabels') }}</p>
                    <article
                      v-for="group in queueGroups"
                      :key="group.id"
                      class="station-queue-group"
                    >
                      <div class="station-job">
                        <label class="checkbox"
                          ><input
                            type="checkbox"
                            :checked="
                              !!selectableCopies(group).length &&
                              selectableCopies(group).every((id) => copyIds.includes(id))
                            "
                            :indeterminate="
                              selectableCopies(group).some((id) => copyIds.includes(id)) &&
                              !selectableCopies(group).every((id) => copyIds.includes(id))
                            "
                            :disabled="!operational || busy || !selectableCopies(group).length"
                            @change="
                              toggleGroup(group, ($event.target as HTMLInputElement).checked)
                            "
                          /><span
                            >{{ group.name ?? group.jobs[0]?.process_name }}
                            <small
                              >{{
                                group.run_id
                                  ? $t('uiDetails.rows', { value1: String(group.jobs.length) })
                                  : ''
                              }}{{ groupCopies(group).length }} {{ $t('common.copies3') }}
                              {{
                                group.jobs[0]?.attribution?.requested_by?.name ??
                                group.jobs[0]?.owner_id
                              }}</small
                            >
                            <small>{{
                              [...new Set(group.jobs.map(jobProfileName))].join(' · ')
                            }}</small>
                          </span></label
                        >
                        <JobPreview
                          v-if="!group.run_id && group.jobs[0]"
                          :job-id="group.jobs[0].id"
                          :text="group.jobs[0].process_name"
                          :width-mm="group.jobs[0].width_mm"
                          :length-mm="group.jobs[0].length_mm"
                          :preview-url="`/api/proxy/jobs/${group.jobs[0].id}/preview`"
                        />
                      </div>
                      <PaymentAttribution :payers="group.jobs.flatMap((job) => job.payers ?? [])" />
                      <AnimatedDetails v-if="group.run_id" class="station-run-rows">
                        <template #summary>{{ $t('companionApp.labelsInThisRun') }}</template>
                        <div v-for="job in group.jobs" :key="job.id" class="station-job">
                          <label class="checkbox"
                            ><input
                              type="checkbox"
                              :checked="queuedCopies(job).every((id) => copyIds.includes(id))"
                              :disabled="!operational || busy || !job.can_print"
                              @change="toggleJob(job, ($event.target as HTMLInputElement).checked)"
                            />
                            <span
                              >{{
                                job.source_row == null
                                  ? job.process_name
                                  : $t('uiDetails.row', { value1: String(job.source_row) })
                              }}<small
                                >{{ queuedCopies(job).length }} {{ $t('common.copies3') }}
                                {{ jobProfileName(job) }}</small
                              ></span
                            >
                          </label>
                          <JobPreview
                            :job-id="job.id"
                            :text="job.process_name"
                            :width-mm="job.width_mm"
                            :length-mm="job.length_mm"
                            :preview-url="`/api/proxy/jobs/${job.id}/preview`"
                          />
                        </div>
                      </AnimatedDetails>
                    </article>
                    <nav
                      v-if="queuePage || hasNextPage"
                      class="row wrap"
                      :aria-label="$t('companionApp.queuePages')"
                    >
                      <button
                        class="secondary"
                        :disabled="!operational || busy || !queuePage"
                        @click="changePage(-1)"
                      >
                        {{ $t('common.previous') }}
                      </button>
                      <span>{{ $t('common.page') }} {{ queuePage + 1 }}</span>
                      <button
                        class="secondary"
                        :disabled="!operational || busy || !hasNextPage"
                        @click="changePage(1)"
                      >
                        {{ $t('common.next') }}
                      </button>
                    </nav>
                    <div
                      class="row wrap queue-print-actions"
                      v-if="can(printer.id, 'start_any') || can(printer.id, 'start_own')"
                    >
                      <button
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
                        {{ $t('common.printSelected') }}{{ copyIds.length }})
                      </button>
                      <button
                        class="secondary"
                        :disabled="
                          !operational ||
                          busy ||
                          !installedProfile ||
                          printer.blocked ||
                          !!status?.printing
                        "
                        @click="printProfileQueue"
                      >
                        {{ $t('companionApp.printCurrentTapeQueue') }}
                      </button>
                      <span v-if="installedProfile" class="muted">{{ installedProfile.name }}</span>
                    </div>
                  </section>
                </div>
              </Transition>
            </ExpandableContent>
          </article>
        </TransitionGroup>
        <ExpandableContent :open="!station?.locked && !!station?.removed_printers.length">
          <section
            v-if="!station?.locked"
            class="station-removed"
            :aria-label="$t('companionApp.removedPrinters')"
          >
            <h3>{{ $t('companionApp.removedPrinters') }}</h3>
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
                {{ $t('companionApp.restorePrinter') }}
              </button>
            </div>
          </section>
        </ExpandableContent>
      </section>
    </MotionSurface>
    <footer class="station-footer">
      <SourceLink class="station-source" />
      <span class="station-connection" role="status" aria-live="polite">
        <span
          class="connection-dot"
          :class="{ connected: stationReachable && !serverUnavailable && station?.online }"
          aria-hidden="true"
        ></span>
        {{ connectionLabel }}
      </span>
      <span class="station-meta">
        <span v-if="station?.version" class="station-version"
          >{{ $t('common.v') }}{{ station.version }}</span
        >
        <span class="station-credit"
          >{{ $t('common.madeWithBy') }}
          <a href="https://github.com/tarobits" target="_blank" rel="noopener noreferrer">{{
            $t('common.tarobits')
          }}</a
          >.</span
        >
      </span>
    </footer>
  </main>
  <AdminDialog
    class="station-unlock-dialog"
    :open="unlocking"
    :title="$t('common.unlockStation')"
    :busy="busy"
    @close="closeUnlock"
    ><div ref="unlockPanel">
      <Transition
        name="notice"
        mode="out-in"
        @after-enter="
          unlockPanel?.querySelector<HTMLElement>(userId ? 'input' : '.station-user')?.focus()
        "
      >
        <div
          v-if="!userId"
          key="users"
          class="station-users motion-reveal"
          role="group"
          :aria-label="$t('companionApp.chooseUser')"
        >
          <button
            v-for="user in station?.users"
            :key="user.id"
            type="button"
            class="secondary station-user"
            :disabled="busy"
            @click="chooseUser(user.id)"
          >
            <UserAvatar
              :username="user.username"
              :src="
                user.avatar_version && station?.online
                  ? `/api/station/users/${encodeURIComponent(user.id)}/avatar?v=${user.avatar_version}`
                  : null
              "
            />
            <span>{{ user.username }}</span>
          </button>
          <p v-if="!station?.users.length" class="muted">
            {{ $t('companionApp.noUsersAvailable') }}
          </p>
        </div>
        <form
          v-else
          :key="userId"
          v-validate-form
          class="form-stack station-pin motion-reveal"
          @submit.prevent="unlock"
        >
          <div class="station-selected-user">
            <UserAvatar
              v-if="selectedUser"
              :username="selectedUser.username"
              :src="
                selectedUser.avatar_version && station?.online
                  ? `/api/station/users/${encodeURIComponent(selectedUser.id)}/avatar?v=${selectedUser.avatar_version}`
                  : null
              "
            />
            <strong v-if="selectedUser">{{ selectedUser.username }}</strong>
            <button
              v-if="!station?.single_user_id"
              type="button"
              class="secondary"
              :disabled="busy"
              @click="chooseUser('')"
            >
              {{ $t('companionApp.changeUser') }}
            </button>
          </div>
          <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
          <PinEntry
            compact
            :key="`${userId}:${pinAttempt}`"
            v-model="pin"
            :keypad="station?.pin_keypad?.enabled"
            :shuffle="station?.pin_keypad?.shuffle"
            :disabled="busy"
          />
          <button
            class="primary unlock-submit"
            :disabled="busy || !stationReachable || serverUnavailable || !station?.online"
          >
            {{ $t('common.unlock') }}
          </button>
        </form>
      </Transition>
    </div></AdminDialog
  >
  <AdminDialog
    :open="!!config && !station?.locked"
    :title="newPrinterId ? $t('common.addPrinter') : $t('uiMessages.printerConfiguration')"
    :busy="busy"
    @close="config = undefined"
    ><form v-if="config" v-validate-form class="form-stack" @submit.prevent="saveConfig">
      <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
      <label>{{ $t('common.name') }}<input v-model="config.name" required maxlength="100" /></label
      ><label
        >{{ $t('common.usbSerial') }}<input v-model="config.usb_serial" maxlength="128" /></label
      ><label
        >{{ $t('companionApp.resolution')
        }}<select v-model="config.resolution">
          <option value="normal">{{ $t('companionApp.normal') }}</option>
          <option value="high">{{ $t('companionApp.high') }}</option>
        </select></label
      ><label
        >{{ $t('common.feedMm')
        }}<input
          v-model.number="config.feed_mm"
          type="number"
          min="2"
          max="127"
          step="0.1"
          required /></label
      ><label
        >{{ $t('companionApp.leaderMm')
        }}<input
          v-model.number="config.leader_mm"
          type="number"
          min="0"
          max="200"
          step="0.1"
          required /></label
      ><label class="checkbox"
        ><input v-model="config.cut_each" type="checkbox" />{{ $t('common.cutEachLabel') }}</label
      ><label v-if="!newPrinterId" class="checkbox"
        ><input v-model="config.no_automatic_printing" type="checkbox" />{{
          $t('common.noAutomaticPrinting')
        }}</label
      >
      <button class="primary" :disabled="busy || !operational">
        {{ newPrinterId ? $t('common.addPrinter') : $t('uiMessages.saveConfiguration') }}
      </button>
    </form></AdminDialog
  >
  <AdminDialog
    :open="adding && !station?.locked"
    :title="$t('companionApp.addCartridge')"
    :busy="busy"
    @close="adding = false"
    ><form v-validate-form class="form-stack" @submit.prevent="createCartridge">
      <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
      <label>{{ $t('common.name') }}<input v-model="newName" required maxlength="100" /></label
      ><label
        >{{ $t('common.tapeProfile')
        }}<select v-model="newProfile" required>
          <option v-for="profile in profiles" :key="profile.id" :value="profile.id">
            {{ profile.name }}
          </option>
        </select></label
      ><label
        >{{ $t('companionApp.lengthMm')
        }}<input v-model.number="newLength" type="number" min="1" max="1000000" required /></label
      ><label
        >{{ $t('companionApp.price')
        }}<input v-model="newPrice" type="number" min="0" step="0.01" /></label
      ><label
        >{{ $t('common.currency')
        }}<input
          v-model="newCurrency"
          pattern="[A-Z]{3}"
          minlength="3"
          maxlength="3"
          required /></label
      ><button class="primary" :disabled="busy || !operational">
        {{ $t('companionApp.addAndInstall') }}
      </button>
    </form></AdminDialog
  >
  <ConfirmDialog /><CartridgeConsent />
</template>

<style scoped>
.station-shell {
  max-width: 1280px;
  margin: 0 auto;
  padding: 16px 20px 64px;
}
.station-unlock {
  display: flex;
  justify-content: center;
  margin: 0;
}
.station-unlock button,
.unlock-submit {
  min-width: 160px;
  min-height: 44px;
}
.unlock-submit {
  align-self: center;
  margin-inline: auto;
}
.station-users {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
  padding: 4px;
}
.station-user {
  display: flex;
  justify-content: flex-start;
  flex-direction: row;
  align-items: center;
  gap: 12px;
  padding: 12px;
  min-height: 68px;
  min-width: 0;
  border-radius: 12px;
}
.station-user > span:last-child {
  overflow-wrap: anywhere;
}
.station-selected-user {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  align-items: center;
  gap: 12px;
  text-align: center;
  overflow-wrap: anywhere;
}
.station-pin {
  max-width: 360px;
  margin-inline: auto;
  gap: 12px;
}
.station-user :deep(.user-avatar),
.station-selected-user :deep(.user-avatar) {
  width: 40px;
  height: 40px;
  font-size: 1.2rem;
}
.station-selected-user strong {
  flex: 1;
  min-width: 0;
  text-align: start;
}
.station-selected-user button {
  min-height: 44px;
}
.station-unlock-dialog :deep(.admin-dialog-heading) {
  padding: 12px 16px;
}
.station-unlock-dialog :deep(.admin-dialog-body) {
  padding: 16px;
}
.station-unlock-dialog :deep(.admin-dialog-heading button) {
  min-height: 44px;
}
.station-footer {
  position: fixed;
  inset: auto 0 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  grid-template-areas: 'source connection meta';
  align-items: center;
  gap: 8px 20px;
  padding: 12px 16px max(12px, env(safe-area-inset-bottom));
  background: var(--surface-dense);
  border-top: 1px solid var(--line);
  font-size: 0.875rem;
  color: var(--muted);
  z-index: 10;
}
.station-source {
  grid-area: source;
  justify-self: start;
}
.station-meta {
  grid-area: meta;
  display: flex;
  justify-content: flex-end;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 12px;
}
.station-version {
  font-variant-numeric: tabular-nums;
}
.station-credit {
  white-space: nowrap;
}
.station-credit a {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
}
.station-connection {
  grid-area: connection;
  justify-self: center;
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
@media (max-width: 799px) {
  .station-footer {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    grid-template-areas: 'connection connection' 'source meta';
  }
  .station-shell {
    padding-bottom: 128px;
  }
}
.connection-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--muted);
  flex-shrink: 0;
}
.connection-dot.connected {
  background: var(--success);
}
.station-heading {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  align-items: center;
  gap: 20px;
  margin-bottom: 16px;
}
.station-heading:has(.station-lock) {
  grid-template-columns: 1fr auto auto;
}
.station-heading > .language-picker {
  grid-column: 3;
  grid-row: 1;
  justify-self: end;
}
.station-title {
  min-width: 0;
}
.station-title h1 {
  font-size: 1.4rem;
  overflow-wrap: anywhere;
}
.station-title p {
  font-size: 0.875rem;
}
.station-update a {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
}
.station-locked {
  grid-column: 3;
  grid-row: 1;
  margin-right: 64px;
  display: flex;
  align-items: center;
  justify-content: end;
  gap: 8px;
  color: var(--muted);
  font-size: 0.875rem;
}
.station-locked svg {
  width: 18px;
  height: 18px;
}
.station-operator {
  max-width: 220px;
  overflow-wrap: anywhere;
}
.fleet-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin-bottom: 12px;
}
.fleet-toolbar h2 {
  margin: 0;
  font-size: 1.125rem;
}
.printer-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  align-items: start;
}
.printer-card-heading {
  display: flex;
  align-items: start;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 16px;
}
.printer-identity {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  flex: 1 1 180px;
}
.printer-identity > div {
  min-width: 0;
}
.printer-icon {
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  color: var(--muted);
}
.printer-identity h2 {
  font-size: 1.125rem;
  overflow-wrap: anywhere;
}
.printer-identity p {
  font-size: 0.875rem;
}
.printer-state {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.875rem;
  padding: 6px 8px;
  border-radius: 6px;
  background: var(--surface-secondary);
  color: var(--muted);
}
.printer-state svg {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
}
.printer-state.ready {
  color: var(--success-text);
  background: var(--success-fill);
}
.printer-state.printing {
  color: var(--accent-hover);
  background: var(--accent-fill);
}
.printer-state.danger {
  color: var(--danger-text);
  background: var(--danger-fill);
}
.printer-state.warning {
  color: #fbbf24;
  background: rgb(245 158 11 / 10%);
}
.printer-problem {
  color: var(--danger-text);
  overflow-wrap: anywhere;
}
.printer-actions:has(button) {
  border-top: 1px solid var(--line);
  padding-top: 12px;
}
.printer-actions button {
  min-height: 44px;
}
.station-printer.expanded {
  grid-column: 1 / -1;
}
.station-printer.expanded :deep(.printer-counts) {
  max-width: 500px;
}
.station-printer.expanded :deep(.printer-stock) {
  max-width: 560px;
}
.station-printer.expanded :deep(.printer-telemetry) {
  margin-bottom: 4px;
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
  min-width: 0;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--surface);
  display: grid;
  gap: 12px;
}
.station-printer h2 {
  margin: 0;
}
.printer-name-mode {
  gap: 0.5rem;
}
.printer-mode {
  font-size: 0.75rem;
}
.station-printer p {
  margin: 4px 0 0;
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
.station-job > label {
  min-width: 0;
  overflow-wrap: anywhere;
}
.station-queue-group {
  border-bottom: 1px solid var(--line);
}
.station-queue-group > .station-job {
  border-bottom: 0;
}
.station-run-rows {
  margin: 0 0 12px;
}
.station-run-rows summary {
  padding: 12px 6px;
  min-height: 44px;
}
.queue-print-actions {
  margin-top: 16px;
}
.queue-print-actions button {
  min-height: 44px;
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
    padding: 24px 16px 128px;
  }
  .station-heading,
  .station-heading:has(.station-lock) {
    grid-template-columns: 1fr auto;
    gap: 16px;
  }
  .station-title {
    grid-column: 1;
    grid-row: 1;
  }
  .station-unlock {
    grid-column: 1 / -1;
    grid-row: 2;
  }
  .station-locked {
    grid-column: 1 / -1;
    grid-row: 3;
    margin-right: 0;
    align-self: start;
  }
  .station-heading:has(.station-locked) .station-title {
    padding-right: 0;
  }
  .station-heading > .language-picker {
    grid-column: 2;
    grid-row: 1;
    justify-self: end;
  }
  .station-lock {
    grid-column: 1 / -1;
    justify-content: space-between;
  }
  .printer-grid {
    grid-template-columns: minmax(0, 1fr);
    gap: 16px;
  }
  .station-printer {
    padding: 16px;
  }
  .station-job {
    flex-wrap: wrap;
  }
}
</style>
