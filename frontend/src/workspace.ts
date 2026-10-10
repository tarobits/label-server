import { computed, ref, watch, type Ref } from 'vue'
import { api, errorMessage } from './api'
import { auth } from './auth'
import { resolveConfirmation } from './confirmation'
import type {
  Batch,
  Destination,
  Cartridge,
  FontAsset,
  ImageAsset,
  Notice,
  Printer,
  Profile,
  Status,
  Template,
  AccessHold,
} from './types'

const selectedPrinter = ref(localStorage.getItem('selectedPrinter') || '')
const printerStatuses = ref<Status[]>([])
const destinations = ref<Destination[]>([])
const status = ref<Status | null>(null)
const overview = ref({ notifications_enabled: false, total_queued: 0 })
const printers = ref<Printer[]>([])
const profiles = ref<Profile[]>([])
const cartridges = ref<Cartridge[]>([])
const batches = ref<Batch[]>([])
const notices = ref<Notice[]>([])
const templates = ref<Template[]>([])
const fonts = ref<FontAsset[]>([])
const images = ref<ImageAsset[]>([])
const accessHolds = ref<AccessHold[]>([])
const connectionError = ref('')
const actionError = ref('')
const success = ref('')
const busy = ref(false)
const loaded = ref(false)
let inflight: Promise<void> | null = null
let generation = 0
function clear() {
  generation++
  resolveConfirmation(false)
  status.value = null
  printers.value = []
  printerStatuses.value = []
  destinations.value = []
  profiles.value = []
  cartridges.value = []
  batches.value = []
  notices.value = []
  templates.value = []
  fonts.value = []
  images.value = []
  accessHolds.value = []
  loaded.value = false
  busy.value = false
  actionError.value = ''
  success.value = ''
  connectionError.value = ''
  overview.value = { notifications_enabled: false, total_queued: 0 }
}
window.addEventListener('session-ended', clear)

function updateIfChanged<T>(target: Ref<T>, value: T) {
  if (JSON.stringify(target.value) !== JSON.stringify(value)) target.value = value
}

async function refresh(): Promise<void> {
  if (!auth.user.value) return
  if (inflight) return inflight
  const ticket = generation
  inflight = (async () => {
    try {
      await auth.refresh()
      if (!auth.user.value || ticket !== generation) return
      const [info, p, c, b, n, t, f, i, devices, targets, states, holds] = await Promise.all([
        api<typeof overview.value>('/workspace'),
        api<Profile[]>('/tape-profiles'),
        api<Cartridge[]>('/cartridges'),
        api<Batch[]>('/batches'),
        auth.user.value?.is_admin ? api<Notice[]>('/notifications') : Promise.resolve([]),
        api<Template[]>('/templates'),
        api<FontAsset[]>('/font-assets'),
        api<ImageAsset[]>('/image-assets'),
        api<Printer[]>('/printers'),
        api<Destination[]>('/destinations'),
        api<Status[]>('/printers/status'),
        auth.user.value?.is_admin ? api<AccessHold[]>('/access-holds') : Promise.resolve([]),
      ])
      if (ticket !== generation || !auth.user.value) return
      if (!targets.some((d) => d.id === selectedPrinter.value))
        selectedPrinter.value = targets[0]?.id ?? ''
      updateIfChanged(status, states.find((s) => s.printer_id === selectedPrinter.value) ?? null)
      updateIfChanged(overview, info)
      updateIfChanged(destinations, targets)
      updateIfChanged(printerStatuses, states)
      updateIfChanged(profiles, p)
      updateIfChanged(cartridges, c)
      updateIfChanged(batches, b)
      updateIfChanged(notices, n)
      updateIfChanged(templates, t)
      updateIfChanged(fonts, f)
      updateIfChanged(images, i)
      updateIfChanged(printers, devices)
      updateIfChanged(accessHolds, holds)
      loaded.value = true
      connectionError.value = ''
    } catch (error) {
      if (ticket !== generation || !auth.user.value) return
      connectionError.value = `Cannot refresh the workspace. ${errorMessage(error)}`
    }
  })().finally(() => {
    inflight = null
  })
  return inflight
}
async function action(task: () => Promise<unknown>, message: string): Promise<boolean> {
  if (busy.value) return false
  const ticket = generation
  busy.value = true
  actionError.value = ''
  success.value = ''
  try {
    await task()
    if (ticket !== generation) return false
    if (inflight) await inflight
    await refresh()
    if (ticket !== generation) return false
    success.value = message
    return true
  } catch (error) {
    if (ticket !== generation) return false
    actionError.value = errorMessage(error)
    return false
  } finally {
    if (ticket === generation) busy.value = false
  }
}
const activeCartridge = computed(() =>
  cartridges.value.find((c) => c.id === status.value?.active_cartridge_id),
)
const activeProfile = computed(() =>
  profiles.value.find((p) => p.id === activeCartridge.value?.profile_id),
)
const activeCount = computed(
  () =>
    status.value?.queues.find((q) => q.profile_id === activeProfile.value?.id)?.queued_copies ?? 0,
)
const totalQueued = computed(() => overview.value.total_queued)
const locked = computed(() => !!status.value?.printing || !!status.value?.needs_review.length)
const canPrint = computed(
  () =>
    auth.atLeast(selectedPrinter.value, 'moderator') &&
    !busy.value &&
    !connectionError.value &&
    !locked.value &&
    !!activeCartridge.value &&
    activeCount.value > 0 &&
    !!status.value?.connected &&
    !status.value?.printer_error &&
    status.value.detected_width_mm === activeProfile.value?.width_mm &&
    !status.value.pending_flush,
)
const printNow = () =>
  action(
    () => api(`/queue/print?printer_id=${encodeURIComponent(selectedPrinter.value)}`, 'POST'),
    'Manual batch requested. Its queued copies are now reserved for this flush.',
  )
const profileName = (id: string) => profiles.value.find((p) => p.id === id)?.name ?? 'Unknown tape'
const cartridgeName = (id: string) =>
  cartridges.value.find((c) => c.id === id)?.name ?? 'Unknown cartridge'
watch(selectedPrinter, () => {
  status.value = printerStatuses.value.find((s) => s.printer_id === selectedPrinter.value) ?? null
  localStorage.setItem('selectedPrinter', selectedPrinter.value)
})
const destinationName = (id: string) => destinations.value.find((d) => d.id === id)?.name ?? id
const destinationPrinter = (id: string) => {
  const target = destinations.value.find((d) => d.id === id)
  return target?.capabilities
    ? { capabilities: target.capabilities }
    : printers.value.find((p) => p.id === target?.printer_ids[0])
}
export const workspace = {
  accessHolds,
  clear,
  overview,
  selectedPrinter,
  printerStatuses,
  destinations,
  destinationName,
  destinationPrinter,
  status,
  printers,
  profiles,
  cartridges,
  batches,
  notices,
  templates,
  fonts,
  images,
  loaded,
  busy,
  connectionError,
  actionError,
  success,
  refresh,
  action,
  activeCartridge,
  activeProfile,
  activeCount,
  totalQueued,
  locked,
  canPrint,
  printNow,
  profileName,
  cartridgeName,
}
export const date = (seconds: number) =>
  new Date(seconds * 1000).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
export const metres = (mm: number) => `${(mm / 1000).toFixed(2)} m`
export const stateLabel = (value: string) => value.replaceAll('_', ' ')
