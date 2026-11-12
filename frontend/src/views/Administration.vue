<script setup lang="ts">
import { t } from '../shared/i18n'

import { vValidateForm } from '../shared/formValidation'
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { api, ApiError, errorMessage } from '../shared/api'
import { useAuthStore, accessLevels, type AccessLevel, type Membership } from '../auth/auth'
import { useWorkspaceStore, date } from '../shared/workspace'
import { useRoute, useRouter } from 'vue-router'
import { confirmAction } from '../shared/confirmation'
import AdminDialog from '../components/AdminDialog.vue'
import PermissionRules from '../components/PermissionRules.vue'
import type { AccessCatalog } from '../shared/resourceAccess'
import { permissionLabel } from '../shared/resourceAccess'
import MotionSurface from '../components/MotionSurface.vue'
import MotionTrack from '../components/MotionTrack.vue'
import NotificationEndpoints from '../components/NotificationEndpoints.vue'
import AnimatedDetails from '../components/AnimatedDetails.vue'
import GroupPermissionsFields from '../components/GroupPermissionsFields.vue'
import {
  legacyPrinterPermissions,
  exclusiveSubmissionPermissions,
  permissionOptions,
  printerPreset,
  printerPermissionLabel,
} from '../printing/printerPermissions'
import {
  useAdministrationStore,
  type AdminResource,
  type Person,
  type Permission,
  type Role,
  type Member,
  type Group,
  type DeletedItem,
} from '../stores/administration'
interface Effective {
  username: string
  is_admin: boolean
  disabled: boolean
  permissions: string[]
  destination_levels: Record<string, AccessLevel>
  destination_permissions?: Record<string, string[]>
  cartridge_permissions?: Record<string, string[]>
  group_memberships: Record<string, Membership>
}
interface Impact {
  confirmation_token: string
  owner_loss_warning?: boolean
  affected_users: {
    id: string
    username: string
    before: Effective | null
    after: Effective | null
    changed: boolean
  }[]
}
interface Change {
  resource: 'users' | 'roles' | 'groups'
  identifier?: string
  method: 'POST' | 'PUT' | 'DELETE' | 'RESTORE'
  payload: unknown
  message: string
  done?: () => void
}
const route = useRoute()
const router = useRouter()
const sections = [
  {
    id: 'users',
    get title() {
      return t('common.users')
    },
  },
  {
    id: 'roles',
    get title() {
      return t('administration.roles')
    },
  },
  {
    id: 'groups',
    get title() {
      return t('administration.contentGroups')
    },
  },
  {
    id: 'codes',
    get title() {
      return t('administration.registrationCodes')
    },
  },
  {
    id: 'settings',
    get title() {
      return t('navigation.account')
    },
  },
  {
    id: 'notifications',
    get title() {
      return t('notificationEndpoints.notificationEndpoints')
    },
  },
  {
    id: 'trash',
    get title() {
      return t('administration.deletedAccountsAndContent')
    },
  },
] as const
const navigationGroups = [
  { title: 'Accounts', sections: sections.slice(0, 4) },
  { title: 'General', sections: sections.slice(4) },
]
const section = computed(
  () => sections.find((item) => item.id === route.query.section) ?? sections[0],
)
const search = ref('')
function navigate(id: string) {
  search.value = ''
  error.value = ''
  success.value = ''
  void router.replace({ query: { ...route.query, section: id } })
}
const editor = ref<'user' | 'new-user' | 'role' | 'group' | 'code' | null>(null)
const editorTitle = computed(() =>
  editor.value === 'user'
    ? `Edit ${selectedUser.value?.username}`
    : editor.value === 'new-user'
      ? t('administration.createAnAccount')
      : editor.value === 'role'
        ? roleForm.id
          ? `Edit ${roleForm.name}`
          : t('administration.newRole')
        : editor.value === 'group'
          ? groupForm.id
            ? `Edit ${groupForm.name}`
            : t('administration.newContentGroup')
          : t('administration.newRegistrationCode'),
)
const loading = ref(true)
const w = useWorkspaceStore()
const auth = useAuthStore()
const administration = useAdministrationStore()
const { users, roles, groups, codes, permissions, trash } = storeToRefs(administration)
const busy = ref(false),
  error = ref(''),
  success = ref(''),
  issuedCode = ref('')
const settings = reactive({
  batch_review_evidence: 'optional',
  registration_code_required: true,
  approval_notification_debounce_seconds: 60,
  approval_notifications_enabled: true,
})
const accessCatalog = ref<AccessCatalog>()
const roleForm = reactive({
  id: '',
  name: '',
  applications: [] as string[],
  destinations: {} as Record<string, string[]>,
  destinationDenials: {} as Record<string, string[]>,
  locations: {} as Record<string, { permissions: string[]; denied_permissions: string[] }>,
})
const groupForm = reactive({ id: '', name: '', members: [] as Member[] })
const codeForm = reactive({
  name: '',
  expires_in_days: 7,
  role_ids: ['member'],
  group_ids: [] as string[],
  group_permissions: {} as Record<string, Membership>,
})
const userForm = reactive({ username: '', password: '', role_ids: ['member'] })
const selectedUser = ref<Person | null>(null),
  password = ref(''),
  impact = ref<Impact | null>(null),
  change = ref<Change | null>(null),
  previewError = ref(''),
  previewDialog = ref<HTMLDialogElement | null>(null)
const deletingAccount = computed(
  () => change.value?.resource === 'users' && change.value.method === 'DELETE',
)
const levelName = (level: AccessLevel) =>
  accessLevels.find((item) => item.value === level)?.label ?? level
async function load(keys?: AdminResource[]) {
  if (!(await administration.load(keys))) return
  if (!keys || keys.includes('roles'))
    accessCatalog.value = await api<AccessCatalog>('/resource-access')
  if (!keys || keys.includes('settings')) Object.assign(settings, administration.settings)
}
async function perform(task: () => Promise<unknown>, message: string, reload: AdminResource[]) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  success.value = ''
  try {
    await task()
    await load(reload)
    await auth.refresh()
    await w.refresh()
    success.value = message
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}
const matches = (value: string) => value.toLowerCase().includes(search.value.trim().toLowerCase())
const filteredUsers = computed(() =>
  users.value.filter((user) => matches(user.username + ' ' + roleNames(user.role_ids))),
)
const filteredRoles = computed(() =>
  roles.value.filter((role) => matches(role.name + ' ' + roleSummary(role))),
)
const filteredGroups = computed(() => groups.value.filter((group) => matches(group.name)))
const filteredCodes = computed(() => codes.value.filter((code) => matches(code.name)))
const filteredTrash = computed(() => trash.value.filter((item) => matches(item.name)))
const roleNames = (ids: string[]) =>
  ids.map((id) => roles.value.find((role) => role.id === id)?.name ?? id).join(', ') || 'No roles'
function roleSummary(role: Role) {
  if (role.protected) return 'Universal access'
  return (
    role.permissions
      .filter((permission) => permission.kind !== 'destination' || permission.level !== 'none')
      .map((permission) =>
        permission.kind === 'application'
          ? (permissions.value.find((item) => item.id === permission.permission)?.label ??
            permission.permission)
          : permission.kind === 'location_permissions'
            ? `${accessCatalog.value?.locations.find((location) => location.id === permission.location_id)?.name ?? permission.location_id} · ${permission.permissions.length} allowed, ${permission.denied_permissions?.length ?? 0} denied`
            : `${w.destinationName(permission.destination_id)} · ${permission.kind === 'destination' ? levelName(permission.level) : `${permission.permissions.length} allowed, ${permission.denied_permissions?.length ?? 0} denied`}`,
      )
      .join('; ') || 'No additional access'
  )
}
const normalized = (value: unknown) => JSON.stringify(value)
const sorted = (values: string[]) => [...values].sort()
const rolePermissions = () => [
  ...roleForm.applications.map((permission) => ({ kind: 'application' as const, permission })),
  ...Object.entries(roleForm.destinations)
    .filter(([id, permissions]) => permissions.length || roleForm.destinationDenials[id]?.length)
    .map(([destination_id, permissions]) => ({
      kind: 'destination_permissions' as const,
      destination_id,
      permissions: [...permissions].sort(),
      denied_permissions: [...(roleForm.destinationDenials[destination_id] ?? [])].sort(),
    })),
  ...Object.entries(roleForm.locations)
    .filter(([, rules]) => rules.permissions.length || rules.denied_permissions.length)
    .map(([location_id, rules]) => ({
      kind: 'location_permissions' as const,
      location_id,
      permissions: [...rules.permissions].sort(),
      denied_permissions: [...rules.denied_permissions].sort(),
    })),
]
const permissionGroups = computed(() => [
  ...(['templates', 'images', 'fonts'] as const).map((kind) => ({
    title: `${kind === 'templates' ? t('common.template') : kind === 'images' ? t('templateEditor.image') : t('templateEditor.font')} permissions`,
    options: permissions.value.filter((permission) => permission.id.startsWith(`${kind}.`)),
  })),
  {
    title: 'Application permissions',
    options: permissions.value.filter(
      (permission) => !/^(templates|images|fonts)\./.test(permission.id),
    ),
  },
])
const sortedPermissions = (values: Permission[]) =>
  values
    .flatMap((p) => {
      if (p.kind === 'application') return [`application:${p.permission}`]
      const scope =
        p.kind === 'location_permissions'
          ? `location:${p.location_id}`
          : `destination:${p.destination_id}`
      const allowed =
        p.kind === 'destination'
          ? legacyPrinterPermissions(
              p.level,
              w.destinations.find((d) => d.id === p.destination_id)?.kind === 'group',
            )
          : p.permissions
      return [
        ...exclusiveSubmissionPermissions(allowed).map(
          (permission) => `${scope}:allow:${permission}`,
        ),
        ...(p.kind === 'destination' ? [] : (p.denied_permissions ?? [])).map(
          (permission) => `${scope}:deny:${permission}`,
        ),
      ]
    })
    .sort()
const sortedMembers = (values: Member[]) =>
  [...values]
    .sort((a, b) => a.user_id.localeCompare(b.user_id))
    .map((member) => [
      member.user_id,
      member.can_create,
      member.can_edit_others,
      member.can_delete_others,
      ...[member.images, member.fonts].flatMap((rights) => [
        !!rights?.can_create,
        !!rights?.can_edit_others,
        !!rights?.can_delete_others,
      ]),
    ])
const editorChanged = computed(() => {
  if (editor.value === 'user') {
    const current = users.value.find((user) => user.id === selectedUser.value?.id)
    return (
      !!current &&
      !!selectedUser.value &&
      (password.value !== '' ||
        current.username !== selectedUser.value.username ||
        current.disabled !== selectedUser.value.disabled ||
        normalized(sorted(current.role_ids)) !== normalized(sorted(selectedUser.value.role_ids)))
    )
  }
  if (editor.value === 'role' && roleForm.id) {
    const current = roles.value.find((role) => role.id === roleForm.id)
    return (
      !!current &&
      (roleForm.name !== current.name ||
        normalized(sortedPermissions(rolePermissions())) !==
          normalized(sortedPermissions(current.permissions)))
    )
  }
  if (editor.value === 'group' && groupForm.id) {
    const current = groups.value.find((group) => group.id === groupForm.id)
    return (
      !!current &&
      (groupForm.name !== current.name ||
        normalized(sortedMembers(groupForm.members)) !== normalized(sortedMembers(current.members)))
    )
  }
  return true
})
const changedUsers = computed(
  () => impact.value?.affected_users.filter((item) => item.changed) ?? [],
)
const unchangedUsers = computed(
  () => impact.value?.affected_users.filter((item) => !item.changed) ?? [],
)
function closeEditor() {
  if (busy.value) return
  editor.value = null
  selectedUser.value = null
  password.value = ''
  error.value = ''
}
function newUser() {
  Object.assign(userForm, { username: '', password: '', role_ids: ['member'] })
  error.value = ''
  editor.value = 'new-user'
}
function newCode() {
  Object.assign(codeForm, {
    name: '',
    expires_in_days: 7,
    role_ids: ['member'],
    group_ids: [],
    group_permissions: {},
  })
  error.value = ''
  editor.value = 'code'
}
const previewBody = (value: Change) => ({
  resource: value.resource,
  identifier: value.identifier,
  method: value.method,
  payload: value.payload,
})
async function preview(value: Change) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  previewError.value = ''
  try {
    change.value = value
    impact.value = await api<Impact>('/admin/access-preview', 'POST', previewBody(value))
    await nextTick()
    if (!previewDialog.value?.open) previewDialog.value?.showModal()
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}
function cancelPreview() {
  if (busy.value) return
  previewDialog.value?.close()
  impact.value = null
  change.value = null
}
async function applyChange() {
  const value = change.value,
    confirmation = impact.value
  if (!value || !confirmation || busy.value) return
  busy.value = true
  previewError.value = ''
  try {
    await api(
      `/admin/${value.resource}${value.identifier ? '/' + value.identifier : ''}${value.method === 'RESTORE' ? '/restore' : ''}`,
      value.method === 'RESTORE' ? 'POST' : value.method,
      value.payload,
      { 'X-Access-Confirmation': confirmation.confirmation_token },
    )
    previewDialog.value?.close()
    value.done?.()
    editor.value = null
    selectedUser.value = null
    password.value = ''
    impact.value = null
    change.value = null
    await auth.refresh(true)
    if (auth.user?.is_admin) {
      const reload: AdminResource[] = [value.resource, 'trash']
      if (value.resource === 'groups') reload.push('users')
      if (value.method === 'DELETE' || value.method === 'RESTORE') {
        reload.push('codes')
        if (value.resource === 'roles') reload.push('users')
        if (value.resource === 'users') reload.push('groups')
      }
      await load(reload)
    }
    await w.refresh()
    success.value = value.message
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      try {
        impact.value = await api<Impact>('/admin/access-preview', 'POST', previewBody(value))
        previewError.value =
          'Access changed since the previous preview. Review the updated comparison and confirm again.'
      } catch (next) {
        previewError.value = errorMessage(next)
        impact.value = null
      }
    } else previewError.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}
function editUser(user: Person) {
  selectedUser.value = { ...user, role_ids: [...user.role_ids] }
  password.value = ''
  error.value = ''
  editor.value = 'user'
}
function cancelUser() {
  selectedUser.value = null
  password.value = ''
}
function deleteUser(user: Person) {
  void preview({
    resource: 'users',
    identifier: user.id,
    method: 'DELETE',
    payload: {},
    message: 'Account deleted.',
    done: () => {
      if (selectedUser.value?.id === user.id) cancelUser()
      groupForm.members = groupForm.members.filter((member) => member.user_id !== user.id)
    },
  })
}
function restoreDeleted(item: DeletedItem) {
  if (item.kind === 'users') {
    void preview({
      resource: 'users',
      identifier: item.identifier,
      method: 'RESTORE',
      payload: {},
      message: 'Account and its content restored. Previously paused labels still need review.',
    })
  } else {
    void perform(
      () => api(`/admin/trash/${item.kind}/${item.identifier}/restore`, 'POST', {}),
      'Content restored. Previously paused labels still need review.',
      ['trash'],
    )
  }
}
async function purgeDeleted(item: DeletedItem) {
  const content = item.kind === 'users' ? ' and the content deleted with this account' : ''
  if (await confirmAction(`Permanently purge “${item.name}”${content}? This cannot be undone.`))
    await perform(
      () =>
        api(`/admin/trash/${item.kind}/${item.identifier}/purge`, 'POST', {
          confirmation: item.identifier,
        }),
      'Permanently purged.',
      ['trash', 'users'],
    )
}
function editRole(role?: Role) {
  editor.value = 'role'
  error.value = ''
  Object.assign(roleForm, {
    id: role?.id ?? '',
    name: role?.name ?? '',
    applications:
      role?.permissions.filter((p) => p.kind === 'application').map((p) => p.permission) ?? [],
    destinationDenials: Object.fromEntries(
      (role?.permissions ?? []).flatMap((p) =>
        p.kind === 'destination_permissions'
          ? [[p.destination_id, [...(p.denied_permissions ?? [])]]]
          : [],
      ),
    ),
    locations: Object.fromEntries(
      (role?.permissions ?? []).flatMap((p) =>
        p.kind === 'location_permissions'
          ? [
              [
                p.location_id,
                {
                  permissions: exclusiveSubmissionPermissions([...p.permissions]),
                  denied_permissions: [...(p.denied_permissions ?? [])],
                },
              ],
            ]
          : [],
      ),
    ),
    destinations: Object.fromEntries([
      ...w.destinations.map((destination) => [destination.id, []]),
      ...(role?.permissions ?? []).flatMap((permission) =>
        permission.kind === 'application' || permission.kind === 'location_permissions'
          ? []
          : [
              [
                permission.destination_id,
                permission.kind === 'destination'
                  ? legacyPrinterPermissions(
                      permission.level,
                      w.destinations.find(
                        (destination) => destination.id === permission.destination_id,
                      )?.kind === 'group',
                    )
                  : exclusiveSubmissionPermissions([...permission.permissions]),
              ],
            ],
      ),
    ]),
  })
}
function selectedPreset(id: string, group: boolean): AccessLevel | 'custom' {
  if (roleForm.destinationDenials[id]?.length) return 'custom'
  const selected = JSON.stringify([...(roleForm.destinations[id] ?? [])].sort())
  return (
    accessLevels.find(
      (level) => JSON.stringify(printerPreset(level.value, group).sort()) === selected,
    )?.value ?? 'custom'
  )
}
function setPrinterRules(id: string, allowed: string[], denied: string[]) {
  roleForm.destinations[id] = allowed
  roleForm.destinationDenials[id] = denied
}
function setLocationRules(id: string, prefix: string, allowed: string[], denied: string[]) {
  const current = roleForm.locations[id] ?? { permissions: [], denied_permissions: [] }
  roleForm.locations[id] = {
    permissions: [
      ...current.permissions.filter((p) => !p.startsWith(prefix)),
      ...allowed.filter((p) => p.startsWith(prefix)),
    ],
    denied_permissions: [
      ...current.denied_permissions.filter((p) => !p.startsWith(prefix)),
      ...denied.filter((p) => p.startsWith(prefix)),
    ],
  }
}
function editGroup(group?: Group) {
  editor.value = 'group'
  error.value = ''
  Object.assign(groupForm, {
    id: group?.id ?? '',
    name: group?.name ?? '',
    members: group?.members.map((m) => ({ ...m })) ?? [],
  })
}
function toggleCodeGroup(id: string, event: Event) {
  if ((event.target as HTMLInputElement).checked) {
    codeForm.group_ids.push(id)
    codeForm.group_permissions[id] = {
      can_create: true,
      can_edit_others: false,
      can_delete_others: false,
    }
  } else {
    codeForm.group_ids = codeForm.group_ids.filter((identifier) => identifier !== id)
    delete codeForm.group_permissions[id]
  }
}
function setMemberPermissions(userId: string, rights: Membership) {
  const member = groupForm.members.find((item) => item.user_id === userId)
  if (member) Object.assign(member, rights)
}
async function revokeCode(id: string) {
  if (!(await confirmAction('Revoke this registration code?'))) return
  await perform(() => api('/admin/registration-codes/' + id, 'DELETE'), 'Code revoked.', ['codes'])
}
function toggleMember(userId: string, event: Event) {
  if ((event.target as HTMLInputElement).checked)
    groupForm.members.push({
      user_id: userId,
      can_create: false,
      can_edit_others: false,
      can_delete_others: false,
    })
  else groupForm.members = groupForm.members.filter((m) => m.user_id !== userId)
}
function saveUser() {
  if (!editorChanged.value) return
  const user = selectedUser.value
  if (user)
    void preview({
      resource: 'users',
      identifier: user.id,
      method: 'PUT',
      payload: {
        username: user.username,
        disabled: user.disabled,
        role_ids: [...user.role_ids],
        ...(password.value ? { password: password.value } : {}),
      },
      message: 'Account updated.',
      done: cancelUser,
    })
}
function createUser() {
  void preview({
    resource: 'users',
    method: 'POST',
    payload: { ...userForm, role_ids: [...userForm.role_ids] },
    message: 'Account created.',
    done: () => {
      userForm.username = ''
      userForm.password = ''
    },
  })
}
function saveRole() {
  if (!editorChanged.value) return
  const permissions = rolePermissions()
  void preview({
    resource: 'roles',
    identifier: roleForm.id || undefined,
    method: roleForm.id ? 'PUT' : 'POST',
    payload: { name: roleForm.name, permissions },
    message: 'Role saved.',
  })
}
function saveGroup() {
  if (!editorChanged.value) return
  void preview({
    resource: 'groups',
    identifier: groupForm.id || undefined,
    method: groupForm.id ? 'PUT' : 'POST',
    payload: { name: groupForm.name, members: groupForm.members.map((m) => ({ ...m })) },
    message: 'Content group saved.',
  })
}
function remove(resource: 'roles' | 'groups', identifier: string) {
  void preview({ resource, identifier, method: 'DELETE', payload: {}, message: 'Removed.' })
}
async function issueCode() {
  await perform(
    async () => {
      const result = await api<{ code: string }>('/admin/registration-codes', 'POST', codeForm)
      issuedCode.value = result.code
      codeForm.name = ''
      editor.value = null
    },
    'Registration code created. Copy it before leaving this page.',
    ['codes'],
  )
}
function describe(value: Effective | null) {
  if (!value) return ['Account does not exist']
  if (value.disabled) return ['Account disabled']
  if (value.is_admin)
    return ['Administrator — universal access to all existing and future resources']
  return [
    ...value.permissions.map((id) => permissions.value.find((p) => p.id === id)?.label ?? id),
    ...(value.destination_permissions
      ? Object.entries(value.destination_permissions).flatMap(([id, values]) =>
          values.map(
            (permission) => `${w.destinationName(id)}: ${printerPermissionLabel(permission)}`,
          ),
        )
      : Object.entries(value.destination_levels).map(
          ([id, level]) => `${w.destinationName(id)}: ${levelName(level)}`,
        )),
    ...Object.entries(value.cartridge_permissions ?? {}).flatMap(([id, values]) =>
      values.map(
        (permission) =>
          `${w.cartridgeName(id)}: ${permission.replace('cartridge.', '').replaceAll('_', ' ')}`,
      ),
    ),
    ...Object.entries(value.group_memberships).map(
      ([id, m]) =>
        `${groups.value.find((g) => g.id === id)?.name ?? groupForm.name ?? id}: view; ${(
          ['templates', 'images', 'fonts'] as const
        )
          .map((kind) => {
            const rights = kind === 'templates' ? m : m[kind]
            return `${kind}${rights?.can_create ? ', create' : ''}${rights?.can_edit_others ? ', edit others' : ''}${rights?.can_delete_others ? ', delete others' : ''}`
          })
          .join('; ')}`,
    ),
    'Own templates, images and fonts: edit and delete; own queued jobs: cancel',
  ]
}
function refreshAccess() {
  if (!auth.user?.is_admin) return
  // Preserve the local settings form while replacing shared, authorized records.
  void load(['users', 'roles', 'groups', 'codes', 'permissions', 'trash']).catch((issue) => {
    error.value = errorMessage(issue)
  })
}
onMounted(() => {
  window.addEventListener('access-changed', refreshAccess)
  void load()
    .catch((e) => {
      error.value = errorMessage(e)
    })
    .finally(() => {
      loading.value = false
    })
})
onUnmounted(() => window.removeEventListener('access-changed', refreshAccess))
</script>
<template>
  <div class="administration-layout">
    <MotionTrack
      tag="nav"
      class="administration-nav"
      :identity="section.id"
      selector="button.active"
      :aria-label="$t('administration.administrationSections')"
    >
      <div v-for="group in navigationGroups" :key="group.title" class="administration-nav-group">
        <h2>{{ group.title }}</h2>
        <button
          v-for="item in group.sections"
          :key="item.id"
          :class="{ active: section.id === item.id }"
          :aria-current="section.id === item.id ? 'page' : undefined"
          @click="navigate(item.id)"
        >
          {{ item.title }}
        </button>
      </div>
    </MotionTrack>
    <label class="administration-mobile-nav">
      <span class="sr-only">{{ $t('administration.administrationSection') }}</span>
      <select :value="section.id" @change="navigate(($event.target as HTMLSelectElement).value)">
        <optgroup v-for="group in navigationGroups" :key="group.title" :label="group.title">
          <option v-for="item in group.sections" :key="item.id" :value="item.id">
            {{ item.title }}
          </option>
        </optgroup>
      </select>
    </label>
    <MotionSurface
      :identity="section.id"
      :order="sections.findIndex((item) => item.id === section.id)"
      class="administration-content"
      :aria-busy="loading"
    >
      <p v-if="error && !editor" class="alert danger" role="alert">{{ error }}</p>
      <p v-if="success" class="alert success" role="status">{{ success }}</p>
      <p v-if="loading" class="empty" role="status">
        {{ $t('administration.loadingAdministration') }}
      </p>
      <template v-else>
        <section
          v-if="section.id === 'users'"
          class="admin-section"
          aria-labelledby="users-heading"
        >
          <header class="admin-section-heading">
            <h2 id="users-heading">
              {{ $t('common.users') }} <span>{{ users.length }}</span>
            </h2>
            <button class="primary" @click="newUser">
              {{ $t('administration.createAnAccount') }}
            </button>
          </header>
          <label class="admin-search"
            >{{ $t('common.searchUsers') }}<input v-model="search" type="search"
          /></label>
          <div class="table-scroll">
            <table class="admin-table">
              <thead>
                <tr>
                  <th>{{ $t('common.account') }}</th>
                  <th>{{ $t('administration.roles') }}</th>
                  <th>{{ $t('common.state') }}</th>
                  <th>
                    <span class="sr-only">{{ $t('common.actions') }}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="user in filteredUsers" :key="user.id">
                  <td>
                    <strong>{{ user.username }}</strong>
                  </td>
                  <td>{{ roleNames(user.role_ids) }}</td>
                  <td>
                    <span class="badge" :class="user.disabled ? 'cancelled' : 'printed'">{{
                      user.disabled ? $t('administration.disabled') : $t('common.active')
                    }}</span>
                  </td>
                  <td class="action-cell">
                    <div class="row wrap user-actions">
                      <RouterLink
                        v-if="!user.disabled"
                        class="button secondary"
                        :to="{ path: '/resource-access', query: { user: user.id } }"
                        :aria-label="`Permissions graph for ${user.username}`"
                        >{{ $t('common.permissionsGraph') }}</RouterLink
                      >
                      <button
                        class="secondary"
                        :disabled="busy"
                        :aria-label="`Edit ${user.username}`"
                        @click="editUser(user)"
                      >
                        {{ $t('common.edit') }}
                      </button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-if="!filteredUsers.length" class="empty">{{ $t('administration.noUsersFound') }}</p>
        </section>
        <section
          v-if="section.id === 'roles'"
          class="admin-section"
          aria-labelledby="roles-heading"
        >
          <header class="admin-section-heading">
            <h2 id="roles-heading">
              {{ $t('administration.roles') }} <span>{{ roles.length }}</span>
            </h2>
            <button class="primary" @click="editRole()">{{ $t('administration.newRole') }}</button>
          </header>
          <label class="admin-search"
            >{{ $t('common.searchRoles') }}<input v-model="search" type="search"
          /></label>
          <div v-for="role in filteredRoles" :key="role.id" class="admin-record">
            <div>
              <strong>{{ role.name }}</strong
              ><small>{{ roleSummary(role) }}</small>
            </div>
            <span v-if="role.protected" class="muted">{{ $t('administration.protected') }}</span
            ><button
              v-else
              class="secondary"
              :disabled="busy"
              :aria-label="`Edit role ${role.name}`"
              @click="editRole(role)"
            >
              {{ $t('common.edit') }}
            </button>
          </div>
          <p v-if="!filteredRoles.length" class="empty">{{ $t('administration.noRolesFound') }}</p>
        </section>
        <section
          v-if="section.id === 'groups'"
          class="admin-section"
          aria-labelledby="groups-heading"
        >
          <header class="admin-section-heading">
            <h2 id="groups-heading">
              {{ $t('administration.contentGroups') }} <span>{{ groups.length }}</span>
            </h2>
            <button class="primary" @click="editGroup()">
              {{ $t('administration.newContentGroup') }}
            </button>
          </header>
          <label v-if="groups.length" class="admin-search"
            >{{ $t('common.searchContentGroups') }}<input v-model="search" type="search"
          /></label>
          <div v-for="group in filteredGroups" :key="group.id" class="admin-record">
            <div>
              <strong>{{ group.name }}</strong
              ><small
                >{{ group.members.length }}
                {{ group.members.length === 1 ? $t('common.member') : 'members' }}</small
              >
            </div>
            <button
              class="secondary"
              :disabled="busy"
              :aria-label="`Edit group ${group.name}`"
              @click="editGroup(group)"
            >
              {{ $t('common.edit') }}
            </button>
          </div>
          <p v-if="!filteredGroups.length" class="empty">
            {{ groups.length ? 'No content groups found.' : 'No content groups.' }}
          </p>
        </section>
        <section
          v-if="section.id === 'codes'"
          class="admin-section"
          aria-labelledby="codes-heading"
        >
          <header class="admin-section-heading">
            <h2 id="codes-heading">{{ $t('administration.registrationCodes') }}</h2>
            <button class="primary" @click="newCode">
              {{ $t('administration.newRegistrationCode') }}
            </button>
          </header>
          <div v-if="issuedCode" class="alert success code-result">
            <label
              >{{ $t('administration.newRegistrationCode')
              }}<input
                :value="issuedCode"
                readonly
                @focus="($event.target as HTMLInputElement).select()"
            /></label>
            <p>{{ $t('common.shownOnce') }}</p>
            <button class="secondary" @click="issuedCode = ''">
              {{ $t('administration.dismissCode') }}
            </button>
          </div>
          <label v-if="codes.length" class="admin-search"
            >{{ $t('common.searchRegistrationCodes') }}<input v-model="search" type="search"
          /></label>
          <div v-for="code in filteredCodes" :key="code.id" class="admin-record">
            <div>
              <strong>{{ code.name }}</strong
              ><small
                >{{
                  code.revoked ? 'Revoked' : code.redeemed_at ? 'Redeemed' : $t('common.unused')
                }}
                · {{ code.expires_at ? 'Expires ' + date(code.expires_at) : 'No expiry' }}</small
              >
            </div>
            <button
              v-if="!code.revoked && !code.redeemed_at"
              class="secondary"
              :disabled="busy"
              :aria-label="`Revoke code ${code.name}`"
              @click="revokeCode(code.id)"
            >
              {{ $t('administration.revoke') }}
            </button>
          </div>
          <p v-if="!filteredCodes.length" class="empty">
            {{ codes.length ? 'No registration codes found.' : 'No registration codes.' }}
          </p>
        </section>
        <section
          v-show="section.id === 'settings'"
          class="admin-section settings-section"
          aria-labelledby="settings-heading"
        >
          <header class="admin-section-heading">
            <h2 id="settings-heading">{{ $t('navigation.account') }}</h2>
          </header>
          <form
            v-validate-form
            class="form-stack"
            @submit.prevent="
              perform(() => api('/admin/settings', 'PUT', settings), 'Account settings saved.', [
                'settings',
              ])
            "
          >
            <label class="checkbox"
              ><input v-model="settings.registration_code_required" type="checkbox" />{{
                $t('administration.requireAnAdministratorIssuedRegistrationCode')
              }}</label
            ><label class="checkbox"
              ><input v-model="settings.approval_notifications_enabled" type="checkbox" />{{
                $t('administration.notifyAdministratorsAboutPendingPrintRequests')
              }}</label
            ><label
              >{{ $t('administration.approvalNotificationDelaySeconds')
              }}<input
                v-model.number="settings.approval_notification_debounce_seconds"
                type="number"
                min="0"
                max="86400"
                required
              /><span class="help">{{
                $t('administration.combinePendingRequestsDuringAFixedIntervalBeginningWith')
              }}</span></label
            ><label
              >{{ $t('common.batchReviewEvidence')
              }}<select v-model="settings.batch_review_evidence">
                <option value="disabled">{{ $t('administration.disabled') }}</option>
                <option value="optional">{{ $t('administration.optional') }}</option>
                <option value="required">{{ $t('common.required') }}</option>
              </select></label
            ><button class="primary" :disabled="busy">
              {{ $t('administration.saveAccountSettings') }}
            </button>
          </form>
        </section>
        <NotificationEndpoints v-show="section.id === 'notifications'" />
        <section
          v-if="section.id === 'trash'"
          class="admin-section"
          aria-labelledby="trash-heading"
        >
          <header class="admin-section-heading">
            <h2 id="trash-heading">{{ $t('administration.deletedAccountsAndContent') }}</h2>
          </header>
          <p class="help">
            {{ $t('administration.restoreDeletedAccountsAndContentWithin30DaysRestoring') }}
          </p>
          <label v-if="trash.length" class="admin-search"
            >{{ $t('common.searchDeletedContent') }}<input v-model="search" type="search"
          /></label>
          <div
            v-for="item in filteredTrash"
            :key="`${item.kind}:${item.identifier}`"
            class="admin-record"
          >
            <div>
              <strong>{{ item.name }}</strong
              ><small
                >{{ item.kind }} {{ $t('common.purgeAfter') }} {{ date(item.purge_after) }}</small
              >
            </div>
            <div class="row wrap">
              <button
                class="secondary"
                :disabled="
                  busy ||
                  item.purge_after * 1000 <= Date.now() ||
                  (!!item.account_id && item.kind !== 'users')
                "
                :aria-label="`Restore ${item.name}`"
                @click="restoreDeleted(item)"
              >
                {{ $t('administration.restore') }}
              </button>
              <button
                class="danger"
                :disabled="busy"
                :aria-label="`Purge ${item.name} now`"
                @click="purgeDeleted(item)"
              >
                {{ $t('administration.purgeNow') }}
              </button>
            </div>
          </div>
          <p v-if="!filteredTrash.length" class="empty">
            {{
              trash.length
                ? 'No deleted content found.'
                : 'No deleted accounts or content awaiting purge.'
            }}
          </p>
        </section>
      </template>
    </MotionSurface>
  </div>
  <AdminDialog
    :open="!!editor"
    :title="editorTitle"
    :busy="busy"
    :wide="editor === 'group' || editor === 'code'"
    @close="closeEditor"
    ><p v-if="error" class="alert danger" role="alert">{{ error }}</p>
    <template v-if="editor === 'user'">
      <form v-validate-form v-if="selectedUser" class="form-stack" @submit.prevent="saveUser">
        <label
          >{{ $t('common.username')
          }}<input
            v-model="selectedUser.username"
            autocomplete="off"
            autocapitalize="none"
            :spellcheck="false"
            required
            minlength="3"
            maxlength="64"
            pattern="[A-Za-z0-9_.-]+"
        /></label>
        <label class="checkbox"
          ><input v-model="selectedUser.disabled" type="checkbox" />{{
            $t('administration.disableAccount')
          }}</label
        >
        <fieldset class="choice-grid">
          <legend>{{ $t('administration.assignedRoles') }}</legend>
          <label v-for="role in roles" :key="role.id" class="checkbox"
            ><input
              v-model="selectedUser.role_ids"
              type="checkbox"
              :value="role.id"
              :aria-label="role.name"
              :aria-describedby="`role-summary-${role.id}`"
            /><span
              >{{ role.name
              }}<small class="role-summary" :id="`role-summary-${role.id}`">{{
                roleSummary(role)
              }}</small></span
            ></label
          >
        </fieldset>
        <label
          >{{ $t('administration.newPasswordOptional')
          }}<input v-model="password" type="password" minlength="12" autocomplete="new-password"
        /></label>
        <p class="help">
          {{ $t('administration.disablingAnAccountEndsItsSessionsQueuedWorkAffected') }}
        </p>
        <div class="admin-actions">
          <button
            type="button"
            class="danger-text secondary"
            :disabled="busy"
            :aria-label="`Delete account ${selectedUser.username}`"
            @click="deleteUser(selectedUser)"
          >
            {{ $t('administration.deleteAccount') }}</button
          ><button class="primary" :disabled="busy || !editorChanged">
            {{ $t('administration.reviewAccountChanges') }}</button
          ><button type="button" @click="closeEditor">{{ $t('common.cancel') }}</button>
        </div>
      </form> </template
    ><template v-if="editor === 'new-user'"
      ><form v-validate-form class="form-stack" @submit.prevent="createUser">
        <div class="field-row">
          <label
            >{{ $t('administration.newUsername')
            }}<input
              v-model="userForm.username"
              required
              minlength="3"
              maxlength="64"
              pattern="[A-Za-z0-9_.-]+"
              autocomplete="off" /></label
          ><label
            >{{ $t('administration.initialPassword')
            }}<input
              v-model="userForm.password"
              type="password"
              required
              minlength="12"
              autocomplete="new-password"
          /></label>
        </div>
        <fieldset class="choice-grid">
          <legend>{{ $t('administration.initialRoles') }}</legend>
          <label v-for="role in roles" :key="role.id" class="checkbox"
            ><input
              v-model="userForm.role_ids"
              type="checkbox"
              :value="role.id"
              :aria-label="role.name"
              :aria-describedby="`role-summary-${role.id}`"
            /><span
              >{{ role.name
              }}<small class="role-summary" :id="`role-summary-${role.id}`">{{
                roleSummary(role)
              }}</small></span
            ></label
          >
        </fieldset>
        <div class="admin-actions">
          <button type="button" class="secondary" @click="closeEditor">
            {{ $t('common.cancel') }}</button
          ><button class="primary" :disabled="busy">
            {{ $t('administration.reviewNewAccount') }}
          </button>
        </div>
      </form></template
    ><template v-if="editor === 'role'">
      <form v-validate-form class="form-stack" @submit.prevent="saveRole">
        <label
          >{{ $t('administration.roleName')
          }}<input v-model="roleForm.name" required maxlength="100"
        /></label>
        <fieldset v-for="category in permissionGroups" :key="category.title" class="choice-grid">
          <legend>{{ category.title }}</legend>
          <label v-for="permission in category.options" :key="permission.id" class="checkbox"
            ><input v-model="roleForm.applications" type="checkbox" :value="permission.id" />{{
              permission.label
            }}</label
          >
        </fieldset>
        <fieldset>
          <legend>{{ $t('common.printDestinations') }}</legend>
          <AnimatedDetails v-for="destination in w.destinations" :key="destination.id">
            <template #summary
              >{{ destination.name }} · {{ (roleForm.destinations[destination.id] ?? []).length }}
              {{ $t('common.allowed') }}
              {{ (roleForm.destinationDenials[destination.id] ?? []).length }}
              {{ $t('common.denied') }}</template
            >
            <div class="form-stack">
              <label
                >{{ $t('administration.preset')
                }}<select
                  :aria-label="`Access to ${destination.name}`"
                  :value="selectedPreset(destination.id, destination.kind === 'group')"
                  @change="
                    setPrinterRules(
                      destination.id,
                      printerPreset(
                        ($event.target as HTMLSelectElement).value as AccessLevel,
                        destination.kind === 'group',
                      ),
                      [],
                    )
                  "
                >
                  <option value="custom" disabled>{{ $t('common.custom') }}</option>
                  <option v-for="level in accessLevels" :key="level.value" :value="level.value">
                    {{ level.label }}
                  </option>
                </select></label
              >
              <div role="group" :aria-label="`${destination.name} permissions`">
                <PermissionRules
                  :options="permissionOptions(destination.kind === 'group')"
                  :allowed="roleForm.destinations[destination.id] ?? []"
                  :denied="roleForm.destinationDenials[destination.id] ?? []"
                  @change="(allowed, denied) => setPrinterRules(destination.id, allowed, denied)"
                />
              </div>
            </div>
          </AnimatedDetails>
        </fieldset>
        <fieldset class="form-stack">
          <legend>{{ $t('common.locations') }}</legend>
          <AnimatedDetails v-for="location in accessCatalog?.locations" :key="location.id">
            <template #summary>{{ location.name }}</template>
            <fieldset
              v-for="kind in ['printer', 'cartridge'] as const"
              :key="kind"
              class="form-stack"
            >
              <legend>
                {{ kind === 'printer' ? 'Printer permissions' : 'Cartridge permissions' }}
              </legend>
              <PermissionRules
                :options="
                  (accessCatalog?.permissions[kind] ?? []).map((id) => ({
                    id,
                    label: permissionLabel(id),
                  }))
                "
                :allowed="roleForm.locations[location.id]?.permissions ?? []"
                :denied="roleForm.locations[location.id]?.denied_permissions ?? []"
                @change="
                  (allowed, denied) => setLocationRules(location.id, `${kind}.`, allowed, denied)
                "
              />
            </fieldset>
          </AnimatedDetails>
        </fieldset>

        <div class="admin-actions">
          <button
            v-if="roleForm.id"
            type="button"
            class="danger-text secondary"
            :disabled="busy"
            @click="remove('roles', roleForm.id)"
          >
            {{ $t('administration.deleteRole') }}</button
          ><button class="primary" :disabled="busy || !editorChanged">
            {{ $t('administration.reviewRoleChanges') }}</button
          ><button type="button" class="secondary" @click="closeEditor">
            {{ $t('common.cancel') }}
          </button>
        </div>
      </form> </template
    ><template v-if="editor === 'group'"
      ><form v-validate-form class="form-stack" @submit.prevent="saveGroup">
        <label
          >{{ $t('common.groupName') }}<input v-model="groupForm.name" required maxlength="100"
        /></label>
        <fieldset>
          <legend>{{ $t('administration.membershipAndCollaboration') }}</legend>
          <div class="member-matrix">
            <div v-for="user in users" :key="user.id" class="member-row">
              <label class="checkbox member-name"
                ><input
                  type="checkbox"
                  :checked="groupForm.members.some((m) => m.user_id === user.id)"
                  @change="toggleMember(user.id, $event)"
                />{{ user.username }}</label
              >
              <Transition name="panel-expand">
                <GroupPermissionsFields
                  v-if="groupForm.members.find((m) => m.user_id === user.id)"
                  :model-value="groupForm.members.find((m) => m.user_id === user.id)!"
                  :subject="user.username"
                  @update:model-value="setMemberPermissions(user.id, $event)"
                />
              </Transition>
            </div>
          </div>
        </fieldset>
        <p class="help">
          {{ $t('administration.membersCanViewThisGroupSTemplatesImagesAnd') }}
        </p>
        <div class="admin-actions">
          <button
            v-if="groupForm.id"
            type="button"
            class="danger-text secondary"
            :disabled="busy"
            @click="remove('groups', groupForm.id)"
          >
            {{ $t('administration.deleteGroup') }}</button
          ><button type="button" class="secondary" @click="closeEditor">
            {{ $t('common.cancel') }}</button
          ><button class="primary" :disabled="busy || !editorChanged">
            {{ $t('administration.reviewGroupChanges') }}
          </button>
        </div>
      </form></template
    ><template v-if="editor === 'code'">
      <form v-validate-form class="form-stack" @submit.prevent="issueCode">
        <div class="field-row">
          <label
            >{{ $t('administration.codeLabel')
            }}<input v-model="codeForm.name" required maxlength="100" /></label
          ><label
            >{{ $t('common.validForDays')
            }}<input
              v-model.number="codeForm.expires_in_days"
              type="number"
              min="1"
              max="365"
              required
          /></label>
        </div>
        <fieldset class="choice-grid">
          <legend>{{ $t('administration.initialRoles') }}</legend>
          <label v-for="role in roles.filter((r) => !r.protected)" :key="role.id" class="checkbox"
            ><input
              v-model="codeForm.role_ids"
              type="checkbox"
              :value="role.id"
              :aria-label="role.name"
              :aria-describedby="`role-summary-${role.id}`"
            /><span
              >{{ role.name
              }}<small class="role-summary" :id="`role-summary-${role.id}`">{{
                roleSummary(role)
              }}</small></span
            ></label
          >
        </fieldset>
        <fieldset v-if="groups.length">
          <legend>{{ $t('administration.joinContentGroups') }}</legend>
          <div class="member-matrix">
            <div v-for="group in groups" :key="group.id" class="member-row">
              <label class="checkbox member-name"
                ><input
                  type="checkbox"
                  :checked="codeForm.group_ids.includes(group.id)"
                  @change="toggleCodeGroup(group.id, $event)"
                />{{ group.name }}</label
              >
              <Transition name="panel-expand">
                <GroupPermissionsFields
                  v-if="codeForm.group_permissions[group.id]"
                  :model-value="codeForm.group_permissions[group.id]!"
                  :subject="group.name"
                  invitation
                  @update:model-value="codeForm.group_permissions[group.id] = $event"
                />
              </Transition>
            </div>
          </div>
        </fieldset>
        <div class="admin-actions">
          <button type="button" class="secondary" @click="closeEditor">
            {{ $t('common.cancel') }}</button
          ><button class="primary" :disabled="busy">
            {{ $t('administration.createRegistrationCode') }}
          </button>
        </div>
      </form>
    </template></AdminDialog
  >
  <Teleport to="body"
    ><dialog
      ref="previewDialog"
      class="access-preview-dialog"
      aria-labelledby="access-preview-title"
      @cancel.prevent="cancelPreview"
    >
      <h2 id="access-preview-title">
        {{ deletingAccount ? $t('administration.deleteAccount') : 'Review effective access' }}
      </h2>
      <template v-if="deletingAccount">
        <p>
          {{ $t('administration.deleteThisAccountEndItsSessionsAndRemoveAll') }}
        </p>
        <p v-if="change?.identifier === auth.user?.id" class="alert warning">
          {{ $t('common.youAreDeletingYourOwnAccountAndWillBe') }}
        </p>
      </template>
      <p v-if="previewError" class="alert warning" role="alert">{{ previewError }}</p>
      <p v-if="impact?.owner_loss_warning" class="alert warning">
        {{ $t('common.thisChangeGrantsApproveUseOnCartridgesTheirOwners') }}
      </p>
      <div v-if="impact" class="table-scroll">
        <table v-if="changedUsers.length">
          <thead>
            <tr>
              <th>{{ $t('common.user') }}</th>
              <th>{{ $t('administration.before') }}</th>
              <th>{{ $t('administration.after') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in changedUsers" :key="item.id">
              <td>
                <strong>{{
                  item.before && item.after && item.before.username !== item.after.username
                    ? `${item.before.username} → ${item.after.username}`
                    : item.username
                }}</strong
                ><small>{{ item.changed ? 'Changed' : 'Unchanged' }}</small>
              </td>
              <td>
                <ul>
                  <li v-for="line in describe(item.before)" :key="line">{{ line }}</li>
                </ul>
              </td>
              <td>
                <ul>
                  <li v-for="line in describe(item.after)" :key="line">{{ line }}</li>
                </ul>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-if="!changedUsers.length" class="empty compact">
          {{ $t('administration.noEffectiveAccessChanges') }}
        </p>
        <AnimatedDetails v-if="unchangedUsers.length" class="unchanged-access">
          <template #summary>
            {{ unchangedUsers.length }} {{ $t('common.unchanged') }}
            {{ unchangedUsers.length === 1 ? 'account' : 'accounts' }}
          </template>
          <ul>
            <li v-for="item in unchangedUsers" :key="item.id">{{ item.username }}</li>
          </ul>
        </AnimatedDetails>
      </div>
      <div class="row wrap">
        <button class="secondary" :disabled="busy" @click="cancelPreview">
          {{ $t('common.cancel') }}</button
        ><button class="primary" :disabled="busy || !impact" @click="applyChange">
          {{
            deletingAccount
              ? $t('administration.deleteAccount')
              : $t('resourceAccess.confirmAccessChanges')
          }}
        </button>
      </div>
    </dialog></Teleport
  >
</template>
<style scoped>
.administration-layout {
  display: grid;
  grid-template-columns: 184px minmax(0, 1fr);
  gap: 32px;
  align-items: start;
}
.administration-nav {
  display: grid;
  gap: 24px;
  position: sticky;
  top: 24px;
}
.administration-nav-group {
  display: grid;
  gap: 4px;
}
.administration-nav h2 {
  margin: 0 12px 8px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
}
.administration-nav button {
  text-align: left;
  justify-content: flex-start;
  background: transparent;
  border-color: transparent;
  color: var(--text-secondary);
  font-weight: 500;
  padding: 12px;
}
.administration-nav button.active {
  background: var(--surface-secondary);
  color: var(--ink);
}
.administration-content {
  min-width: 0;
}
.administration-mobile-nav {
  display: none;
}
.admin-section,
:deep(.notification-endpoints) {
  min-width: 0;
}
.admin-section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 24px;
  flex-wrap: wrap;
}
h2 {
  font-size: 20px;
  margin: 0;
}
h2 span {
  color: var(--muted);
  font-size: 14px;
  font-weight: 400;
  margin-left: 8px;
}
.admin-search {
  display: grid;
  gap: 8px;
  max-width: 360px;
  margin-bottom: 24px;
}
.admin-record {
  display: flex;
  align-items: center;
  gap: 20px;
  justify-content: space-between;
  padding: 16px 0;
  border-bottom: 1px solid var(--line);
}
.admin-record > div {
  min-width: 0;
}
.admin-record strong,
.admin-table strong {
  overflow-wrap: anywhere;
}
.admin-record small {
  display: block;
  color: var(--muted);
  margin-top: 4px;
  overflow-wrap: anywhere;
}
.admin-record button {
  flex-shrink: 0;
}
.admin-table {
  min-width: 440px;
}
.admin-table td {
  white-space: normal;
  overflow-wrap: anywhere;
  padding: 10px 12px;
}
.admin-table .action-cell {
  text-align: right;
  white-space: nowrap;
  overflow-wrap: normal;
}
.user-actions {
  justify-content: flex-end;
}
.settings-section form {
  max-width: 600px;
}
.choice-grid,
.destination-grants {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(220px, 100%), 1fr));
  gap: 12px;
}
.role-summary {
  display: block;
  color: var(--muted);
  font-size: 12px;
}
.code-result {
  display: block;
}
.member-matrix {
  margin-top: 8px;
}
.member-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 12px;
  align-items: center;
}
.member-row {
  padding: 12px 0;
  border-top: 1px solid var(--line);
}
.member-name {
  overflow-wrap: anywhere;
  min-width: 0;
}
.unassigned {
  color: var(--muted);
  text-align: center;
}
.access-preview-dialog {
  width: min(940px, calc(100% - 32px));
  max-height: calc(100dvh - 32px);
  padding: 24px;
  background: var(--surface-dense);
  color: var(--ink);
  border: 1px solid var(--line-strong);
  border-radius: 12px;
  box-shadow: 0 24px 64px var(--shadow);
}
.access-preview-dialog::backdrop {
  background: #030712b3;
}
.access-preview-dialog td {
  white-space: normal;
  vertical-align: top;
  overflow-wrap: anywhere;
}
.access-preview-dialog td:first-child {
  min-width: 100px;
}
.access-preview-dialog li {
  margin-bottom: 8px;
}
.access-preview-dialog .row {
  justify-content: flex-end;
  margin-top: 24px;
}
.unchanged-access {
  margin: 16px 0;
  color: var(--muted);
}
.unchanged-access :deep(summary) {
  cursor: pointer;
}
@media (max-width: 1000px) {
  .administration-layout {
    grid-template-columns: 160px minmax(0, 1fr);
    gap: 20px;
  }
}
@media (max-width: 700px) {
  .administration-layout {
    grid-template-columns: minmax(0, 1fr);
    gap: 24px;
  }
  .administration-nav {
    display: none;
  }
  .administration-mobile-nav {
    display: block;
  }
  .admin-table th,
  .admin-table td {
    padding: 12px 8px;
  }
}
@media (max-width: 600px) {
  .member-row {
    grid-template-columns: minmax(0, 1fr);
    gap: 8px;
  }
  .unassigned {
    display: none;
  }
  .admin-record {
    gap: 12px;
  }
  .access-preview-dialog {
    padding: 16px;
  }
}
</style>
