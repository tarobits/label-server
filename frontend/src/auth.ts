import { computed, ref } from 'vue'
import { api, configureSession, errorMessage } from './api'
export type AccessLevel = 'none' | 'request' | 'print' | 'moderator' | 'full'
export const accessLevels: { value: AccessLevel; label: string }[] = [
  { value: 'none', label: 'No access' },
  { value: 'request', label: 'Request only' },
  { value: 'print', label: 'Print' },
  { value: 'moderator', label: 'Moderator' },
  { value: 'full', label: 'Full' },
]
export interface Membership {
  can_create: boolean
  can_edit_others: boolean
  can_delete_others: boolean
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
const session = ref<Session | null>(null)
const ready = ref(false)
const error = ref('')
const user = computed(() => session.value?.user ?? null)
const can = (permission: string) =>
  !!user.value && (user.value.is_admin || user.value.permissions.includes(permission))
const level = (destination: string) =>
  user.value?.is_admin ? 'full' : (user.value?.destination_levels?.[destination] ?? 'none')
const atLeast = (destination: string, minimum: AccessLevel) =>
  accessLevels.findIndex((l) => l.value === level(destination)) >=
  accessLevels.findIndex((l) => l.value === minimum)
const any = (minimum: AccessLevel) =>
  !!user.value?.is_admin ||
  Object.keys(user.value?.destination_levels ?? {}).some((id) => atLeast(id, minimum))
function accept(value: Session) {
  session.value = value
  configureSession(value.csrf_token, () => {
    if (session.value) session.value = { ...session.value, user: null, csrf_token: null }
    configureSession(null)
    window.dispatchEvent(new Event('session-ended'))
  })
  ready.value = true
}
async function refresh() {
  error.value = ''
  try {
    accept(await api<Session>('/auth/session'))
  } catch (e) {
    error.value = errorMessage(e)
  }
}
async function logout() {
  await api('/auth/logout', 'POST', {})
  if (session.value) accept({ ...session.value, user: null, csrf_token: null })
  window.dispatchEvent(new Event('session-ended'))
  await refresh()
}
export const auth = {
  session,
  user,
  ready,
  error,
  can,
  level,
  atLeast,
  any,
  accept,
  refresh,
  logout,
}
