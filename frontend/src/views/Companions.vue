<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, errorMessage } from '../api'
import { confirmAction } from '../confirmation'
import type { AccessCatalog, AccessPreview, Grant } from '../resourceAccess'
import AdminDialog from '../components/AdminDialog.vue'
import ExpandableContent from '../components/ExpandableContent.vue'
import ResourceImpact from '../components/ResourceImpact.vue'
import { vValidateForm } from '../formValidation'

interface Companion {
  id: string
  name: string
  location_id: string
  bound_user_id: string | null
  revision: number
  enabled: boolean
  status: 'online' | 'offline' | 'never_connected' | 'revoked'
  last_seen_at: number | null
  software_version: string | null
  server_version: string
  grants: Grant[]
}
interface Draft {
  name: string
  location_id: string
  bound_user_id: string | null
  grants: Grant[]
  expected_revision?: number
}
const items = ref<Companion[]>([]),
  catalog = ref<AccessCatalog>()
const form = ref<Draft>(),
  selected = ref<Companion>(),
  preview = ref<AccessPreview>()
const busy = ref(false),
  error = ref(''),
  success = ref(''),
  key = ref(''),
  copied = ref(false)
const principal = ref('')
const refreshError = ref('')
const statusLabels = {
  online: 'Online',
  offline: 'Offline',
  never_connected: 'Never connected',
  revoked: 'Key revoked',
}
let refreshTimer: ReturnType<typeof setTimeout> | undefined
let loadGeneration = 0
let disposed = false
onBeforeUnmount(() => {
  disposed = true
  clearTimeout(refreshTimer)
  key.value = ''
})
const people = computed(() => [
  ...(catalog.value?.users ?? []).map((u) => ({ id: `user:${u.id}`, name: u.name })),
  ...(catalog.value?.roles ?? []).map((r) => ({ id: `role:${r.id}`, name: `Role: ${r.name}` })),
])
async function load() {
  const [, access] = await Promise.all([loadCompanions(), api<AccessCatalog>('/resource-access')])
  if (!disposed) {
    catalog.value = access
  }
}
async function loadCompanions() {
  const generation = ++loadGeneration
  try {
    const companions = await api<Companion[]>('/companions')
    if (!disposed && generation === loadGeneration) {
      items.value = companions
      refreshError.value = ''
    }
  } catch (issue) {
    if (!disposed && generation === loadGeneration) refreshError.value = errorMessage(issue)
    throw issue
  }
}
async function refresh() {
  try {
    if (!busy.value) await (catalog.value ? loadCompanions() : load())
  } catch (issue) {
    if (!disposed) refreshError.value = errorMessage(issue)
  } finally {
    if (!disposed) refreshTimer = setTimeout(refresh, 5000)
  }
}
onMounted(refresh)
function versionMismatch(item: Companion) {
  return !!item.software_version && item.software_version !== item.server_version
}
function edit(item?: Companion) {
  selected.value = item
  preview.value = undefined
  error.value = ''
  success.value = ''
  principal.value = ''
  form.value = item
    ? {
        name: item.name,
        location_id: item.location_id,
        bound_user_id: item.bound_user_id,
        grants: item.grants.map((g) => ({ ...g })),
        expected_revision: item.revision,
      }
    : {
        name: '',
        location_id: catalog.value?.locations[0]?.id ?? '',
        bound_user_id: null,
        grants: [],
      }
}
function grant(value = principal.value) {
  if (!form.value || !value) return
  const split = value.indexOf(':')
  if (!form.value.grants.some((g) => `${g.principal_kind}:${g.principal_id}` === value))
    form.value.grants.push({
      principal_kind: value.slice(0, split) as 'user' | 'role',
      principal_id: value.slice(split + 1),
      permission: 'companion.access',
    })
  preview.value = undefined
  principal.value = ''
}
async function save() {
  if (!form.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    if (selected.value && !preview.value) {
      preview.value = await api<AccessPreview>(
        `/companions/${selected.value.id}/preview`,
        'POST',
        form.value,
      )
      return
    }
    const result = await api<{ api_key?: string }>(
      selected.value ? `/companions/${selected.value.id}` : '/companions',
      selected.value ? 'PUT' : 'POST',
      form.value,
      preview.value ? { 'X-Access-Confirmation': preview.value.confirmation_token } : {},
    )
    if (disposed) return
    form.value = undefined
    key.value = result.api_key ?? ''
    copied.value = false
    success.value = 'Companion saved.'
    await load()
  } catch (issue) {
    if (!disposed) {
      error.value = errorMessage(issue)
      preview.value = undefined
    }
  } finally {
    busy.value = false
  }
}
async function keyAction(item: Companion, revoke: boolean) {
  if (
    !(await confirmAction(
      revoke
        ? `Revoke ${item.name}'s key? It will disconnect and cannot receive more work.`
        : `Replace ${item.name}'s key? Update its deployment with the new key to reconnect.`,
      revoke ? 'Revoke key' : 'Replace key',
    ))
  )
    return
  busy.value = true
  error.value = ''
  try {
    const result = await api<{ api_key?: string }>(
      `/companions/${item.id}/key`,
      revoke ? 'DELETE' : 'POST',
    )
    if (disposed) return
    key.value = result.api_key ?? ''
    copied.value = false
    await load()
  } catch (issue) {
    if (!disposed) error.value = errorMessage(issue)
  } finally {
    busy.value = false
  }
}
async function copyKey() {
  try {
    await navigator.clipboard.writeText(key.value)
    copied.value = true
  } catch {
    error.value = 'Copy the key from the field below.'
  }
}
function removeGrant(index: number) {
  form.value?.grants.splice(index, 1)
  preview.value = undefined
}
</script>

<template>
  <section class="panel">
    <div class="section-heading wrap">
      <h2>Companions</h2>
      <button class="primary" :disabled="busy || !catalog?.locations.length" @click="edit()">
        Add companion
      </button>
    </div>
    <p v-if="(error || refreshError) && !form && !key" class="alert danger" role="alert">
      {{ error || refreshError }}
    </p>
    <p v-if="success" class="alert success" role="status">{{ success }}</p>
    <p v-if="catalog && !catalog.locations.length">
      <RouterLink to="/resource-access">Add a location</RouterLink> before registering a companion.
    </p>
    <p v-else-if="!items.length" class="muted">No companions registered.</p>
    <div v-for="item in items" :key="item.id" class="companion-row">
      <div class="companion-details">
        <div class="companion-heading">
          <h3>{{ item.name }}</h3>
          <span
            class="badge"
            :class="{
              printed: !refreshError && item.status === 'online',
              failed: !refreshError && ['offline', 'revoked'].includes(item.status),
            }"
            >{{ refreshError ? 'Status unavailable' : statusLabels[item.status] }}</span
          >
        </div>
        <p class="muted">
          {{ catalog?.locations.find((l) => l.id === item.location_id)?.name }} ·
          {{
            item.bound_user_id
              ? (catalog?.users.find((u) => u.id === item.bound_user_id)?.name ??
                'Unavailable user')
              : 'User picker'
          }}
        </p>
        <div class="companion-telemetry muted">
          <span>{{ item.software_version ? `v${item.software_version}` : 'Version unknown' }}</span>
          <span v-if="item.last_seen_at !== null">
            Last seen
            <time :datetime="new Date(item.last_seen_at * 1000).toISOString()">
              {{ new Date(item.last_seen_at * 1000).toLocaleString() }}
            </time>
          </span>
        </div>
        <ExpandableContent :open="versionMismatch(item)">
          <p class="inline-warning companion-version-warning">
            Version mismatch · Main server v{{ item.server_version }}
          </p>
        </ExpandableContent>
      </div>
      <div class="row wrap">
        <button class="secondary" :disabled="busy" @click="edit(item)">Settings</button
        ><button class="secondary" :disabled="busy" @click="keyAction(item, false)">
          {{ item.enabled ? 'Replace key' : 'Generate key' }}</button
        ><button v-if="item.enabled" class="danger" :disabled="busy" @click="keyAction(item, true)">
          Revoke key
        </button>
      </div>
    </div>
  </section>
  <AdminDialog
    :open="!!form"
    :title="selected ? selected.name : 'Add companion'"
    :busy="busy"
    @close="form = undefined"
  >
    <form
      v-if="form"
      v-validate-form
      class="form-stack"
      @submit.prevent="save"
      @input="preview = undefined"
    >
      <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
      <label>Name<input v-model="form.name" required maxlength="100" :disabled="busy" /></label>
      <label
        >Location<select v-model="form.location_id" required :disabled="busy">
          <option v-for="location in catalog?.locations" :key="location.id" :value="location.id">
            {{ location.name }}
          </option>
        </select></label
      >
      <label
        >Station user<select
          v-model="form.bound_user_id"
          :disabled="busy"
          @change="form.bound_user_id && grant(`user:${form.bound_user_id}`)"
        >
          <option :value="null">User picker</option>
          <option v-for="user in catalog?.users" :key="user.id" :value="user.id">
            {{ user.name }}
          </option>
        </select></label
      >
      <ExpandableContent :open="!!form.bound_user_id"
        ><label>Deployment user ID<input :value="form.bound_user_id ?? ''" readonly /></label>
        <p class="alert warning">
          Anyone with the shared deployment PIN can use the selected account’s permissions at this
          companion.
        </p></ExpandableContent
      >
      <fieldset>
        <legend>Companion access</legend>
        <div class="row">
          <label class="grow"
            >User or role<select v-model="principal" :disabled="busy">
              <option value="">Choose a user or role</option>
              <option v-for="person in people" :key="person.id" :value="person.id">
                {{ person.name }}
              </option>
            </select></label
          ><button type="button" class="secondary" :disabled="busy || !principal" @click="grant()">
            Add
          </button>
        </div>
        <div
          v-for="(entry, index) in form.grants"
          :key="`${entry.principal_kind}:${entry.principal_id}`"
          class="row spread grant-row"
        >
          <span>{{
            people.find((p) => p.id === `${entry.principal_kind}:${entry.principal_id}`)?.name ??
            entry.principal_id
          }}</span
          ><button
            type="button"
            class="secondary"
            :disabled="busy"
            :aria-label="`Remove ${entry.principal_id}`"
            @click="removeGrant(index)"
          >
            Remove
          </button>
        </div>
      </fieldset>
      <ExpandableContent :open="!!preview"
        ><ResourceImpact
          v-if="preview"
          :changes="preview.affected_users"
          :resources="catalog?.resources ?? []"
        />
        <p>Saving locks existing companion sessions.</p></ExpandableContent
      >
      <button class="primary" :disabled="busy">
        {{ selected ? (preview ? 'Confirm changes' : 'Review changes') : 'Create companion' }}
      </button>
    </form>
  </AdminDialog>
  <AdminDialog :open="!!key" title="Companion API key" @close="key = ''">
    <div class="form-stack">
      <p>Copy this key now. It is shown only once.</p>
      <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
      <label>API key<input :value="key" readonly autocomplete="off" spellcheck="false" /></label>
      <button type="button" class="primary" @click="copyKey">
        {{ copied ? 'Copied' : 'Copy key' }}
      </button>
    </div>
  </AdminDialog>
</template>

<style scoped>
.companion-row {
  padding-block: 24px;
  border-bottom: 1px solid var(--line);
  display: flex;
  gap: 24px;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
}
.companion-row h3 {
  margin: 0;
}
.companion-row p {
  margin: 0;
}
.grant-row {
  margin-top: 16px;
}
.companion-details {
  min-width: 0;
  overflow-wrap: anywhere;
}
.companion-heading,
.companion-telemetry {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 16px;
}
.companion-heading {
  margin-bottom: 8px;
}
.companion-telemetry {
  margin-top: 8px;
}
.companion-row .companion-version-warning {
  margin-top: 8px;
}
</style>
