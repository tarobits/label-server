<script setup lang="ts">
import { vValidateForm } from '../formValidation'
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { api, ApiError, errorMessage } from '../api'
import { useAuthStore, accessLevels, type AccessLevel, type Membership } from '../auth'
import { useWorkspaceStore, date } from '../workspace'
import PropertySection from '../components/PropertySection.vue'
import NotificationEndpoints from '../components/NotificationEndpoints.vue'
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
  is_admin: boolean
  disabled: boolean
  permissions: string[]
  destination_levels: Record<string, AccessLevel>
  group_memberships: Record<string, Membership>
}
interface Impact {
  confirmation_token: string
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
const w = useWorkspaceStore()
const auth = useAuthStore()
const administration = useAdministrationStore()
const { users, roles, groups, codes, permissions, trash } = storeToRefs(administration)
const busy = ref(false),
  error = ref(''),
  success = ref(''),
  issuedCode = ref('')
const settings = reactive({
  registration_code_required: true,
  approval_notification_debounce_seconds: 60,
  approval_notifications_enabled: true,
})
const roleForm = reactive({
  id: '',
  name: '',
  applications: [] as string[],
  levels: {} as Record<string, AccessLevel>,
})
const groupForm = reactive({ id: '', name: '', members: [] as Member[] })
const codeForm = reactive({
  name: '',
  expires_in_days: 7,
  role_ids: ['member'],
  group_ids: [] as string[],
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
    value.done?.()
    previewDialog.value?.close()
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
function editRole(role?: Role) {
  Object.assign(roleForm, {
    id: role?.id ?? '',
    name: role?.name ?? '',
    applications:
      role?.permissions.filter((p) => p.kind === 'application').map((p) => p.permission) ?? [],
    levels: Object.fromEntries(
      role?.permissions
        .filter((p) => p.kind === 'destination')
        .map((p) => [p.destination_id, p.level]) ?? [],
    ),
  })
}
function editGroup(group?: Group) {
  Object.assign(groupForm, {
    id: group?.id ?? '',
    name: group?.name ?? '',
    members: group?.members.map((m) => ({ ...m })) ?? [],
  })
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
  const user = selectedUser.value
  if (user)
    void preview({
      resource: 'users',
      identifier: user.id,
      method: 'PUT',
      payload: {
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
  const permissions: Permission[] = [
    ...roleForm.applications.map((permission) => ({ kind: 'application' as const, permission })),
    ...Object.entries(roleForm.levels).map(([destination_id, level]) => ({
      kind: 'destination' as const,
      destination_id,
      level,
    })),
  ]
  void preview({
    resource: 'roles',
    identifier: roleForm.id || undefined,
    method: roleForm.id ? 'PUT' : 'POST',
    payload: { name: roleForm.name, permissions },
    message: 'Role saved.',
    done: () => editRole(),
  })
}
function saveGroup() {
  void preview({
    resource: 'groups',
    identifier: groupForm.id || undefined,
    method: groupForm.id ? 'PUT' : 'POST',
    payload: { name: groupForm.name, members: groupForm.members.map((m) => ({ ...m })) },
    message: 'Template group saved.',
    done: () => editGroup(),
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
    ...Object.entries(value.destination_levels).map(
      ([id, level]) => `${w.destinationName(id)}: ${levelName(level)}`,
    ),
    ...Object.entries(value.group_memberships).map(
      ([id, m]) =>
        `${groups.value.find((g) => g.id === id)?.name ?? groupForm.name ?? id}: view${m.can_create ? ', create' : ''}${m.can_edit_others ? ', edit others' : ''}${m.can_delete_others ? ', delete others' : ''}`,
    ),
    'Own templates: edit and delete; own queued jobs: cancel',
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
  void load().catch((e) => {
    error.value = errorMessage(e)
  })
})
onUnmounted(() => window.removeEventListener('access-changed', refreshAccess))
</script>
<template>
  <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
  <p v-if="success" class="alert success" role="status">{{ success }}</p>
  <div class="panel">
    <p>Roles grant printer and application access. Template groups control sharing and editing.</p>
  </div>
  <section class="panel">
    <PropertySection title="Users" initially-open>
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Account</th>
              <th>Roles</th>
              <th>State</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="user in users" :key="user.id">
              <td>{{ user.username }}</td>
              <td>
                {{
                  user.role_ids
                    .map((id) => roles.find((r) => r.id === id)?.name ?? id)
                    .join(', ') || 'No roles'
                }}
              </td>
              <td>{{ user.disabled ? 'Disabled' : 'Active' }}</td>
              <td>
                <div class="row record-actions">
                  <button class="small secondary" @click="editUser(user)">
                    Edit {{ user.username }}
                  </button>
                  <button class="small danger-text" :disabled="busy" @click="deleteUser(user)">
                    Delete account {{ user.username }}
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <form
        v-validate-form
        v-if="selectedUser"
        class="form-stack admin-form"
        @submit.prevent="saveUser"
      >
        <h3>Edit {{ selectedUser.username }}</h3>
        <label class="checkbox"
          ><input v-model="selectedUser.disabled" type="checkbox" />Disable account</label
        >
        <fieldset class="choice-grid">
          <legend>Assigned roles</legend>
          <label v-for="role in roles" :key="role.id" class="checkbox"
            ><input v-model="selectedUser.role_ids" type="checkbox" :value="role.id" />{{
              role.name
            }}</label
          >
        </fieldset>
        <label
          >New password (optional)<input
            v-model="password"
            type="password"
            minlength="12"
            autocomplete="new-password"
        /></label>
        <p class="help">
          Disabling an account ends its sessions. Queued work affected by lost access waits for an
          administrator.
        </p>
        <div class="row">
          <button class="primary" :disabled="busy">Review account changes</button
          ><button type="button" @click="cancelUser">Cancel</button>
        </div>
      </form>
      <PropertySection title="Create an account"
        ><form v-validate-form class="form-stack" @submit.prevent="createUser">
          <div class="field-row">
            <label
              >New username<input
                v-model="userForm.username"
                required
                minlength="3"
                maxlength="64"
                pattern="[A-Za-z0-9_.-]+"
                autocomplete="off" /></label
            ><label
              >Initial password<input
                v-model="userForm.password"
                type="password"
                required
                minlength="12"
                autocomplete="new-password"
            /></label>
          </div>
          <fieldset class="choice-grid">
            <legend>Initial roles</legend>
            <label v-for="role in roles" :key="role.id" class="checkbox"
              ><input v-model="userForm.role_ids" type="checkbox" :value="role.id" />{{
                role.name
              }}</label
            >
          </fieldset>
          <button class="primary" :disabled="busy">Review new account</button>
        </form></PropertySection
      >
    </PropertySection>
  </section>
  <section class="panel">
    <PropertySection title="Roles">
      <div v-for="role in roles" :key="role.id" class="list-row">
        <div>
          <strong>{{ role.name }}</strong
          ><small>{{
            role.protected
              ? 'Universal access · protected role'
              : `${role.permissions.length} permission objects`
          }}</small>
        </div>
        <div v-if="!role.protected" class="row record-actions">
          <button class="small" @click="editRole(role)">Edit role {{ role.name }}</button
          ><button class="small danger-text" :disabled="busy" @click="remove('roles', role.id)">
            Delete role {{ role.name }}
          </button>
        </div>
      </div>
      <form v-validate-form class="form-stack admin-form" @submit.prevent="saveRole">
        <h3>{{ roleForm.id ? 'Edit role' : 'New role' }}</h3>
        <label>Role name<input v-model="roleForm.name" required maxlength="100" /></label>
        <fieldset class="choice-grid">
          <legend>Application permissions</legend>
          <label v-for="permission in permissions" :key="permission.id" class="checkbox"
            ><input v-model="roleForm.applications" type="checkbox" :value="permission.id" />{{
              permission.label
            }}</label
          >
        </fieldset>
        <fieldset>
          <legend>Print destinations</legend>
          <div class="destination-grants">
            <label v-for="destination in w.destinations" :key="destination.id"
              >{{ destination.name }}
              <span class="help">{{
                destination.kind === 'group' ? 'Distribution group' : 'Printer'
              }}</span
              ><select
                :aria-label="`Access to ${destination.name}`"
                :value="roleForm.levels[destination.id] ?? 'none'"
                @change="
                  roleForm.levels[destination.id] = ($event.target as HTMLSelectElement)
                    .value as AccessLevel
                "
              >
                <option v-for="level in accessLevels" :key="level.value" :value="level.value">
                  {{ level.label }}
                </option>
              </select></label
            >
          </div>
        </fieldset>
        <p class="help">
          Highest applicable access wins. Group access permits use through that group only. Full
          group access does not configure its physical printers.
        </p>
        <div class="row">
          <button class="primary" :disabled="busy">Review role changes</button
          ><button v-if="roleForm.id" type="button" @click="editRole()">Cancel</button>
        </div>
      </form>
    </PropertySection>
  </section>
  <section class="panel">
    <PropertySection title="Template groups">
      <div v-for="group in groups" :key="group.id" class="list-row">
        <div>
          <strong>{{ group.name }}</strong
          ><small>{{ group.members.length }} members</small>
        </div>
        <div class="row record-actions">
          <button class="small" @click="editGroup(group)">Edit group {{ group.name }}</button
          ><button class="small danger-text" :disabled="busy" @click="remove('groups', group.id)">
            Delete group {{ group.name }}
          </button>
        </div>
      </div>
      <form v-validate-form class="form-stack admin-form" @submit.prevent="saveGroup">
        <h3>{{ groupForm.id ? 'Edit template group' : 'New template group' }}</h3>
        <label>Group name<input v-model="groupForm.name" required maxlength="100" /></label>
        <fieldset>
          <legend>Membership and collaboration</legend>
          <div v-for="user in users" :key="user.id" class="member-permissions">
            <label class="checkbox"
              ><input
                type="checkbox"
                :checked="groupForm.members.some((m) => m.user_id === user.id)"
                @change="toggleMember(user.id, $event)"
              />{{ user.username }}</label
            ><template
              v-for="member in groupForm.members.filter((m) => m.user_id === user.id)"
              :key="member.user_id"
              ><div class="member-options">
                <label class="checkbox"
                  ><input
                    v-model="member.can_create"
                    type="checkbox"
                    :aria-label="`Allow ${user.username} to create group templates`"
                  />Create templates</label
                ><label class="checkbox"
                  ><input
                    v-model="member.can_edit_others"
                    type="checkbox"
                    :aria-label="`Allow ${user.username} to edit others’ templates`"
                  />Edit others’ templates</label
                ><label class="checkbox"
                  ><input
                    v-model="member.can_delete_others"
                    type="checkbox"
                    :aria-label="`Allow ${user.username} to delete others’ templates`"
                  />Delete others’ templates</label
                >
              </div></template
            >
          </div>
        </fieldset>
        <p class="help">
          Members can view this group’s templates. Each collaboration permission is independent.
          Owners always retain editing and deletion rights to their own templates.
        </p>
        <div class="row">
          <button class="primary" :disabled="busy">Review group changes</button
          ><button v-if="groupForm.id" type="button" @click="editGroup()">Cancel</button>
        </div>
      </form>
    </PropertySection>
  </section>
  <section class="panel">
    <PropertySection title="Registration codes"
      ><div v-if="issuedCode" class="alert success code-result">
        <label
          >New registration code<input
            :value="issuedCode"
            readonly
            @focus="($event.target as HTMLInputElement).select()"
        /></label>
        <p>Shown once.</p>
        <button class="secondary" @click="issuedCode = ''">Dismiss code</button>
      </div>
      <form v-validate-form class="form-stack" @submit.prevent="issueCode">
        <div class="field-row">
          <label>Code label<input v-model="codeForm.name" required maxlength="100" /></label
          ><label
            >Valid for (days)<input
              v-model.number="codeForm.expires_in_days"
              type="number"
              min="1"
              max="365"
              required
          /></label>
        </div>
        <fieldset class="choice-grid">
          <legend>Initial roles</legend>
          <label v-for="role in roles.filter((r) => !r.protected)" :key="role.id" class="checkbox"
            ><input v-model="codeForm.role_ids" type="checkbox" :value="role.id" />{{
              role.name
            }}</label
          >
        </fieldset>
        <fieldset class="choice-grid">
          <legend>Join template groups</legend>
          <label v-for="group in groups" :key="group.id" class="checkbox"
            ><input v-model="codeForm.group_ids" type="checkbox" :value="group.id" />{{
              group.name
            }}</label
          >
        </fieldset>
        <button class="primary" :disabled="busy">Create registration code</button>
      </form>
      <div v-for="code in codes" :key="code.id" class="list-row">
        <div>
          <strong>{{ code.name }}</strong
          ><small
            >{{ code.revoked ? 'Revoked' : code.redeemed_at ? 'Redeemed' : 'Unused' }} ·
            {{ code.expires_at ? 'Expires ' + date(code.expires_at) : 'No expiry' }}</small
          >
        </div>
        <button
          v-if="!code.revoked && !code.redeemed_at"
          class="small danger-text"
          :disabled="busy"
          @click="
            perform(() => api('/admin/registration-codes/' + code.id, 'DELETE'), 'Code revoked.', [
              'codes',
            ])
          "
        >
          Revoke code
        </button>
      </div>
    </PropertySection>
  </section>
  <section class="panel">
    <PropertySection title="Account settings"
      ><form
        v-validate-form
        class="form-stack"
        @submit.prevent="
          perform(() => api('/admin/settings', 'PUT', settings), 'Account settings saved.', [
            'settings',
          ])
        "
      >
        <label class="checkbox"
          ><input v-model="settings.registration_code_required" type="checkbox" />Require an
          administrator-issued registration code</label
        ><label class="checkbox"
          ><input v-model="settings.approval_notifications_enabled" type="checkbox" />Notify
          administrators about pending print requests</label
        ><label
          >Approval notification delay (seconds)<input
            v-model.number="settings.approval_notification_debounce_seconds"
            type="number"
            min="0"
            max="86400"
            required
          /><span class="help"
            >Combine pending requests during a fixed interval beginning with the first
            request.</span
          ></label
        ><button class="primary" :disabled="busy">Save account settings</button>
      </form></PropertySection
    >
  </section>
  <NotificationEndpoints v-if="auth.user?.is_admin" />
  <section class="panel">
    <PropertySection title="Deleted accounts and content">
      <p class="help">
        Deleted accounts and content are unavailable immediately. Administrators can restore them
        for 30 days. After that, their retained data is permanently purged. Restore an account to
        recover the content deleted with it.
      </p>
      <p v-if="!trash.length" class="empty">No deleted accounts or content awaiting purge.</p>
      <div v-for="item in trash" :key="`${item.kind}:${item.identifier}`" class="list-row">
        <div>
          <strong>{{ item.name }}</strong>
          <small>{{ item.kind }} · Purge after {{ date(item.purge_after) }}</small>
        </div>
        <button
          class="small secondary"
          :disabled="
            busy ||
            item.purge_after * 1000 <= Date.now() ||
            (!!item.account_id && item.kind !== 'users')
          "
          @click="restoreDeleted(item)"
        >
          Restore {{ item.name }}
        </button>
      </div>
    </PropertySection>
  </section>
  <Teleport to="body"
    ><dialog
      ref="previewDialog"
      class="access-preview-dialog"
      aria-labelledby="access-preview-title"
      @cancel.prevent="cancelPreview"
    >
      <h2 id="access-preview-title">
        {{ deletingAccount ? 'Delete account' : 'Review effective access' }}
      </h2>
      <template v-if="deletingAccount">
        <p>
          Delete this account, end its sessions, and remove all its templates, images and fonts from
          use, including shared content. Administrators can restore the account and its content for
          30 days before permanent purging. Other templates using its assets will show missing-asset
          placeholders. Affected queued work is paused. Print history is retained.
        </p>
        <p v-if="change?.identifier === auth.user?.id" class="alert warning">
          You are deleting your own account and will be signed out.
        </p>
      </template>
      <p v-if="previewError" class="alert warning" role="alert">{{ previewError }}</p>
      <div v-if="impact" class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>User</th>
              <th>Before</th>
              <th>After</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in impact.affected_users" :key="item.id">
              <td>
                <strong>{{ item.username }}</strong
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
        <p v-if="!impact.affected_users.length">No existing accounts are affected.</p>
      </div>
      <div class="row wrap">
        <button class="secondary" :disabled="busy" @click="cancelPreview">Cancel</button
        ><button class="primary" :disabled="busy || !impact" @click="applyChange">
          {{ deletingAccount ? 'Delete account' : 'Confirm access changes' }}
        </button>
      </div>
    </dialog></Teleport
  >
</template>
<style scoped>
.admin-form {
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid var(--line);
}
.choice-grid,
.destination-grants {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}
.code-result {
  display: block;
}
.list-row {
  gap: 16px;
  flex-wrap: wrap;
}
.list-row small {
  overflow-wrap: anywhere;
}
.record-actions {
  justify-content: flex-end;
  margin-left: auto;
  flex-wrap: wrap;
}
.member-permissions {
  padding: 12px 0;
  border-bottom: 1px solid var(--line);
}
.member-options {
  display: grid;
  gap: 10px;
  margin: 12px 0 0 30px;
}
.access-preview-dialog {
  width: min(1100px, calc(100vw - 32px));
  max-height: calc(100dvh - 48px);
  padding: 24px;
  background: var(--surface);
  color: var(--ink);
  border: 1px solid var(--line);
  border-radius: 12px;
}
.access-preview-dialog::backdrop {
  background: #030712b3;
  backdrop-filter: blur(3px);
}
.access-preview-dialog table {
  min-width: 620px;
}
.access-preview-dialog td {
  white-space: normal;
  vertical-align: top;
}
.access-preview-dialog li {
  margin-bottom: 8px;
}
.access-preview-dialog .row {
  justify-content: flex-end;
  margin-top: 20px;
}
</style>
