<script setup lang="ts">
import { vValidateForm } from '../formValidation'
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { api, errorMessage } from '../api'
import { useAuthStore } from '../auth'
import { confirmAction } from '../confirmation'
import { useWorkspaceStore } from '../workspace'
import PropertySection from './PropertySection.vue'
import {
  useAdministrationStore,
  type NotificationEndpoint as Endpoint,
} from '../stores/administration'

const w = useWorkspaceStore()
const auth = useAuthStore()
const eventKinds = [
  { value: 'general', label: 'General alerts', scoped: false, priority: 3 },
  { value: 'empty_tape', label: 'Empty cartridges', scoped: true, priority: 4 },
  { value: 'printer_blocked', label: 'Blocked printers', scoped: true, priority: 4 },
  { value: 'batch_review', label: 'Batch reviews', scoped: true, priority: 4 },
  { value: 'tape_waiting', label: 'Waiting tape reminders', scoped: true, priority: 3 },
  { value: 'approval_digest', label: 'Pending print requests', scoped: false, priority: 3 },
]
const priorityOptions = [
  { value: 1, label: 'Min' },
  { value: 2, label: 'Low' },
  { value: 3, label: 'Normal' },
  { value: 4, label: 'High' },
  { value: 5, label: 'Urgent' },
]
const administration = useAdministrationStore()
const { endpoints } = storeToRefs(administration)
const busy = ref(false),
  error = ref(''),
  success = ref(''),
  showForm = ref(false),
  editing = ref<Endpoint | null>(null)
const defaults = () => ({
  name: '',
  url: '',
  topic: '',
  token: '',
  clear_token: false,
  enabled: true,
  all_printers: false,
  destination_ids: [] as string[],
  kinds: eventKinds.filter((kind) => !kind.scoped).map((kind) => kind.value),
  priorities: Object.fromEntries(eventKinds.map((kind) => [kind.value, kind.priority])) as Record<
    string,
    number
  >,
})
const form = reactive(defaults())
const currentPrinters = computed(() =>
  w.destinations.filter((destination) => destination.kind === 'printer'),
)
const hasPrinterScope = computed(() => form.all_printers || form.destination_ids.length > 0)
watch(
  [hasPrinterScope, () => form.kinds],
  ([scoped]) => {
    if (!scoped) {
      const allowed = form.kinds.filter(
        (value) => !eventKinds.some((kind) => kind.value === value && kind.scoped),
      )
      if (allowed.length !== form.kinds.length) form.kinds = allowed
    }
  },
  { flush: 'sync' },
)
watch(
  () => form.all_printers,
  (all) => {
    if (all) form.destination_ids = []
  },
  { flush: 'sync' },
)
const unavailableDestinations = computed(() =>
  form.destination_ids.filter((id) => !w.destinations.some((destination) => destination.id === id)),
)
function selectAll() {
  form.destination_ids = currentPrinters.value.map((printer) => printer.id)
  form.all_printers = false
}
function clearSelection() {
  form.all_printers = false
  form.destination_ids = []
}
async function load() {
  if (!auth.user?.is_admin) return
  await administration.load(['endpoints'])
}
function edit(endpoint?: Endpoint) {
  editing.value = endpoint ?? null
  Object.assign(
    form,
    defaults(),
    endpoint
      ? {
          name: endpoint.name,
          url: endpoint.url,
          topic: endpoint.topic,
          enabled: endpoint.enabled,
          all_printers: endpoint.all_printers,
          destination_ids: [...endpoint.destination_ids],
          kinds: [...endpoint.kinds],
          priorities: { ...defaults().priorities, ...endpoint.priorities },
        }
      : {},
  )
  showForm.value = true
  error.value = ''
  success.value = ''
}
function cancel() {
  showForm.value = false
  editing.value = null
  Object.assign(form, defaults())
}
async function perform(task: () => Promise<unknown>, message: string) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  success.value = ''
  try {
    await task()
    await load()
    await w.refresh()
    success.value = message
  } catch (issue) {
    error.value = errorMessage(issue)
  } finally {
    busy.value = false
  }
}
async function save() {
  const endpoint = editing.value
  await perform(async () => {
    await api(
      `/admin/notification-endpoints${endpoint ? '/' + endpoint.id : ''}`,
      endpoint ? 'PUT' : 'POST',
      {
        name: form.name,
        url: form.url,
        topic: form.topic,
        enabled: form.enabled,
        all_printers: form.all_printers,
        destination_ids: [...form.destination_ids],
        kinds: [...form.kinds],
        priorities: { ...form.priorities },
        token: form.clear_token ? '' : form.token || null,
      },
    )
    cancel()
  }, 'Notification endpoint saved.')
}
async function remove(endpoint: Endpoint) {
  if (!(await confirmAction(`Delete notification endpoint “${endpoint.name}”?`))) return
  await perform(async () => {
    await api(`/admin/notification-endpoints/${endpoint.id}`, 'DELETE')
    if (editing.value?.id === endpoint.id) cancel()
  }, 'Notification endpoint deleted.')
}
function refreshAccess() {
  void load().catch((issue) => {
    error.value = errorMessage(issue)
  })
}
onMounted(() => {
  window.addEventListener('access-changed', refreshAccess)
  refreshAccess()
})
onUnmounted(() => window.removeEventListener('access-changed', refreshAccess))
</script>

<template>
  <section v-if="auth.user?.is_admin" class="panel notification-endpoints">
    <PropertySection title="Notification endpoints">
      <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
      <p v-if="success" class="alert success" role="status">{{ success }}</p>
      <div class="section-heading">
        <span class="muted">{{ endpoints.length }} configured</span>
        <button class="secondary" :disabled="busy" @click="edit()">
          Add notification endpoint
        </button>
      </div>
      <p v-if="!endpoints.length" class="empty compact">No notification endpoints configured.</p>
      <article v-for="endpoint in endpoints" :key="endpoint.id" class="endpoint-row">
        <div class="grow">
          <strong>{{ endpoint.name }}</strong>
          <small>{{ endpoint.url }} / {{ endpoint.topic }}</small>
          <small
            >{{ endpoint.has_token ? 'Token stored' : 'No token stored' }} ·
            {{
              endpoint.all_printers
                ? 'All current and future printers'
                : endpoint.destination_ids.length
                  ? endpoint.destination_ids.map(w.destinationName).join(', ')
                  : 'No printers or groups selected'
            }}</small
          >
        </div>
        <span class="badge" :class="endpoint.enabled ? 'printed' : 'cancelled'">{{
          endpoint.enabled ? 'Enabled' : 'Disabled'
        }}</span>
        <div class="row wrap">
          <button
            class="small secondary"
            :disabled="busy"
            :aria-label="`Edit endpoint ${endpoint.name}`"
            @click="edit(endpoint)"
          >
            Edit
          </button>
          <button
            class="small danger-text"
            :disabled="busy"
            :aria-label="`Delete endpoint ${endpoint.name}`"
            @click="remove(endpoint)"
          >
            Delete
          </button>
        </div>
      </article>
      <form v-validate-form v-if="showForm" class="form-stack endpoint-form" @submit.prevent="save">
        <h3>{{ editing ? 'Edit notification endpoint' : 'New notification endpoint' }}</h3>
        <label>Endpoint name<input v-model="form.name" required maxlength="100" /></label>
        <div class="field-row">
          <label
            >ntfy server URL<input
              v-model="form.url"
              type="url"
              required
              maxlength="2048"
              placeholder="https://ntfy.example.com"
          /></label>
          <label
            >ntfy topic<input v-model="form.topic" required maxlength="64" pattern="[-_A-Za-z0-9]+"
          /></label>
        </div>
        <label
          >Access token<input
            v-model="form.token"
            type="password"
            autocomplete="new-password"
            :disabled="form.clear_token"
          /><span class="help">{{
            editing?.has_token
              ? 'Leave blank to keep the stored token.'
              : 'Optional. Tokens are stored privately and never shown again.'
          }}</span></label
        >
        <label v-if="editing?.has_token" class="checkbox"
          ><input v-model="form.clear_token" type="checkbox" />Clear stored token</label
        >
        <label class="checkbox"
          ><input v-model="form.enabled" type="checkbox" />Enable this endpoint</label
        >
        <fieldset class="form-stack">
          <legend>Print destinations</legend>
          <label class="checkbox">
            <input v-model="form.all_printers" type="checkbox" />All current and future printers
          </label>
          <div class="row wrap">
            <button
              type="button"
              class="secondary"
              :disabled="busy || !currentPrinters.length"
              @click="selectAll"
            >
              Select all
            </button>
            <button
              type="button"
              class="secondary"
              :disabled="busy || !hasPrinterScope"
              @click="clearSelection"
            >
              Clear selection
            </button>
          </div>
          <div class="choice-grid">
            <label v-for="destination in w.destinations" :key="destination.id" class="checkbox"
              ><input
                v-model="form.destination_ids"
                type="checkbox"
                :value="destination.id"
                :aria-label="`Notify for ${destination.name}`"
                :disabled="form.all_printers"
              />{{ destination.name }}
              <span class="muted">{{
                destination.kind === 'group' ? '(group)' : '(printer)'
              }}</span></label
            >
            <label
              v-for="id in unavailableDestinations"
              :key="id"
              class="checkbox unavailable-choice"
              ><input
                v-model="form.destination_ids"
                type="checkbox"
                :value="id"
                :aria-label="`Remove unavailable destination ${id}`"
              />Unavailable destination ({{ id }})</label
            >
          </div>
        </fieldset>
        <p v-if="unavailableDestinations.length" class="help">
          Unselect unavailable destinations before saving.
        </p>
        <p class="help">
          Select all chooses only current physical printers. Select groups individually to include
          their member printers’ operational alerts as membership changes.
        </p>
        <fieldset class="event-types">
          <legend>Event types</legend>
          <div v-for="kind in eventKinds" :key="kind.value" class="event-type">
            <label class="checkbox">
              <input
                v-model="form.kinds"
                type="checkbox"
                :value="kind.value"
                :disabled="kind.scoped && !hasPrinterScope"
              />{{ kind.label }}
            </label>
            <label class="event-priority"
              >Priority
              <select
                v-model.number="form.priorities[kind.value]"
                :aria-label="`Priority for ${kind.label}`"
                :disabled="!form.kinds.includes(kind.value) || (kind.scoped && !hasPrinterScope)"
              >
                <option
                  v-for="priority in priorityOptions"
                  :key="priority.value"
                  :value="priority.value"
                >
                  {{ priority.label }}
                </option>
              </select>
            </label>
          </div>
        </fieldset>
        <p v-if="!hasPrinterScope" class="help">
          Select a printer, group or all printers to enable cartridge, printer, batch and tape
          alerts. General alerts and pending print requests can be sent without a printer selection.
        </p>
        <p v-if="!form.kinds.length" class="help">Select at least one event type.</p>
        <div class="row wrap">
          <button
            class="primary"
            :disabled="busy || !form.kinds.length || !!unavailableDestinations.length"
          >
            Save notification endpoint
          </button>
          <button type="button" :disabled="busy" @click="cancel">Cancel</button>
        </div>
      </form>
    </PropertySection>
  </section>
</template>

<style scoped>
.endpoint-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
  padding: 16px 0;
  border-bottom: 1px solid var(--line);
}
.endpoint-row small {
  display: block;
  margin-top: 4px;
  color: var(--muted);
  overflow-wrap: anywhere;
}
.endpoint-form {
  margin-top: 24px;
}
.choice-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(220px, 100%), 1fr));
  gap: 12px;
}
.unavailable-choice {
  min-width: 0;
  overflow-wrap: anywhere;
}
.event-types {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(300px, 100%), 1fr));
  gap: 16px;
}
.event-type {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 100px;
  align-items: center;
  gap: 12px;
}
@media (max-width: 600px) {
  .endpoint-row > .grow {
    flex-basis: 100%;
  }
}
</style>
