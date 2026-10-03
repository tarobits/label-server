import { computed, ref, type Ref } from 'vue'
import { api, errorMessage } from './api'
import type {
  Batch,
  Cartridge,
  FontAsset,
  ImageAsset,
  Notice,
  Printer,
  Profile,
  Status,
  Template,
} from './types'

const status = ref<Status | null>(null)
const printers = ref<Printer[]>([])
const profiles = ref<Profile[]>([])
const cartridges = ref<Cartridge[]>([])
const batches = ref<Batch[]>([])
const notices = ref<Notice[]>([])
const templates = ref<Template[]>([])
const fonts = ref<FontAsset[]>([])
const images = ref<ImageAsset[]>([])
const connectionError = ref('')
const actionError = ref('')
const success = ref('')
const busy = ref(false)
const loaded = ref(false)
let inflight: Promise<void> | null = null

function updateIfChanged<T>(target: Ref<T>, value: T) {
  if (JSON.stringify(target.value) !== JSON.stringify(value)) target.value = value
}

async function refresh(): Promise<void> {
  if (inflight) return inflight
  inflight = (async () => {
    try {
      const [s, p, c, b, n, t, f, i, devices] = await Promise.all([
        api<Status>('/status'),
        api<Profile[]>('/tape-profiles'),
        api<Cartridge[]>('/cartridges'),
        api<Batch[]>('/batches'),
        api<Notice[]>('/notifications'),
        api<Template[]>('/templates'),
        api<FontAsset[]>('/font-assets'),
        api<ImageAsset[]>('/image-assets'),
        api<Printer[]>('/printers'),
      ])
      updateIfChanged(status, s)
      updateIfChanged(profiles, p)
      updateIfChanged(cartridges, c)
      updateIfChanged(batches, b)
      updateIfChanged(notices, n)
      updateIfChanged(templates, t)
      updateIfChanged(fonts, f)
      updateIfChanged(images, i)
      updateIfChanged(printers, devices)
      loaded.value = true
      connectionError.value = ''
    } catch (error) {
      connectionError.value = `Cannot refresh the workspace. ${errorMessage(error)}`
    }
  })().finally(() => {
    inflight = null
  })
  return inflight
}
async function action(task: () => Promise<unknown>, message: string): Promise<boolean> {
  if (busy.value) return false
  busy.value = true
  actionError.value = ''
  success.value = ''
  try {
    await task()
    if (inflight) await inflight
    await refresh()
    success.value = message
    return true
  } catch (error) {
    actionError.value = errorMessage(error)
    return false
  } finally {
    busy.value = false
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
const totalQueued = computed(
  () => status.value?.queues.reduce((total, q) => total + q.queued_copies, 0) ?? 0,
)
const locked = computed(() => !!status.value?.printing || !!status.value?.needs_review.length)
const canPrint = computed(
  () =>
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
    () => api('/queue/print', 'POST'),
    'Manual batch requested. Its queued copies are now reserved for this flush.',
  )
const profileName = (id: string) => profiles.value.find((p) => p.id === id)?.name ?? 'Unknown tape'
const cartridgeName = (id: string) =>
  cartridges.value.find((c) => c.id === id)?.name ?? 'Unknown cartridge'
export const workspace = {
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
