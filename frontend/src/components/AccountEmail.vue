<script setup lang="ts">
import { computed, nextTick, onMounted, onBeforeUnmount, reactive, ref, useId } from 'vue'
import { api, errorMessage } from '../shared/api'
import { useAuthStore } from '../auth/auth'
import { useWorkspaceStore } from '../shared/workspace'
import { vValidateForm } from '../shared/formValidation'
import ExpandableContent from './ExpandableContent.vue'
import PrinterNotificationKinds from './PrinterNotificationKinds.vue'
import {
  scopedPrinters,
  selectedPrinterKinds,
  type PrinterKinds,
} from '../notifications/notificationPreferences'

const auth = useAuthStore(),
  w = useWorkspaceStore()
interface Subscription {
  enabled: boolean
  all_printers: boolean
  destination_ids: string[]
  kinds: string[]
  printer_kinds: PrinterKinds
}
interface EmailSettings {
  available: boolean
  email: string | null
  pending_email: string | null
  subscription: Subscription
}
const settings = ref<EmailSettings | null>(null)
const emailInput = ref<HTMLInputElement | null>(null)
const editButton = ref<HTMLButtonElement | null>(null)
const emailFormId = useId()
const email = ref(''),
  password = ref(''),
  editing = ref(false)
const busy = ref(false),
  error = ref(''),
  success = ref('')
const subscription = reactive<Subscription>({
  enabled: false,
  all_printers: false,
  destination_ids: [],
  kinds: ['general'],
  printer_kinds: {},
})
const destinations = computed(() =>
  w.destinations.filter((destination) => auth.printer(destination.id, 'view_activity')),
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
  subscription.destination_ids.filter((id) =>
    destinations.value.some((destination) => destination.id === id),
  ),
)
const selectedKinds = computed(() =>
  subscription.kinds.filter((value) =>
    kinds.value.some(
      (kind) =>
        kind.value === value &&
        (!kind.scoped || subscription.all_printers || selectedDestinations.value.length > 0),
    ),
  ),
)
const customPrinters = computed(() =>
  scopedPrinters(destinations.value, subscription.all_printers, selectedDestinations.value),
)
const printerKinds = computed(() =>
  selectedPrinterKinds(subscription.printer_kinds, customPrinters.value),
)
const hasEvents = computed(
  () =>
    selectedKinds.value.length > 0 ||
    Object.values(printerKinds.value).some((kinds) => kinds.length > 0),
)
async function load() {
  settings.value = await api<EmailSettings>('/auth/email')
  Object.assign(subscription, { printer_kinds: {} }, settings.value.subscription)
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
  } finally {
    busy.value = false
  }
}
async function edit() {
  email.value = settings.value?.pending_email || settings.value?.email || ''
  password.value = ''
  editing.value = true
  error.value = ''
  success.value = ''
  await nextTick()
  emailInput.value?.focus()
}
function cancel() {
  editing.value = false
  password.value = ''
  editButton.value?.focus()
}
async function saveEmail(remove = false) {
  await perform(async () => {
    const result = await api<{ message: string }>('/auth/email', 'PUT', {
      email: remove ? null : email.value,
      current_password: password.value,
    })
    cancel()
    return result.message
  })
  if (!editing.value) {
    await nextTick()
    editButton.value?.focus()
  }
}
async function saveSubscription() {
  await perform(async () => {
    await api('/auth/email/subscription', 'PUT', {
      ...subscription,
      destination_ids: subscription.all_printers ? [] : selectedDestinations.value,
      kinds: hasEvents.value ? selectedKinds.value : ['general'],
      printer_kinds: printerKinds.value,
    })
    return 'Email notifications saved.'
  })
}
onMounted(() => {
  void load().catch((issue) => {
    error.value = errorMessage(issue)
  })
})
onBeforeUnmount(() => {
  password.value = ''
})
</script>

<template>
  <div class="account-email">
    <h2>{{ $t('accountEmail.accountEmail') }}</h2>
    <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
    <p v-if="success" class="alert success" role="status">{{ success }}</p>
    <p v-if="!settings && !error" class="help" role="status">
      {{ $t('accountEmail.loadingEmailSettings') }}
    </p>
    <template v-if="settings">
      <p v-if="!settings.available" class="alert warning">
        {{ $t('accountEmail.emailDeliveryHasNotBeenConfiguredByYourAdministrator') }}
      </p>
      <div class="row wrap">
        <span>{{ settings.email || 'No verified email address' }}</span>
        <button
          ref="editButton"
          :aria-expanded="editing"
          :aria-controls="emailFormId"
          :disabled="busy || (!settings.available && !settings.email && !settings.pending_email)"
          @click="edit"
        >
          {{ settings.email ? 'Change email' : 'Add email' }}
        </button>
      </div>
      <p v-if="settings.pending_email" class="help">
        {{ $t('common.verificationPending') }} {{ settings.pending_email }}
      </p>
      <ExpandableContent :id="emailFormId" :open="editing">
        <form v-validate-form class="form-stack email-form" @submit.prevent="saveEmail()">
          <label
            >{{ $t('accountEmail.emailAddress')
            }}<input
              ref="emailInput"
              v-model="email"
              type="email"
              autocomplete="email"
              required
              maxlength="254"
              :disabled="busy"
          /></label>
          <label
            >{{ $t('accountEmail.accountPassword')
            }}<input
              v-model="password"
              type="password"
              autocomplete="current-password"
              required
              maxlength="256"
              :disabled="busy"
          /></label>
          <div class="row wrap">
            <button class="primary" :disabled="busy || !settings.available">
              {{ $t('common.sendVerificationLink') }}
            </button>
            <button type="button" :disabled="busy" @click="cancel">
              {{ $t('common.cancel') }}
            </button>
            <button
              v-if="settings.email || settings.pending_email"
              type="button"
              class="danger-text"
              :disabled="busy || !password"
              @click="saveEmail(true)"
            >
              {{ $t('accountEmail.removeEmail') }}
            </button>
          </div>
        </form>
      </ExpandableContent>
      <h2 class="notifications-heading">{{ $t('accountEmail.emailNotifications') }}</h2>
      <form v-validate-form class="form-stack" @submit.prevent="saveSubscription">
        <label class="checkbox"
          ><input
            v-model="subscription.enabled"
            type="checkbox"
            :disabled="busy || !settings.email || (!settings.available && !subscription.enabled)"
          />{{ $t('accountEmail.receiveEmailNotifications') }}</label
        >
        <ExpandableContent :open="subscription.enabled">
          <div class="form-stack subscription-options">
            <fieldset v-if="destinations.length" class="choice-list">
              <legend>{{ $t('common.printDestinations') }}</legend>
              <label class="checkbox"
                ><input v-model="subscription.all_printers" type="checkbox" :disabled="busy" />{{
                  $t('common.allPrintersICanModerate')
                }}</label
              >
              <label v-for="destination in destinations" :key="destination.id" class="checkbox"
                ><input
                  v-model="subscription.destination_ids"
                  :value="destination.id"
                  type="checkbox"
                  :disabled="busy || subscription.all_printers"
                />{{ destination.name }}</label
              >
            </fieldset>
            <fieldset class="choice-list">
              <legend>{{ $t('common.defaultEventTypes') }}</legend>
              <label v-for="kind in kinds" :key="kind.value" class="checkbox"
                ><input
                  v-model="subscription.kinds"
                  :value="kind.value"
                  type="checkbox"
                  :disabled="
                    busy ||
                    (kind.scoped &&
                      !subscription.all_printers &&
                      !subscription.destination_ids.length)
                  "
                />{{ kind.label }}</label
              >
            </fieldset>
            <PrinterNotificationKinds
              v-model="subscription.printer_kinds"
              :printers="customPrinters"
              :defaults="selectedKinds"
              :disabled="busy"
            />
          </div>
        </ExpandableContent>
        <button
          class="primary"
          :disabled="
            busy || !settings.email || (subscription.enabled && (!settings.available || !hasEvents))
          "
        >
          {{ $t('common.saveEmailNotifications') }}
        </button>
      </form>
    </template>
  </div>
</template>

<style scoped>
.account-email h2 {
  margin-bottom: 24px;
}
.email-form {
  max-width: 440px;
  padding-top: 20px;
}
.notifications-heading {
  margin-top: 32px;
}
.subscription-options {
  padding-block: 16px;
}
.account-email > .row span {
  overflow-wrap: anywhere;
  min-width: 0;
}
.account-email > .row button {
  flex-shrink: 0;
}
.account-email > .help {
  margin-top: 8px;
  overflow-wrap: anywhere;
}
</style>
