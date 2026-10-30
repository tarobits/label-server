import { computed, onUnmounted, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from './auth'
import { errorMessage } from './api'
import { useLiveRefresh } from './live'
import { useResourceStore } from './stores/resources'

interface HistoryPage<T> {
  items: T[]
  total: number
  before: number
}
export function useHistoryPage<T>(kind: 'batches' | 'notifications', enabled = () => true) {
  const route = useRoute(),
    router = useRouter(),
    auth = useAuthStore(),
    resources = useResourceStore()
  const key = `${kind}_page`,
    anchorKey = `${kind}_before`,
    size = 25
  const page = computed(() => {
    const value = Number(route.query[key])
    return Number.isSafeInteger(value) && value > 0 && value <= 1_000_000 ? value : 1
  })
  const anchor = computed(() => {
    const value = Number(route.query[anchorKey])
    return page.value > 1 && Number.isFinite(value) && value > 0 ? value : null
  })
  const items = shallowRef<T[]>([]),
    total = ref(0),
    loading = ref(false),
    error = ref('')
  const pages = computed(() => Math.max(1, Math.ceil(total.value / size)))
  const loadedPage = ref(0),
    snapshot = ref<number | null>(null)
  let sequence = 0,
    stopped = false
  function go(next: number, replace = false) {
    const query = { ...route.query }
    if (next <= 1) {
      delete query[key]
      delete query[anchorKey]
    } else {
      query[key] = String(next)
      if (snapshot.value) query[anchorKey] = String(snapshot.value)
    }
    return router[replace ? 'replace' : 'push']({ query })
  }
  async function load(background = false, force = false) {
    if (stopped || !enabled() || !auth.user) return
    const ticket = ++sequence,
      actor = auth.user.id,
      requestedPage = page.value
    if (!background || loadedPage.value !== requestedPage) loading.value = true
    try {
      const query = new URLSearchParams({
        limit: String(size),
        offset: String((requestedPage - 1) * size),
      })
      if (anchor.value !== null) query.set('before', String(anchor.value))
      const result = await resources.get<HistoryPage<T>>(`/${kind}/page?${query}`, {
        ttl: 5000,
        force,
      })
      if (stopped || ticket !== sequence || auth.user?.id !== actor || !enabled()) return
      snapshot.value = result.before
      total.value = result.total
      if (requestedPage > pages.value) {
        await go(pages.value, true)
        return
      }
      items.value = result.items
      loadedPage.value = requestedPage
      error.value = ''
      if (requestedPage > 1 && anchor.value === null) await go(requestedPage, true)
    } catch (cause) {
      if (!stopped && ticket === sequence && auth.user?.id === actor) {
        if (loadedPage.value !== requestedPage) items.value = []
        error.value = errorMessage(cause)
      }
    } finally {
      if (ticket === sequence) loading.value = false
    }
  }
  watch([page, anchor], () => {
    void load(false, true)
  })
  watch([() => auth.user?.id, enabled], () => {
    sequence++
    items.value = []
    total.value = 0
    loadedPage.value = 0
    error.value = ''
    void load()
  })
  useLiveRefresh(
    () => (loading.value ? Promise.resolve() : load(loadedPage.value > 0)),
    kind === 'batches' ? 5000 : 10000,
  )
  onUnmounted(() => {
    stopped = true
    sequence++
  })
  const pagination = computed(() => ({
    page: page.value,
    pages: loadedPage.value ? pages.value : null,
    loading: loading.value,
  }))
  return {
    items,
    total,
    page,
    pages,
    loadedPage,
    loading,
    error,
    pagination,
    go,
    retry: () => load(false, true),
  }
}
