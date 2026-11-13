<script setup lang="ts">
import { t } from '../shared/i18n'
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { api, ApiError, errorMessage } from '../shared/api'
import { useAuthStore } from '../auth/auth'
import { useWorkspaceStore } from '../shared/workspace'
import { confirmAction } from '../shared/confirmation'
import { vValidateForm } from '../shared/formValidation'
import {
  applicationKey,
  needsHomeScreen,
  pushRegistration,
  pushSupported,
  subscriptionId,
} from '../notifications/push'
import {
  scopedPrinters,
  selectedPrinterKinds,
  type PrinterKinds,
} from '../notifications/notificationPreferences'
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
        : t('uiMessages.thisBrowser'),
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
  w.destinations.filter((destination) => auth.printer(destination.id, 'view_activity')),
)
const kinds = computed(() => [
  {
    value: 'general',
    get label() {
      return t('uiMessages.generalAlerts')
    },
    scoped: false,
  },
  {
    value: 'job_printed',
    get label() {
      return t('uiMessages.myPrintedLabels')
    },
    scoped: false,
  },
  {
    value: 'empty_tape',
    get label() {
      return t('uiMessages.emptyCartridges')
    },
    scoped: true,
  },
  {
    value: 'printer_blocked',
    get label() {
      return t('uiMessages.blockedPrinters')
    },
    scoped: true,
  },
  {
    value: 'batch_review',
    get label() {
      return t('uiMessages.batchReviews')
    },
    scoped: true,
  },
  {
    value: 'batch_printed',
    get label() {
      return t('uiMessages.finishedBatches')
    },
    scoped: true,
  },
  {
    value: 'tape_waiting',
    get label() {
      return t('uiMessages.waitingTapeReminders')
    },
    scoped: true,
  },
  ...(auth.user?.is_admin
    ? [
        {
          value: 'approval_digest',
          get label() {
            return t('uiMessages.pendingPrintRequests')
          },
          scoped: false,
        },
      ]
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
        t(
          'uiMessages.theBrowserDeniedNotificationPermissionCheckThisSiteSNotificationPermissionAndDeviceSettingsSomeBrowsersDisableWebNotificationsEntirely',
        ),
      )
    }
    if (permission !== 'granted')
      throw new Error(
        t(
          'uiMessages.notificationPermissionWasNotGrantedTryAgainAndAcceptTheBrowserSPermissionPrompt',
        ),
      )
    const worker = registration.value
    if (!worker || !settings.value?.public_key)
      throw new Error(t('uiMessages.reloadTheAppAndTryAgain'))
    // Fresh keys prevent a different account on this installation from inheriting a subscription.
    const previous = await worker.pushManager.getSubscription()
    if (previous && !(await previous.unsubscribe()))
      throw new Error(t('uiMessages.couldNotRenewNotificationsTryAgain'))
    const subscription = await worker.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: applicationKey(settings.value.public_key),
    })
    await api('/auth/push', 'POST', {
      name: name.value,
      subscription: subscription.toJSON(),
      replace_id: current.value?.id,
    })
    return t('uiMessages.notificationsEnabled')
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
    return t('uiMessages.notificationPreferencesSaved')
  })
  if (!editing.value) {
    await nextTick()
    preferencesButton.value?.focus()
  }
}
async function testPush() {
  await perform(async () => {
    await api(`/auth/push/${currentId.value}/test`, 'POST', {})
    return t('uiMessages.testNotificationSent')
  })
}
async function remove(device: Device) {
  if (
    !(await confirmAction(
      t('uiDetails.stopDeviceNotifications', { value1: String(device.name) }),
      t('uiMessages.removeDevice'),
    ))
  )
    return
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
    return t('uiMessages.deviceRemoved')
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
    <h2>{{ $t('common.pushNotifications') }}</h2>
    <Transition name="notice"
      ><p v-if="error" class="alert danger" role="alert">{{ error }}</p></Transition
    >
    <Transition name="notice"
      ><p v-if="success" class="alert success" role="status">{{ success }}</p></Transition
    >
    <p v-if="!settings && !error" class="help" role="status">
      {{ $t('accountPush.loadingNotificationSettings') }}
    </p>
    <template v-if="settings">
      <p v-if="!settings.public_key" class="alert warning">
        {{ $t('accountPush.pushDeliveryHasNotBeenConfiguredByYourAdministrator') }}
      </p>
      <p v-else-if="homeScreen" class="help">
        {{ $t('accountPush.onIphoneOrIpadUseShareAddToHome') }}
      </p>
      <p v-else-if="!supported" class="help">
        {{ $t('accountPush.pushNotificationsAreNotSupportedInThisBrowserOpen') }}
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
              >{{ $t('accountPush.deviceName')
              }}<input v-model="name" required maxlength="100" :disabled="busy"
            /></label>
            <button ref="enableButton" class="primary" :disabled="busy || !registration">
              {{ $t('accountPush.enableNotifications') }}
            </button>
          </form>
          <div v-else class="row wrap motion-reveal">
            <button :disabled="busy" @click="testPush">
              {{ $t('common.sendTestNotification') }}
            </button>
            <button
              ref="preferencesButton"
              :aria-expanded="editing"
              :disabled="busy"
              @click="editing = !editing"
            >
              {{ $t('accountPush.notificationPreferences') }}
            </button>
          </div>
        </Transition>
        <ExpandableContent :open="editing && !!current?.enabled">
          <form v-validate-form class="form-stack subscription-options" @submit.prevent="save">
            <fieldset v-if="destinations.length" class="choice-list">
              <legend>{{ $t('common.printDestinations') }}</legend>
              <label class="checkbox"
                ><input v-model="preferences.all_printers" type="checkbox" :disabled="busy" />{{
                  $t('common.allPrintersICanModerate')
                }}</label
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
              <legend>{{ $t('common.defaultEventTypes') }}</legend>
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
              {{ $t('common.saveNotificationPreferences') }}
            </button>
          </form>
        </ExpandableContent>
      </template>
      <TransitionGroup
        name="notice"
        tag="ul"
        class="device-list"
        :aria-label="$t('accountPush.notificationDevices')"
      >
        <li v-for="device in settings.devices" :key="device.id" class="row wrap motion-reveal">
          <span class="device-name"
            >{{ device.name
            }}<small
              >{{ device.id === currentId ? $t('uiMessages.thisDevice') : ''
              }}{{
                !device.enabled
                  ? device.id === currentId
                    ? ' · Inactive'
                    : $t('uiMessages.inactive')
                  : ''
              }}</small
            ></span
          >
          <button
            class="danger-text"
            :disabled="busy"
            :aria-label="$t('uiDetails.remove', { value1: String(device.name) })"
            @click="remove(device)"
          >
            {{ $t('common.remove') }}
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
