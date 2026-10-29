import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api, configureSession, errorMessage } from './api'
export type AccessLevel = 'none' | 'request' | 'print' | 'moderator' | 'full'
export const accessLevels: { value: AccessLevel; label: string }[] = [
  { value: 'none', label: 'No access' },
  { value: 'request', label: 'Request only' },
  { value: 'print', label: 'Print' },
  { value: 'moderator', label: 'Moderator' },
  { value: 'full', label: 'Full' },
]
export interface GroupRights {
  can_create: boolean
  can_edit_others: boolean
  can_delete_others: boolean
}
export interface Membership extends GroupRights {
  images?: GroupRights
  fonts?: GroupRights
}

export interface User {
  id: string
  username: string
  is_admin: boolean
  permissions: string[]
  group_ids: string[]
  printer_ids: string[]
  role_ids: string[]
  destination_levels: Record<string, AccessLevel>
  group_memberships: Record<string, Membership>
}
export interface Session {
  setup_required: boolean
  registration_code_required: boolean
  user: User | null
  csrf_token: string | null
}
export const useAuthStore = defineStore('auth', () => {
  const session = ref<Session | null>(null)
  const ready = ref(false)
  const error = ref('')
  const user = computed(() => session.value?.user ?? null)
  const can = (permission: string) =>
    !!user.value && (user.value.is_admin || user.value.permissions.includes(permission))
  const canCreateTemplates = computed(
    () =>
      can('templates.create_personal') ||
      can('templates.create_global') ||
      Object.values(user.value?.group_memberships ?? {}).some(
        (membership) => membership.can_create,
      ),
  )
  const canUpload = (kind: 'images' | 'fonts') =>
    can(`${kind}.create_personal`) ||
    can(`${kind}.create_global`) ||
    Object.values(user.value?.group_memberships ?? {}).some((member) => member[kind]?.can_create)
  const level = (destination: string) =>
    user.value?.is_admin ? 'full' : (user.value?.destination_levels?.[destination] ?? 'none')
  const atLeast = (destination: string, minimum: AccessLevel) =>
    accessLevels.findIndex((l) => l.value === level(destination)) >=
    accessLevels.findIndex((l) => l.value === minimum)
  const any = (minimum: AccessLevel) =>
    !!user.value?.is_admin ||
    Object.keys(user.value?.destination_levels ?? {}).some((id) => atLeast(id, minimum))
  let fetchedAt = 0,
    generation = 0
  let pending: Promise<void> | null = null
  let forced: Promise<void> | null = null
  function accept(value: Session) {
    const previous = JSON.stringify(session.value?.user ?? null)
    const changed = session.value?.user?.id !== value.user?.id
    if (changed) {
      generation++
      pending = null
      forced = null
    }
    if (JSON.stringify(session.value) !== JSON.stringify(value)) session.value = value
    fetchedAt = Date.now()
    configureSession(value.csrf_token, () => {
      if (session.value) session.value = { ...session.value, user: null, csrf_token: null }
      configureSession(null)
      generation++
      pending = null
      forced = null
      fetchedAt = 0
      window.dispatchEvent(new Event('session-ended'))
    })
    ready.value = true
    if (changed) window.dispatchEvent(new Event('session-ended'))
    else if (previous !== JSON.stringify(value.user))
      window.dispatchEvent(new Event('access-changed'))
  }
  async function refresh(force = false) {
    if (force === true && pending) {
      if (forced) return forced
      const ticket = generation
      const previous = pending
      const following = previous
        .then(async () => {
          if (ticket === generation) await refresh(true)
        })
        .finally(() => {
          if (forced === following) forced = null
        })
      forced = following
      return following
    }
    if (pending) return pending
    if (force !== true && ready.value && Date.now() - fetchedAt < 30000) return
    error.value = ''
    const ticket = generation
    const request = (async () => {
      try {
        const result = await api<Session>('/auth/session')
        if (ticket === generation) accept(result)
      } catch (e) {
        if (ticket === generation) error.value = errorMessage(e)
      }
    })().finally(() => {
      if (pending === request) pending = null
    })
    pending = request
    return request
  }
  async function logout() {
    await api('/auth/logout', 'POST', {})
    if (session.value) accept({ ...session.value, user: null, csrf_token: null })
    window.dispatchEvent(new Event('session-ended'))
    await refresh(true)
  }
  return {
    session,
    user,
    ready,
    error,
    can,
    canCreateTemplates,
    canUpload,
    level,
    atLeast,
    any,
    accept,
    refresh,
    logout,
  }
})
