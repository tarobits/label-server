import { defineStore } from 'pinia'
import { shallowRef } from 'vue'
import type { AccessLevel, Membership } from '../auth'
import { useResourceStore } from './resources'

export interface Person {
  id: string
  username: string
  is_admin: boolean
  disabled: boolean
  role_ids: string[]
}
export interface DeletedItem {
  kind: 'users' | 'templates' | 'images' | 'fonts'
  identifier: string
  name: string
  owner_id: string
  deleted_at: number
  purge_after: number
  account_id: string | null
}
export type Permission =
  | { kind: 'application'; permission: string }
  | { kind: 'destination'; destination_id: string; level: AccessLevel }
export interface Role {
  id: string
  name: string
  protected: boolean
  permissions: Permission[]
}
export interface Member extends Membership {
  user_id: string
}
export interface Group {
  id: string
  name: string
  members: Member[]
}
export interface Code {
  id: string
  name: string
  expires_at: number | null
  redeemed_at: number | null
  revoked: boolean
}
export interface AccountSettings {
  registration_code_required: boolean
  approval_notification_debounce_seconds: number
  approval_notifications_enabled: boolean
}
export interface NotificationEndpoint {
  id: string
  name: string
  url: string
  topic: string
  enabled: boolean
  all_printers: boolean
  destination_ids: string[]
  kinds: string[]
  priorities: Record<string, number>
  has_token: boolean
}

const paths = {
  users: '/admin/users',
  roles: '/admin/roles',
  groups: '/admin/groups',
  codes: '/admin/registration-codes',
  permissions: '/admin/permissions',
  settings: '/admin/settings',
  endpoints: '/admin/notification-endpoints',
  trash: '/admin/trash',
} as const
export type AdminResource = keyof typeof paths
const initialResources: AdminResource[] = [
  'users',
  'roles',
  'groups',
  'codes',
  'permissions',
  'settings',
  'trash',
]

export const useAdministrationStore = defineStore('administration', () => {
  const resources = useResourceStore()
  const users = shallowRef<Person[]>([])
  const roles = shallowRef<Role[]>([])
  const groups = shallowRef<Group[]>([])
  const codes = shallowRef<Code[]>([])
  const permissions = shallowRef<{ id: string; label: string }[]>([])
  const settings = shallowRef<AccountSettings | null>(null)
  const endpoints = shallowRef<NotificationEndpoint[]>([])
  const trash = shallowRef<DeletedItem[]>([])
  let generation = 0
  const loadedKeys = new Set<AdminResource>()

  async function load(keys: AdminResource[] = initialResources): Promise<boolean> {
    const ticket = generation
    const requested = new Set(keys)
    if (keys.some((key) => key !== 'endpoints')) {
      for (const key of initialResources) if (!loadedKeys.has(key)) requested.add(key)
    }
    const loaded = await Promise.all(
      [...requested].map(async (key) => ({
        key,
        value: await resources.get<unknown>(paths[key], { ttl: 60_000 }),
      })),
    ).catch((issue) => {
      if (ticket !== generation) return []
      throw issue
    })
    if (ticket !== generation) return false
    for (const { key, value } of loaded) {
      loadedKeys.add(key)
      switch (key) {
        case 'users':
          users.value = value as Person[]
          break
        case 'roles':
          roles.value = value as Role[]
          break
        case 'groups':
          groups.value = value as Group[]
          break
        case 'codes':
          codes.value = value as Code[]
          break
        case 'permissions':
          permissions.value = value as { id: string; label: string }[]
          break
        case 'settings':
          settings.value = value as AccountSettings
          break
        case 'endpoints':
          endpoints.value = value as NotificationEndpoint[]
          break
        case 'trash':
          trash.value = value as DeletedItem[]
          break
      }
    }
    return true
  }

  function reset() {
    generation++
    loadedKeys.clear()
    users.value = []
    roles.value = []
    groups.value = []
    codes.value = []
    permissions.value = []
    settings.value = null
    endpoints.value = []
    trash.value = []
  }
  window.addEventListener('session-ended', reset)
  window.addEventListener('access-changed', reset)
  return { users, roles, groups, codes, permissions, settings, endpoints, trash, load, reset }
})
