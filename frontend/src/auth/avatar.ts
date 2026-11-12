import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { api } from '../shared/api'
import { useAuthStore } from './auth'

export const useAvatarStore = defineStore('avatar', () => {
  const auth = useAuthStore()
  const version = ref<string | null>(null)
  const src = computed(() =>
    auth.user && version.value ? `/api/auth/avatar?v=${encodeURIComponent(version.value)}` : null,
  )
  let generation = 0
  let pending: Promise<void> | undefined

  function refresh(): Promise<void> {
    if (!auth.user) return Promise.resolve()
    if (pending) return pending
    const ticket = generation
    const request = api<{ avatar_version: string | null }>('/auth/avatar/info')
      .then((result) => {
        if (ticket === generation) version.value = result.avatar_version
      })
      .finally(() => {
        if (pending === request) pending = undefined
      })
    pending = request
    return request
  }

  function setVersion(value: string | null, owner: string | undefined) {
    if (!owner || owner !== auth.user?.id) return
    generation++
    pending = undefined
    version.value = value
  }

  watch(
    () => auth.user?.id,
    () => {
      generation++
      pending = undefined
      version.value = null
      void refresh().catch(() => {})
    },
    { immediate: true, flush: 'sync' },
  )
  return { version, src, refresh, setVersion }
})
