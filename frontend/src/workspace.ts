import { computed, ref, watch, toRaw, type Ref } from 'vue'
import { defineStore } from 'pinia'
import { useResourceStore } from './stores/resources'
import { errorMessage } from './api'
import { useAuthStore } from './auth'
import { ActionCancelled, resolveConfirmation } from './confirmation'
import { requestPrinting } from './printing'
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

export const useWorkspaceStore = defineStore('workspace', () => {
  const auth = useAuthStore()
  const resources = useResourceStore()
  const routePath = ref('/')
  const routeLoaded = ref('')
  const routeReady = computed(() => routePath.value === routeLoaded.value)
  const selectedPrinter = ref('')
  try {
    selectedPrinter.value = localStorage.getItem('selectedPrinter') || ''
  } catch {
    // The destination still works in memory when browser storage is blocked.
  }
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
  const inflight = new Map<string, Promise<void>>()
  let generation = 0
  function clear() {
    generation++
    inflight.clear()
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
    routeLoaded.value = ''
    busy.value = false
    actionError.value = ''
    success.value = ''
    connectionError.value = ''
    overview.value = { notifications_enabled: false, total_queued: 0 }
  }
  window.addEventListener('session-ended', clear)
  window.addEventListener('access-changed', clear)

  function updateIfChanged<T>(target: Ref<T>, value: T) {
    if (toRaw(target.value) === value) return
    if (JSON.stringify(target.value) !== JSON.stringify(value)) target.value = value
  }

  async function refresh(force = false): Promise<void> {
    if (!auth.user) return
    const path = routePath.value
    const key = path + ':' + (force === true)
    const existing = inflight.get(key)
    if (existing) return existing
    const ticket = generation
    const request = (async () => {
      try {
        await auth.refresh()
        if (!auth.user || ticket !== generation) return
        const read = <T>(url: string, ttl: number) =>
          resources.get<T>(url, { ttl, force: force === true })
        const apply = <T>(target: Ref<T>, value: T) => {
          if (ticket === generation && auth.user) updateIfChanged(target, value)
        }
        const tasks: Promise<unknown>[] = [
          read<typeof overview.value>('/workspace', 10000).then((value) => apply(overview, value)),
          read<Profile[]>('/tape-profiles', 60000).then((value) => apply(profiles, value)),
          read<Cartridge[]>('/cartridges', 10000).then((value) => apply(cartridges, value)),
          read<Printer[]>('/printers', 30000).then((value) => apply(printers, value)),
          read<Destination[]>('/destinations', 10000).then((value) => {
            apply(destinations, value)
            if (ticket === generation && !value.some((d) => d.id === selectedPrinter.value))
              selectedPrinter.value = value[0]?.id ?? ''
          }),
          read<Status[]>('/printers/status', 5000).then((value) => apply(printerStatuses, value)),
        ]
        if (auth.user.is_admin)
          tasks.push(
            read<AccessHold[]>('/access-holds', path === '/access-holds' ? 5000 : 15000).then(
              (value) => apply(accessHolds, value),
            ),
          )
        if (['/', '/activity', '/printers'].includes(path) || path.startsWith('/batches/'))
          tasks.push(read<Batch[]>('/batches', 5000).then((value) => apply(batches, value)))
        if (path === '/activity' && auth.user.is_admin)
          tasks.push(read<Notice[]>('/notifications', 10000).then((value) => apply(notices, value)))
        if (
          ['/templates', '/new'].includes(path) ||
          path.startsWith('/templates/') ||
          path.startsWith('/runs')
        )
          tasks.push(read<Template[]>('/templates', 60000).then((value) => apply(templates, value)))
        if (path === '/fonts' || path.startsWith('/templates/'))
          tasks.push(read<FontAsset[]>('/font-assets', 60000).then((value) => apply(fonts, value)))
        if (path === '/images' || path.startsWith('/templates/'))
          tasks.push(
            read<ImageAsset[]>('/image-assets', 60000).then((value) => apply(images, value)),
          )
        await Promise.all(tasks)
        if (ticket !== generation || !auth.user) return
        loaded.value = true
        if (routePath.value === path) routeLoaded.value = path
        connectionError.value = ''
      } catch (error) {
        if (ticket !== generation || !auth.user) return
        connectionError.value = `Cannot refresh the workspace. ${errorMessage(error)}`
      }
    })().finally(() => {
      if (inflight.get(key) === request) inflight.delete(key)
    })
    inflight.set(key, request)
    return request
  }
  async function setRoute(path: string) {
    routePath.value = path
    await refresh()
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
      // A poll may have already applied a pre-mutation snapshot while waiting
      // for another resource. Finish it, then read the invalidated resources.
      await Promise.all([...inflight.values()])
      if (ticket !== generation) return false
      await refresh()
      if (ticket !== generation) return false
      success.value = message
      return true
    } catch (error) {
      if (ticket !== generation) return false
      if (error instanceof ActionCancelled) return false
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
      status.value?.queues.find((q) => q.profile_id === activeProfile.value?.id)?.queued_copies ??
      0,
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
      () => requestPrinting(`/queue/print?printer_id=${encodeURIComponent(selectedPrinter.value)}`),
      'Manual batch requested. Its queued copies are now reserved for this flush.',
    )
  const profileName = (id: string) =>
    profiles.value.find((p) => p.id === id)?.name ?? 'Unknown tape'
  const cartridgeName = (id: string) =>
    cartridges.value.find((c) => c.id === id)?.name ?? 'Unknown cartridge'
  watch([selectedPrinter, printerStatuses], () => {
    status.value = printerStatuses.value.find((s) => s.printer_id === selectedPrinter.value) ?? null
    try {
      localStorage.setItem('selectedPrinter', selectedPrinter.value)
    } catch {
      // A full or disabled storage area must not interrupt the workspace.
    }
  })
  const destinationName = (id: string) => destinations.value.find((d) => d.id === id)?.name ?? id
  const destinationPrinter = (id: string) => {
    const target = destinations.value.find((d) => d.id === id)
    return target?.capabilities
      ? { capabilities: target.capabilities }
      : printers.value.find((p) => p.id === target?.printer_ids[0])
  }
  return {
    routeReady,
    routeLoaded,
    routePath,
    setRoute,
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
})
export const date = (seconds: number) =>
  new Date(seconds * 1000).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
export const metres = (mm: number) => `${(mm / 1000).toFixed(2)} m`
export const stateLabel = (value: string) => value.replaceAll('_', ' ')
