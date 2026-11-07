<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { api, ApiError, errorMessage } from '../api'
import { useAuthStore } from '../auth'
import { useWorkspaceStore } from '../workspace'
import { confirmAction } from '../confirmation'
import { vValidateForm } from '../formValidation'
import {
  applicationKey,
  needsHomeScreen,
  pushRegistration,
  pushSupported,
  subscriptionId,
} from '../push'
import { scopedPrinters, selectedPrinterKinds, type PrinterKinds } from '../notificationPreferences'
import ExpandableContent from './ExpandableContent.vue'
import PrinterNotificationKinds from './PrinterNotificationKinds.vue'

interface Device {
  id: string
  name: string
  enabled: boolean
  all_printers: boolean
  destination_ids: string[]
  kinds: string[]
  printer_kinds: PrinterKinds
}
interface PushSettings {
  public_key: string | null
  devices: Device[]
}
const auth = useAuthStore(),
  w = useWorkspaceStore()
const settings = ref<PushSettings | null>(null)
const registration = ref<ServiceWorkerRegistration>()
const currentId = ref(''),
  busy = ref(false),
  editing = ref(false)
const error = ref(''),
  success = ref('')
const name = ref(
  /iPhone/.test(navigator.userAgent)
    ? 'iPhone'
    : /iPad/.test(navigator.userAgent) ||
        (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
      ? 'iPad'
      : /Android/.test(navigator.userAgent)
        ? 'Android'
        : 'This browser',
)
const enableButton = ref<HTMLButtonElement | null>(null)
const preferencesButton = ref<HTMLButtonElement | null>(null)
let pendingFocus = false
function restorePushFocus() {
  const target = enableButton.value || preferencesButton.value
  if (pendingFocus && target && !busy.value) {
    target.focus()
    pendingFocus = false
  }
}
const current = computed(() =>
  settings.value?.devices.find((device) => device.id === currentId.value),
)
const preferences = reactive({
  enabled: true,
  all_printers: false,
  destination_ids: [] as string[],
  kinds: ['general'],
  printer_kinds: {} as PrinterKinds,
})
const homeScreen = needsHomeScreen(),
  supported = pushSupported()
const destinations = computed(() =>
  w.destinations.filter((destination) => auth.atLeast(destination.id, 'moderator')),
)
const kinds = computed(() => [
  { value: 'general', label: 'General alerts', scoped: false },
  { value: 'job_printed', label: 'My printed labels', scoped: false },
  { value: 'empty_tape', label: 'Empty cartridges', scoped: true },
  { value: 'printer_blocked', label: 'Blocked printers', scoped: true },
  { value: 'batch_review', label: 'Batch reviews', scoped: true },
  { value: 'batch_printed', label: 'Finished batches', scoped: true },
  { value: 'tape_waiting', label: 'Waiting tape reminders', scoped: true },
  ...(auth.user?.is_admin
    ? [{ value: 'approval_digest', label: 'Pending print requests', scoped: false }]
    : []),
])
const selectedDestinations = computed(() =>
  preferences.destination_ids.filter((id) =>
    destinations.value.some((destination) => destination.id === id),
  ),
)
const selectedKinds = computed(() =>
  preferences.kinds.filter((value) =>
    kinds.value.some(
      (kind) =>
        kind.value === value &&
        (!kind.scoped || preferences.all_printers || selectedDestinations.value.length > 0),
    ),
  ),
)
const customPrinters = computed(() =>
  scopedPrinters(destinations.value, preferences.all_printers, selectedDestinations.value),
)
const printerKinds = computed(() =>
  selectedPrinterKinds(preferences.printer_kinds, customPrinters.value),
)
const hasEvents = computed(
  () =>
    selectedKinds.value.length > 0 ||
    Object.values(printerKinds.value).some((kinds) => kinds.length > 0),
)
async function load() {
  settings.value = await api<PushSettings>('/auth/push')
  if (supported && !homeScreen) {
    registration.value = await pushRegistration()
    const subscription = await registration.value.pushManager.getSubscription()
    currentId.value = subscription ? await subscriptionId(subscription) : ''
  }
  if (current.value) {
    Object.assign(preferences, current.value)
    name.value = current.value.name
  }
}
async function perform(task: () => Promise<string>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  success.value = ''
  try {
    const message = await task()
    await load()
    success.value = message
  } catch (issue) {
    error.value = errorMessage(issue)
    if (issue instanceof ApiError && [404, 410].includes(issue.status)) {
      await load().catch(() => {})
    }
  } finally {
    busy.value = false
  }
}
async function enable() {
  // Request permission directly in the click handler, before any network/worker wait.
  await perform(async () => {
    const permission =
      Notification.permission === 'granted' ? 'granted' : await Notification.requestPermission()
    if (permission === 'denied') {
      throw new Error(
        'The browser denied notification permission. Check this site’s notification permission and device settings. Some browsers disable web notifications entirely.',
      )
    }
    if (permission !== 'granted')
      throw new Error(
        'Notification permission was not granted. Try again and accept the browser’s permission prompt.',
      )
    const worker = registration.value
    if (!worker || !settings.value?.public_key) throw new Error('Reload the app and try again.')
    // Fresh keys prevent a different account on this installation from inheriting a subscription.
    const previous = await worker.pushManager.getSubscription()
    if (previous && !(await previous.unsubscribe()))
      throw new Error('Could not renew notifications. Try again.')
    const subscription = await worker.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: applicationKey(settings.value.public_key),
    })
    await api('/auth/push', 'POST', {
      name: name.value,
      subscription: subscription.toJSON(),
      replace_id: current.value?.id,
    })
    return 'Notifications enabled.'
  })
}
async function save() {
  await perform(async () => {
    await api(`/auth/push/${currentId.value}`, 'PUT', {
      enabled: true,
      all_printers: preferences.all_printers,
      destination_ids: preferences.all_printers ? [] : selectedDestinations.value,
      kinds: selectedKinds.value,
      printer_kinds: printerKinds.value,
    })
    editing.value = false
    return 'Notification preferences saved.'
  })
  if (!editing.value) {
    await nextTick()
    preferencesButton.value?.focus()
  }
}
async function testPush() {
  await perform(async () => {
    await api(`/auth/push/${currentId.value}/test`, 'POST', {})
    return 'Test notification sent.'
  })
}
async function remove(device: Device) {
  if (!(await confirmAction(`Stop notifications on ${device.name}?`, 'Remove device'))) return
  await perform(async () => {
    await api(`/auth/push/${device.id}`, 'DELETE')
    if (device.id === currentId.value) {
      editing.value = false
      try {
        await (await registration.value?.pushManager.getSubscription())?.unsubscribe()
      } catch {
        /* Already revoked on the server. */
      }
      const notifications = await registration.value?.getNotifications()
      notifications?.forEach((notification) => notification.close())
    }
    return 'Device removed.'
  })
  await nextTick()
  pendingFocus = true
  restorePushFocus()
}
onMounted(() => {
  void load().catch((issue) => {
    error.value = errorMessage(issue)
  })
})
</script>

<template>
  <div class="account-push">
    <h2>Push notifications</h2>
    <Transition name="notice"
      ><p v-if="error" class="alert danger" role="alert">{{ error }}</p></Transition
    >
    <Transition name="notice"
      ><p v-if="success" class="alert success" role="status">{{ success }}</p></Transition
    >
    <p v-if="!settings && !error" class="help" role="status">Loading notification settings…</p>
    <template v-if="settings">
      <p v-if="!settings.public_key" class="alert warning">
        Push delivery has not been configured by your administrator.
      </p>
      <p v-else-if="homeScreen" class="help">
        On iPhone or iPad, use Share → Add to Home Screen, then open the app from your Home Screen
        to enable notifications. Requires iOS or iPadOS 16.4 or later.
      </p>
      <p v-else-if="!supported" class="help">
        Push notifications are not supported in this browser. Open the app in a supported browser
        over HTTPS.
      </p>
      <template v-else>
        <Transition name="notice" mode="out-in" @after-enter="restorePushFocus">
          <form
            v-if="!current?.enabled"
            v-validate-form
            class="form-stack enable-push motion-reveal"
            @submit.prevent="enable"
          >
            <label
              >Device name<input v-model="name" required maxlength="100" :disabled="busy"
            /></label>
            <button ref="enableButton" class="primary" :disabled="busy || !registration">
              Enable notifications
            </button>
          </form>
          <div v-else class="row wrap motion-reveal">
            <button :disabled="busy" @click="testPush">Send test notification</button>
            <button
              ref="preferencesButton"
              :aria-expanded="editing"
              :disabled="busy"
              @click="editing = !editing"
            >
              Notification preferences
            </button>
          </div>
        </Transition>
        <ExpandableContent :open="editing && !!current?.enabled">
          <form v-validate-form class="form-stack subscription-options" @submit.prevent="save">
            <fieldset v-if="destinations.length" class="choice-list">
              <legend>Print destinations</legend>
              <label class="checkbox"
                ><input v-model="preferences.all_printers" type="checkbox" :disabled="busy" />All
                printers I can moderate</label
              >
              <label v-for="destination in destinations" :key="destination.id" class="checkbox"
                ><input
                  v-model="preferences.destination_ids"
                  :value="destination.id"
                  type="checkbox"
                  :disabled="busy || preferences.all_printers"
                />{{ destination.name }}</label
              >
            </fieldset>
            <fieldset class="choice-list">
              <legend>Default event types</legend>
              <label v-for="kind in kinds" :key="kind.value" class="checkbox"
                ><input
                  v-model="preferences.kinds"
                  :value="kind.value"
                  type="checkbox"
                  :disabled="
                    busy ||
                    (kind.scoped &&
                      !preferences.all_printers &&
                      !preferences.destination_ids.length)
                  "
                />{{ kind.label }}</label
              >
            </fieldset>
            <PrinterNotificationKinds
              v-model="preferences.printer_kinds"
              :printers="customPrinters"
              :defaults="selectedKinds"
              :disabled="busy"
            />
            <button class="primary" :disabled="busy || !hasEvents">
              Save notification preferences
            </button>
          </form>
        </ExpandableContent>
      </template>
      <TransitionGroup name="notice" tag="ul" class="device-list" aria-label="Notification devices">
        <li v-for="device in settings.devices" :key="device.id" class="row wrap motion-reveal">
          <span class="device-name"
            >{{ device.name
            }}<small
              >{{ device.id === currentId ? 'This device' : ''
              }}{{
                !device.enabled ? (device.id === currentId ? ' · Inactive' : 'Inactive') : ''
              }}</small
            ></span
          >
          <button
            class="danger-text"
            :disabled="busy"
            :aria-label="`Remove ${device.name}`"
            @click="remove(device)"
          >
            Remove
          </button>
        </li>
      </TransitionGroup>
    </template>
  </div>
</template>

<style scoped>
.account-push h2 {
  margin-bottom: 24px;
}
.enable-push {
  max-width: 440px;
}
.subscription-options {
  padding-block: 24px;
}
.device-list {
  list-style: none;
  padding: 0;
  margin: 24px 0 0;
}
.device-list li + li {
  margin-top: 16px;
}
.device-name {
  flex: 1;
  min-width: 0;
  overflow-wrap: anywhere;
}
.device-name small {
  display: block;
}
</style>
