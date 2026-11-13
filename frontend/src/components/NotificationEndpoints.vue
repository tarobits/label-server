<script setup lang="ts">
import { t } from '../shared/i18n'
import { vValidateForm } from '../shared/formValidation'
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { api, errorMessage } from '../shared/api'
import { useAuthStore } from '../auth/auth'
import { confirmAction } from '../shared/confirmation'
import { useWorkspaceStore } from '../shared/workspace'
import AdminDialog from './AdminDialog.vue'
import MotionSurface from './MotionSurface.vue'
import ExpandableContent from './ExpandableContent.vue'
import PrinterNotificationKinds from './PrinterNotificationKinds.vue'
import {
  scopedPrinters,
  selectedPrinterKinds,
  priorityOptions,
  type PrinterKinds,
  type PrinterPriorities,
} from '../notifications/notificationPreferences'
import {
  useAdministrationStore,
  type NotificationEndpoint as Endpoint,
} from '../stores/administration'

const w = useWorkspaceStore()
const auth = useAuthStore()
const eventKinds = [
  {
    value: 'general',
    get label() {
      return t('uiMessages.generalAlerts')
    },
    scoped: false,
    priority: 3,
  },
  {
    value: 'empty_tape',
    get label() {
      return t('uiMessages.emptyCartridges')
    },
    scoped: true,
    priority: 4,
  },
  {
    value: 'printer_blocked',
    get label() {
      return t('uiMessages.blockedPrinters')
    },
    scoped: true,
    priority: 4,
  },
  {
    value: 'batch_review',
    get label() {
      return t('uiMessages.batchReviews')
    },
    scoped: true,
    priority: 4,
  },
  {
    value: 'batch_printed',
    get label() {
      return t('uiMessages.finishedBatches')
    },
    scoped: true,
    priority: 3,
  },
  {
    value: 'tape_waiting',
    get label() {
      return t('uiMessages.waitingTapeReminders')
    },
    scoped: true,
    priority: 3,
  },
  {
    value: 'approval_digest',
    get label() {
      return t('uiMessages.pendingPrintRequests')
    },
    scoped: false,
    priority: 3,
  },
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
  transport: 'ntfy' as 'ntfy' | 'email',
  email: '',
  url: '',
  topic: '',
  token: '',
  clear_token: false,
  enabled: true,
  all_printers: false,
  destination_ids: [] as string[],
  kinds: eventKinds.filter((kind) => !kind.scoped).map((kind) => kind.value),
  printer_kinds: {} as PrinterKinds,
  printer_priorities: {} as PrinterPriorities,
  priorities: Object.fromEntries(eventKinds.map((kind) => [kind.value, kind.priority])) as Record<
    string,
    number
  >,
})
const form = reactive(defaults())
const search = ref('')
const filteredEndpoints = computed(() =>
  endpoints.value.filter((endpoint) =>
    `${endpoint.name} ${endpoint.url} ${endpoint.topic} ${endpoint.email}`
      .toLowerCase()
      .includes(search.value.trim().toLowerCase()),
  ),
)
const currentPrinters = computed(() =>
  w.destinations.filter((destination) => destination.kind === 'printer'),
)
const hasPrinterScope = computed(() => form.all_printers || form.destination_ids.length > 0)
const customPrinters = computed(() =>
  scopedPrinters(w.destinations, form.all_printers, form.destination_ids),
)
const printerKinds = computed(() => selectedPrinterKinds(form.printer_kinds, customPrinters.value))
const hasEvents = computed(
  () =>
    form.kinds.length > 0 || Object.values(printerKinds.value).some((kinds) => kinds.length > 0),
)
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
          transport: endpoint.transport,
          email: endpoint.email,
          url: endpoint.url,
          topic: endpoint.topic,
          enabled: endpoint.enabled,
          all_printers: endpoint.all_printers,
          destination_ids: [...endpoint.destination_ids],
          kinds: [...endpoint.kinds],
          printer_kinds: Object.fromEntries(
            Object.entries(endpoint.printer_kinds ?? {}).map(([id, kinds]) => [id, [...kinds]]),
          ),
          printer_priorities: Object.fromEntries(
            Object.entries(endpoint.printer_priorities ?? {}).map(([id, priorities]) => [
              id,
              { ...priorities },
            ]),
          ),
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
        transport: form.transport,
        email: form.transport === 'email' ? form.email : '',
        url: form.transport === 'ntfy' ? form.url : '',
        topic: form.transport === 'ntfy' ? form.topic : '',
        enabled: form.enabled,
        all_printers: form.all_printers,
        destination_ids: [...form.destination_ids],
        kinds: [...form.kinds],
        printer_kinds: printerKinds.value,
        printer_priorities:
          form.transport === 'ntfy'
            ? Object.fromEntries(
                Object.entries(form.printer_priorities).filter(([id]) => id in printerKinds.value),
              )
            : {},
        priorities: { ...form.priorities },
        token: form.clear_token ? '' : form.token || null,
      },
    )
    cancel()
  }, t('uiMessages.notificationEndpointSaved'))
}
async function remove(endpoint: Endpoint) {
  if (
    !(await confirmAction(
      t('uiDetails.deleteNotificationEndpoint', { value1: String(endpoint.name) }),
    ))
  )
    return
  await perform(async () => {
    await api(`/admin/notification-endpoints/${endpoint.id}`, 'DELETE')
    if (editing.value?.id === endpoint.id) cancel()
  }, t('uiMessages.notificationEndpointDeleted'))
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
  <section v-if="auth.user?.is_admin" class="notification-endpoints">
    <p v-if="error && !showForm" class="alert danger" role="alert">{{ error }}</p>
    <p v-if="success" class="alert success" role="status">{{ success }}</p>
    <header class="admin-section-heading">
      <h2>
        {{ $t('notificationEndpoints.notificationEndpoints') }} <span>{{ endpoints.length }}</span>
      </h2>
      <button class="secondary" :disabled="busy" @click="edit()">
        {{ $t('notificationEndpoints.addNotificationEndpoint') }}
      </button>
    </header>
    <label v-if="endpoints.length" class="admin-search"
      >{{ $t('common.searchNotificationEndpoints') }}<input v-model="search" type="search"
    /></label>
    <p v-if="endpoints.length && !filteredEndpoints.length" class="empty compact">
      {{ $t('notificationEndpoints.noNotificationEndpointsFound') }}
    </p>
    <p v-if="!endpoints.length" class="empty compact">
      {{ $t('notificationEndpoints.noNotificationEndpointsConfigured') }}
    </p>
    <article v-for="endpoint in filteredEndpoints" :key="endpoint.id" class="endpoint-row">
      <div class="grow">
        <strong>{{ endpoint.name }}</strong>
        <small>{{
          endpoint.transport === 'email' ? endpoint.email : `${endpoint.url} / ${endpoint.topic}`
        }}</small>
        <small
          ><template v-if="endpoint.transport === 'ntfy'"
            >{{
              endpoint.has_token ? $t('uiMessages.tokenStored') : $t('uiMessages.noTokenStored')
            }}
            ·
          </template>
          {{
            endpoint.all_printers
              ? $t('notificationEndpoints.allCurrentAndFuturePrinters')
              : endpoint.destination_ids.length
                ? endpoint.destination_ids.map(w.destinationName).join(', ')
                : $t('uiMessages.noPrintersOrGroupsSelected')
          }}</small
        >
      </div>
      <span class="badge" :class="endpoint.enabled ? 'printed' : 'cancelled'">{{
        endpoint.enabled ? $t('uiMessages.enabled') : $t('administration.disabled')
      }}</span>
      <div class="row wrap">
        <button
          class="secondary"
          :disabled="busy"
          :aria-label="$t('uiDetails.editEndpoint', { value1: String(endpoint.name) })"
          @click="edit(endpoint)"
        >
          {{ $t('common.edit') }}
        </button>
      </div>
    </article>
    <AdminDialog
      :open="showForm"
      :title="
        editing
          ? $t('uiMessages.editNotificationEndpoint')
          : $t('uiMessages.newNotificationEndpoint')
      "
      :busy="busy"
      wide
      @close="cancel"
    >
      <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
      <form v-validate-form class="form-stack" @submit.prevent="save">
        <label
          >{{ $t('notificationEndpoints.endpointName')
          }}<input v-model="form.name" required maxlength="100"
        /></label>
        <label
          >{{ $t('notificationEndpoints.deliveryMethod')
          }}<select v-model="form.transport">
            <option value="ntfy">{{ $t('common.ntfy') }}</option>
            <option value="email">{{ $t('notificationEndpoints.email') }}</option>
          </select></label
        >
        <MotionSurface :identity="form.transport" class="form-stack">
          <label v-if="form.transport === 'email'"
            >{{ $t('notificationEndpoints.recipientEmail')
            }}<input v-model="form.email" type="email" required maxlength="254"
          /></label>
          <template v-else>
            <div class="field-row">
              <label
                >{{ $t('common.ntfyServerUrl')
                }}<input
                  v-model="form.url"
                  type="url"
                  required
                  maxlength="2048"
                  :placeholder="$t('common.httpsNtfyExampleCom')"
              /></label>
              <label
                >{{ $t('common.ntfyTopic')
                }}<input v-model="form.topic" required maxlength="64" pattern="[-_A-Za-z0-9]+"
              /></label>
            </div>
            <label
              >{{ $t('notificationEndpoints.accessToken')
              }}<input
                v-model="form.token"
                type="password"
                autocomplete="new-password"
                :disabled="form.clear_token"
              /><span class="help">{{
                editing?.has_token
                  ? $t('uiMessages.leaveBlankToKeepTheStoredToken')
                  : $t('uiMessages.optionalTokensAreStoredPrivatelyAndNeverShownAgain')
              }}</span></label
            >
            <label v-if="editing?.has_token" class="checkbox"
              ><input v-model="form.clear_token" type="checkbox" />{{
                $t('notificationEndpoints.clearStoredToken')
              }}</label
            >
          </template>
        </MotionSurface>
        <label class="checkbox"
          ><input v-model="form.enabled" type="checkbox" />{{
            $t('notificationEndpoints.enableThisEndpoint')
          }}</label
        >
        <fieldset class="choice-list">
          <legend>{{ $t('common.printDestinations') }}</legend>
          <label class="checkbox">
            <input v-model="form.all_printers" type="checkbox" />{{
              $t('notificationEndpoints.allCurrentAndFuturePrinters')
            }}
          </label>
          <div class="row wrap">
            <button
              type="button"
              class="secondary"
              :disabled="busy || !currentPrinters.length"
              @click="selectAll"
            >
              {{ $t('common.selectAll') }}
            </button>
            <button
              type="button"
              class="secondary"
              :disabled="busy || !hasPrinterScope"
              @click="clearSelection"
            >
              {{ $t('notificationEndpoints.clearSelection') }}
            </button>
          </div>
          <div class="choice-grid">
            <label v-for="destination in w.destinations" :key="destination.id" class="checkbox"
              ><input
                v-model="form.destination_ids"
                type="checkbox"
                :value="destination.id"
                :aria-label="$t('uiDetails.notifyFor', { value1: String(destination.name) })"
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
                :aria-label="$t('uiDetails.removeUnavailableDestination', { value1: String(id) })"
              />{{ $t('common.unavailableDestination') }}{{ id }})</label
            >
          </div>
        </fieldset>
        <p v-if="unavailableDestinations.length" class="help">
          {{ $t('common.unselectUnavailableDestinationsBeforeSaving') }}
        </p>
        <p class="help">
          {{ $t('common.selectAllChoosesOnlyCurrentPhysicalPrintersSelectGroups') }}
        </p>
        <fieldset class="notification-event-grid">
          <legend>{{ $t('common.defaultEventTypes') }}</legend>
          <div
            v-for="kind in eventKinds"
            :key="kind.value"
            class="notification-event-row"
            :class="{ 'without-priority': form.transport !== 'ntfy' }"
          >
            <label class="checkbox">
              <input
                v-model="form.kinds"
                type="checkbox"
                :value="kind.value"
                :disabled="kind.scoped && !hasPrinterScope"
              />{{ kind.label }}
            </label>
            <ExpandableContent :open="form.transport === 'ntfy'">
              <label class="event-priority"
                >{{ $t('common.priority') }}
                <select
                  v-model.number="form.priorities[kind.value]"
                  :aria-label="$t('uiDetails.eventPriority', { value1: String(kind.label) })"
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
            </ExpandableContent>
          </div>
        </fieldset>
        <PrinterNotificationKinds
          v-model="form.printer_kinds"
          v-model:priorities="form.printer_priorities"
          :show-priorities="form.transport === 'ntfy'"
          :default-priorities="form.priorities"
          :printers="customPrinters"
          :defaults="form.kinds"
          :disabled="busy"
        />
        <p v-if="!hasPrinterScope" class="help">
          {{ $t('common.selectAPrinterGroupOrAllPrintersToEnable') }}
        </p>
        <p v-if="!hasEvents" class="help">{{ $t('common.selectAtLeastOneEventType') }}</p>
        <div class="admin-actions">
          <button
            v-if="editing"
            type="button"
            class="secondary danger-text"
            :disabled="busy"
            :aria-label="$t('uiDetails.deleteEndpoint', { value1: String(editing.name) })"
            @click="remove(editing)"
          >
            {{ $t('notificationEndpoints.deleteEndpoint') }}
          </button>
          <button
            class="primary"
            :disabled="busy || !hasEvents || !!unavailableDestinations.length"
          >
            {{ $t('common.saveNotificationEndpoint') }}
          </button>
          <button type="button" :disabled="busy" @click="cancel">{{ $t('common.cancel') }}</button>
        </div>
      </form>
    </AdminDialog>
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
.admin-section-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 24px;
}
h2 {
  margin: 0;
  font-size: 20px;
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
.choice-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(220px, 100%), 1fr));
  gap: 12px;
}
.unavailable-choice {
  min-width: 0;
  overflow-wrap: anywhere;
}
@media (max-width: 600px) {
  .endpoint-row > .grow {
    flex-basis: 100%;
  }
}
</style>
