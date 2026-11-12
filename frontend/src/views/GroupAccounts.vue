<script setup lang="ts">
import { locale, t } from '../shared/i18n'

import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errorMessage } from '../shared/api'
import { useAuthStore } from '../auth/auth'
import { date } from '../shared/workspace'
import { randomUUID } from '../shared/uuid'
import { useLiveRefresh } from '../shared/live'
import { freezeLeavingItem } from '../shared/collectionMotion'
import AdminDialog from '../components/AdminDialog.vue'
import MotionTrack from '../components/MotionTrack.vue'
import JobPreview from '../components/JobPreview.vue'
import ExpandableContent from '../components/ExpandableContent.vue'
import MotionSurface from '../components/MotionSurface.vue'
import GroupPrintDetails from '../components/GroupPrintDetails.vue'

interface Account {
  id: string
  name: string
  archived: boolean
  permissions: string[]
}
interface Charge {
  id: string
  requester_name: string
  recipient_id: string | null
  recipient_name: string | null
  cartridge_id: string
  cartridge_name?: string
  currency: string
  amount_micros: string
  outstanding_micros: number
  kind: string
  created_at: number
  source_kind: string
  prints_url: string | null
}
interface FundingRequest {
  id: string
  requester_name: string
  kind: string
  mode: string
  status: string
  reason: string | null
  created_at: number
  can_decide: boolean
  can_resolve: boolean
  prints_url: string | null
  preview: { url: string; width_mm: number; length_mm: number; copies: number } | null
  details: {
    amount_micros?: number
    currency?: string
    pricing?: { quotes?: Record<string, number> }
    note?: string
  }
}
interface Details extends Account {
  charges: Charge[]
  requests: FundingRequest[]
}
interface History {
  labels: { job_id: string; available_micros: number; pending: boolean }[]
  previews: {
    job_id: string
    copy_id: string
    text: string
    url: string
    width_mm: number
    length_mm: number
    copies: number
  }[]
  batch_id: string
  cartridge_id: string
  currency: string
  available_micros: number
  paid_micros: number
  created_at: number
  needs_payment_allocation: boolean
}
interface Grant {
  principal_kind: 'user' | 'role'
  principal_id: string
  permission: string
  effect: string
}
interface Access {
  grants: Grant[]
  users: { id: string; name: string }[]
  roles: { id: string; name: string }[]
  permissions: Record<string, string>
}
const route = useRoute(),
  router = useRouter(),
  auth = useAuthStore()
const accounts = ref<Account[]>([]),
  selected = ref(typeof route.query.account === 'string' ? route.query.account : '')
const details = ref<Details | null>(null),
  access = ref<Access | null>(null),
  history = ref<History[]>([])
const events = ref<
  {
    id: string
    actor_name: string
    action: string
    created_at: number
    details: Record<string, unknown>
  }[]
>([])
const busy = ref(false),
  error = ref(''),
  success = ref(''),
  canCreate = ref(false),
  createName = ref(''),
  editName = ref('')
const editArchived = ref(false)
const reasons = reactive<Record<string, string>>({})
const payment = reactive({
  recipient_id: '',
  currency: 'EUR',
  amount: '',
  note: '',
  cartridge_ids: [] as string[],
})
const grant = reactive({
  principal_kind: 'user' as 'user' | 'role',
  principal_id: '',
  permission: 'view',
  effect: 'allow',
})
const rights = computed(() => new Set(details.value?.permissions ?? []))
const createOpen = ref(false)
const historyOpen = ref(false)
const selections = reactive<Record<string, string[]>>({})
const chargeId = ref('')
const chargeItem = computed(() => details.value?.charges.find((c) => c.id === chargeId.value))
function openCharge(item: Charge, event: MouseEvent) {
  ;(event.currentTarget as HTMLElement).focus()
  chargeId.value = item.id
}
function openHistory(event: MouseEvent) {
  ;(event.currentTarget as HTMLElement).focus()
  historyOpen.value = true
  void loadHistory()
}
function selectedCost(item: History) {
  return item.labels
    .filter((label) => selections[item.batch_id]?.includes(label.job_id))
    .reduce((sum, label) => sum + label.available_micros, 0)
}
function openCreate(event: MouseEvent) {
  ;(event.currentTarget as HTMLElement).focus()
  error.value = ''
  createOpen.value = true
}
function closeCreate() {
  createOpen.value = false
  error.value = ''
}
const reviewId = ref(typeof route.query.request === 'string' ? route.query.request : '')
const reviewItem = computed(() =>
  details.value?.requests.find((item) => item.id === reviewId.value),
)
function openRequest(item: FundingRequest, event: MouseEvent) {
  ;(event.currentTarget as HTMLElement).focus()
  error.value = ''
  reviewId.value = item.id
}
function closeRequest() {
  reviewId.value = ''
  error.value = ''
  if (route.query.request) void router.replace({ query: { ...route.query, request: undefined } })
}
watch(
  () => route.query.request,
  (value) => {
    reviewId.value = typeof value === 'string' ? value : ''
  },
)
const canRecordPayment = computed(
  () =>
    rights.value.has('record_payments') ||
    auth.can('usage.edit_accounts') ||
    payees.value.some(([id]) => id === auth.user?.id),
)
const sections = computed(() => [
  {
    id: 'requests',
    get title() {
      return t('groupAccounts.requests')
    },
  },
  {
    id: 'balances',
    get title() {
      return t('groupAccounts.balancesCharges')
    },
  },
  ...(canRecordPayment.value
    ? [
        {
          id: 'payments',
          get title() {
            return t('groupAccounts.payments')
          },
        },
      ]
    : []),
  {
    id: 'history',
    get title() {
      return t('groupAccounts.requestHistory')
    },
  },
  ...(rights.value.has('edit')
    ? [
        {
          id: 'settings',
          get title() {
            return t('navigation.account')
          },
        },
      ]
    : []),
  ...(rights.value.has('manage_access')
    ? [
        {
          id: 'permissions',
          get title() {
            return t('common.permissions')
          },
        },
      ]
    : []),
  ...(rights.value.has('view_audit')
    ? [
        {
          id: 'audit',
          get title() {
            return t('common.auditLog')
          },
        },
      ]
    : []),
])
const section = computed(
  () => sections.value.find((item) => item.id === route.query.section) ?? sections.value[0]!,
)
const navigationGroups = computed(() =>
  [
    {
      get title() {
        return t('common.funding')
      },
      sections: sections.value.filter(
        (item) => !['settings', 'permissions', 'audit'].includes(item.id),
      ),
    },
    {
      get title() {
        return t('resourceAccess.manage')
      },
      sections: sections.value.filter((item) =>
        ['settings', 'permissions', 'audit'].includes(item.id),
      ),
    },
  ].filter((group) => group.sections.length),
)
function navigate(id: string) {
  void router.replace({ query: { ...route.query, section: id, request: undefined } })
}
async function loadHistory() {
  await perform(async () => {
    history.value = (await api<History[]>('/accounts/groups/history')).filter(
      (item) => item.available_micros > 0,
    )
    for (const item of history.value) selections[item.batch_id] ??= []
  }, '')
}
async function loadEvents() {
  await perform(async () => {
    events.value = await api(`/accounts/groups/${selected.value}/audit`)
  }, '')
}
const balances = computed(() => {
  const totals = new Map<string, { name: string; currency: string; amount: number }>()
  for (const charge of details.value?.charges ?? []) {
    const key = `${charge.recipient_id ?? charge.cartridge_id}:${charge.currency}`
    const row = totals.get(key) ?? {
      name: charge.recipient_name ?? charge.cartridge_name ?? 'Unowned cartridge',
      currency: charge.currency,
      amount: 0,
    }
    row.amount += charge.outstanding_micros
    totals.set(key, row)
  }
  return [...totals.values()].filter((row) => row.amount !== 0)
})
const pending = computed(
  () => details.value?.requests.filter((r) => r.status === 'pending' || r.can_resolve) ?? [],
)
const completed = computed(
  () => details.value?.requests.filter((r) => r.status !== 'pending' && !r.can_resolve) ?? [],
)
const payees = computed(() => [
  ...new Map(
    (details.value?.charges ?? [])
      .filter((c) => c.recipient_id && c.outstanding_micros > 0)
      .map((c) => [c.recipient_id!, c.recipient_name ?? 'Former member']),
  ).entries(),
])
const payable = computed(() =>
  (details.value?.charges ?? []).filter(
    (c) =>
      c.recipient_id === payment.recipient_id &&
      c.currency === payment.currency &&
      c.outstanding_micros > 0,
  ),
)
const cartridges = computed(() => [
  ...new Map(
    payable.value.map((c) => [c.cartridge_id, c.cartridge_name ?? c.cartridge_id]),
  ).entries(),
])
const currencies = computed(() => [
  ...new Set(
    (details.value?.charges ?? [])
      .filter((c) => c.recipient_id === payment.recipient_id)
      .map((c) => c.currency),
  ),
])
const money = (micros: number | string, currency: string) =>
  new Intl.NumberFormat(locale.value, {
    style: 'currency',
    currency,
    maximumFractionDigits: 6,
  }).format(Number(micros) / 1000000)
const kind = (value: string) =>
  ({
    job: 'Print funding',
    history: 'Historical transfer',
    payment: 'Payment confirmation',
    transfer: 'Transferred debt',
    reimbursement: 'Reimbursement',
    supply: 'Cartridge use',
  })[value] ?? value
const obligation = (value: string) =>
  ({ transfer: 'Cartridge cost', reimbursement: 'Reimbursement', supply: 'Own cartridge' })[
    value
  ] ?? value
let generation = 0
async function load() {
  const ticket = ++generation
  const result = await api<{ accounts: Account[]; can_create: boolean }>('/accounts/groups')
  if (ticket !== generation) return
  accounts.value = result.accounts
  canCreate.value = result.can_create
  if (!selected.value && accounts.value.length) {
    selected.value = accounts.value[0]!.id
    return
  }
  if (!selected.value) return
  const value = await api<Details>(`/accounts/groups/${selected.value}`)
  if (ticket !== generation) return
  details.value = value
}
async function refresh() {
  if (busy.value) return
  try {
    await load()
  } catch (e) {
    error.value = errorMessage(e)
    details.value = null
    access.value = null
    events.value = []
  }
}
async function perform(task: () => Promise<void>, message: string) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  success.value = ''
  try {
    await task()
    await load()
    success.value = message
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}
watch(selected, async (value) => {
  generation++
  details.value = null
  access.value = null
  events.value = []
  history.value = []
  historyOpen.value = false
  chargeId.value = ''
  payment.recipient_id = ''
  payment.amount = ''
  payment.note = ''
  grant.principal_id = ''
  await router.replace({
    query: {
      ...route.query,
      account: value || undefined,
      request: route.query.account === value ? route.query.request : undefined,
    },
  })
  await refresh()
})
watch(
  () => route.query.account,
  (value) => {
    if (typeof value === 'string' && value !== selected.value) selected.value = value
  },
)
watch(
  () => details.value?.name,
  (value) => {
    editName.value = value ?? ''
  },
)
watch(
  () => details.value?.archived,
  (value) => {
    editArchived.value = value ?? false
  },
)
watch(
  () => payment.recipient_id,
  () => {
    payment.cartridge_ids = []
    payment.currency = currencies.value[0] ?? 'EUR'
  },
)
watch(
  () => payment.currency,
  () => {
    payment.cartridge_ids = []
  },
)
watch(
  () => grant.principal_kind,
  () => {
    grant.principal_id = ''
  },
)
watch([() => section.value.id, () => details.value?.id], ([tab, account]) => {
  if (!account) return
  if (tab === 'permissions') void loadAccess()
  if (tab === 'audit') void loadEvents()
})
onMounted(refresh)
useLiveRefresh(refresh)
async function create() {
  await perform(async () => {
    const account = await api<Account>('/accounts/groups', 'POST', { name: createName.value })
    await router.replace({ query: { account: account.id, section: 'requests' } })
    selected.value = account.id
    createName.value = ''
    createOpen.value = false
  }, 'Group account created.')
}
async function decide(item: FundingRequest, approve: boolean) {
  await perform(
    async () => {
      await api(`/accounts/groups/requests/${item.id}/decision`, 'POST', {
        approve,
        reason: reasons[item.id] ?? '',
      })
      closeRequest()
    },
    approve ? 'Request approved.' : 'Request rejected.',
  )
}
async function resolve(item: FundingRequest, cancel: boolean) {
  await perform(
    async () => {
      await api(`/accounts/groups/requests/${item.id}/resolve`, 'POST', { cancel })
      closeRequest()
    },
    cancel ? 'Queued labels cancelled.' : 'Personal payment selected.',
  )
}
async function loadAccess() {
  await perform(async () => {
    access.value = await api<Access>(`/accounts/groups/${selected.value}/access`)
  }, '')
}
async function saveGrant() {
  await perform(async () => {
    await api(`/accounts/groups/${selected.value}/access`, 'PUT', grant)
    if (
      grant.principal_kind === 'user' &&
      grant.principal_id === auth.user?.id &&
      grant.permission === 'manage_access' &&
      grant.effect !== 'allow'
    )
      access.value = null
    else access.value = await api<Access>(`/accounts/groups/${selected.value}/access`)
  }, 'Permissions saved.')
}
let paymentKey = '',
  paymentSignature = ''
async function reportPayment() {
  await perform(async () => {
    const amount = payment.amount.trim()
    if (!/^\d+(\.\d{1,6})?$/.test(amount))
      throw new Error('Enter an amount with up to six decimal places.')
    const micros =
      Number(amount.split('.')[0]) * 1000000 + Number((amount.split('.')[1] ?? '').padEnd(6, '0'))
    const body = {
      recipient_id: payment.recipient_id,
      currency: payment.currency,
      amount_micros: micros,
      note: payment.note,
      cartridge_ids: payment.cartridge_ids.length ? payment.cartridge_ids : null,
    }
    const signature = JSON.stringify([selected.value, body])
    if (signature !== paymentSignature) {
      paymentSignature = signature
      paymentKey = randomUUID()
    }
    await api(`/accounts/groups/${selected.value}/payments`, 'POST', {
      ...body,
      request_id: paymentKey,
    })
    payment.amount = ''
    payment.note = ''
    paymentSignature = ''
  }, 'Payment recorded. Unconfirmed payments remain pending.')
}
const transferKeys = new Map<string, string>()
async function transfer(item: History, direct = false) {
  await perform(
    async () => {
      const jobIds = [...(selections[item.batch_id] ?? [])].sort()
      const key = JSON.stringify([selected.value, item.batch_id, jobIds, direct])
      if (!transferKeys.has(key)) transferKeys.set(key, randomUUID())
      await api(`/accounts/groups/${selected.value}/transfers`, 'POST', {
        batch_id: item.batch_id,
        request_id: transferKeys.get(key),
        direct,
        job_ids: jobIds,
      })
      selections[item.batch_id] = []
      history.value = (await api<History[]>('/accounts/groups/history')).filter(
        (row) => row.available_micros > 0,
      )
    },
    direct ? 'Costs transferred.' : 'Transfer requested.',
  )
}
</script>
<template>
  <div class="group-accounts">
    <ExpandableContent
      :open="(!!error && !createOpen && !reviewId && !historyOpen) || (!!success && !historyOpen)"
    >
      <p v-if="error && !createOpen && !reviewId && !historyOpen" class="alert danger" role="alert">
        {{ error }}
      </p>
      <p v-else-if="success" class="alert success" role="status">{{ success }}</p>
    </ExpandableContent>
    <header class="account-toolbar">
      <label v-if="accounts.length"
        >{{ $t('common.groupAccount')
        }}<select v-model="selected" :disabled="busy">
          <option v-for="account in accounts" :key="account.id" :value="account.id">
            {{ account.name }}{{ account.archived ? ' (archived)' : '' }}
          </option>
        </select></label
      >
      <p v-else class="muted">{{ $t('groupAccounts.noGroupAccountsAvailable') }}</p>
      <button
        v-if="rights.has('request_transfer') && !details?.archived"
        class="secondary"
        :disabled="busy"
        @click="openHistory"
      >
        {{ $t('common.transferPreviousPrintCosts') }}
      </button>
      <button v-if="canCreate" class="primary" :disabled="busy" @click="openCreate">
        {{ $t('groupAccounts.createGroupAccount') }}
      </button>
    </header>
    <div v-if="details" class="administration-layout">
      <MotionTrack
        tag="nav"
        class="administration-nav"
        :identity="section.id"
        selector="button.active"
        :aria-label="$t('groupAccounts.groupFundingSections')"
      >
        <div v-for="group in navigationGroups" :key="group.title" class="administration-nav-group">
          <h2>{{ group.title }}</h2>
          <button
            v-for="item in group.sections"
            :key="item.id"
            :class="{ active: section.id === item.id }"
            :aria-current="section.id === item.id ? 'page' : undefined"
            :disabled="busy"
            @click="navigate(item.id)"
          >
            {{ item.title
            }}<span v-if="item.id === 'requests' && pending.length" class="section-count">{{
              pending.length
            }}</span>
          </button>
        </div>
      </MotionTrack>
      <label class="administration-mobile-nav"
        ><span class="sr-only">{{ $t('groupAccounts.groupFundingSection') }}</span
        ><select
          :value="section.id"
          :disabled="busy"
          @change="navigate(($event.target as HTMLSelectElement).value)"
        >
          <optgroup v-for="group in navigationGroups" :key="group.title" :label="group.title">
            <option v-for="item in group.sections" :key="item.id" :value="item.id">
              {{ item.title }}
            </option>
          </optgroup>
        </select></label
      >
      <MotionSurface
        :identity="`${selected}:${section.id}`"
        :order="sections.findIndex((item) => item.id === section.id)"
        class="administration-content"
        :aria-busy="busy"
      >
        <section
          v-show="section.id === 'requests'"
          class="admin-section"
          aria-labelledby="funding-requests"
        >
          <header class="admin-section-heading">
            <h2 id="funding-requests">{{ $t('groupAccounts.requests') }}</h2>
          </header>
          <p v-if="!pending.length" class="empty">
            {{ $t('groupAccounts.noRequestsAwaitingAction') }}
          </p>
          <div v-for="item in pending" :key="item.id" class="admin-record">
            <div>
              <strong>{{ kind(item.kind) }}</strong
              ><small>{{ item.requester_name }} · {{ date(item.created_at) }}</small>
            </div>
            <span class="badge" :class="item.status">{{ item.status }}</span>
            <button
              class="secondary"
              :disabled="busy"
              :aria-label="`${item.can_decide ? 'Review' : $t('common.view')} ${kind(item.kind)} from ${item.requester_name}`"
              @click="openRequest(item, $event)"
            >
              {{ item.can_decide ? 'Review' : $t('common.viewRequest') }}
            </button>
          </div>
        </section>
        <section
          v-show="section.id === 'balances'"
          class="admin-section"
          aria-labelledby="funding-balances"
        >
          <header class="admin-section-heading">
            <h2 id="funding-balances">{{ $t('groupAccounts.balancesCharges') }}</h2>
          </header>
          <h3>{{ $t('groupAccounts.balances') }}</h3>
          <div v-if="balances.length" class="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>{{ $t('common.recipient') }}</th>
                  <th>{{ $t('common.owed') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(balance, index) in balances" :key="index">
                  <td>{{ balance.name }}</td>
                  <td>{{ money(balance.amount, balance.currency) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="muted">{{ $t('groupAccounts.noOutstandingDebts') }}</p>
          <h3>{{ $t('groupAccounts.charges') }}</h3>
          <div v-if="details.charges.length" class="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>{{ $t('common.requester') }}</th>
                  <th>{{ $t('common.recipient') }}</th>
                  <th>{{ $t('common.cartridge') }}</th>
                  <th>{{ $t('common.type') }}</th>
                  <th>{{ $t('common.charged') }}</th>
                  <th>{{ $t('groupAccounts.outstanding') }}</th>
                  <th>
                    <span class="sr-only">{{ $t('groupAccounts.printDetails') }}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="charge in details.charges" :key="charge.id">
                  <td>{{ charge.requester_name }}</td>
                  <td>
                    {{ charge.recipient_name ?? charge.cartridge_name ?? 'Unowned cartridge' }}
                  </td>
                  <td>{{ charge.cartridge_name ?? charge.cartridge_id }}</td>
                  <td>
                    {{ kind(charge.source_kind) }}<small>{{ obligation(charge.kind) }}</small>
                  </td>
                  <td>{{ money(charge.amount_micros, charge.currency) }}</td>
                  <td>{{ money(charge.outstanding_micros, charge.currency) }}</td>
                  <td>
                    <button
                      v-if="charge.prints_url"
                      class="secondary"
                      @click="openCharge(charge, $event)"
                    >
                      {{ $t('common.viewPrints') }}
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="muted">{{ $t('common.noChargesYet') }}</p>
        </section>
        <section
          v-if="canRecordPayment"
          v-show="section.id === 'payments'"
          class="admin-section"
          aria-labelledby="funding-payments"
        >
          <header class="admin-section-heading">
            <h2 id="funding-payments">{{ $t('groupAccounts.payments') }}</h2>
          </header>
          <p v-if="!payees.length" class="empty">{{ $t('groupAccounts.noOutstandingPayments') }}</p>
          <template v-else>
            <form class="account-form" @submit.prevent="reportPayment">
              <label
                >{{ $t('common.recipient')
                }}<select v-model="payment.recipient_id" required>
                  <option disabled value="">{{ $t('groupAccounts.chooseRecipient') }}</option>
                  <option
                    v-for="[id, name] in payees"
                    :key="id"
                    :value="id"
                    :disabled="
                      !rights.has('record_payments') &&
                      !auth.can('usage.edit_accounts') &&
                      id !== auth.user?.id
                    "
                  >
                    {{ name }}
                  </option>
                </select></label
              >
              <div class="row wrap">
                <label
                  >{{ $t('common.amount')
                  }}<input v-model="payment.amount" inputmode="decimal" required /></label
                ><label
                  >{{ $t('common.currency')
                  }}<select v-model="payment.currency">
                    <option v-for="currency in currencies" :key="currency">{{ currency }}</option>
                  </select></label
                >
              </div>
              <fieldset v-if="cartridges.length">
                <legend>{{ $t('groupAccounts.cartridgesAllByDefaultOldestDebtsFirst') }}</legend>
                <label v-for="[id, name] in cartridges" :key="id" class="checkbox"
                  ><input v-model="payment.cartridge_ids" type="checkbox" :value="id" />{{
                    name
                  }}</label
                >
              </fieldset>
              <label
                >{{ $t('groupAccounts.paymentReference')
                }}<input v-model="payment.note" maxlength="500" required
              /></label>
              <p class="muted">
                {{ $t('common.theRecipientOrAnAccountingEditorMustConfirmReceipt') }}
              </p>
              <button :disabled="busy">{{ $t('groupAccounts.recordPayment') }}</button>
            </form>
          </template>
        </section>
        <section
          v-show="section.id === 'history'"
          class="admin-section"
          aria-labelledby="funding-history"
        >
          <header class="admin-section-heading">
            <h2 id="funding-history">{{ $t('groupAccounts.requestHistory') }}</h2>
          </header>
          <p v-if="!completed.length" class="empty">
            {{ $t('groupAccounts.noCompletedRequests') }}
          </p>
          <div v-for="item in completed" :key="item.id" class="request-row">
            <div class="row wrap">
              <strong>{{ kind(item.kind) }}</strong
              ><span
                >{{ item.requester_name }} · {{ item.status }} · {{ date(item.created_at) }}</span
              >
            </div>
            <p v-if="item.reason">{{ item.reason }}</p>
            <button class="secondary" @click="openRequest(item, $event)">
              {{ $t('common.viewRequest') }}
            </button>
          </div>
        </section>
        <section
          v-if="rights.has('edit')"
          v-show="section.id === 'settings'"
          class="admin-section"
          aria-labelledby="funding-settings"
        >
          <header class="admin-section-heading">
            <h2 id="funding-settings">{{ $t('navigation.account') }}</h2>
          </header>
          <form
            class="account-form"
            @submit.prevent="
              perform(async () => {
                await api(`/accounts/groups/${selected}`, 'PUT', {
                  name: editName,
                  archived: editArchived,
                })
              }, 'Account saved.')
            "
          >
            <label
              >{{ $t('common.name') }}<input v-model="editName" required maxlength="100" /></label
            ><label class="checkbox"
              ><input v-model="editArchived" type="checkbox" />{{ $t('common.archived') }}</label
            >
            <p class="muted">
              {{ $t('groupAccounts.archivingPreventsNewFundingAndHoldsGroupFundedLabels') }}
            </p>
            <button :disabled="busy">{{ $t('groupAccounts.saveAccount') }}</button>
          </form>
        </section>
        <section
          v-if="rights.has('manage_access')"
          v-show="section.id === 'permissions'"
          class="admin-section"
          aria-labelledby="funding-permissions"
        >
          <header class="admin-section-heading">
            <h2 id="funding-permissions">{{ $t('common.permissions') }}</h2>
            <button class="secondary" :disabled="busy" @click="loadAccess">
              {{ $t('common.refresh') }}
            </button>
          </header>
          <div class="account-form">
            <ExpandableContent :open="!!access"
              ><div v-if="access" class="account-form">
                <form class="account-form" @submit.prevent="saveGrant">
                  <div class="row wrap">
                    <label
                      >{{ $t('groupAccounts.principal')
                      }}<select v-model="grant.principal_kind">
                        <option value="user">{{ $t('common.user') }}</option>
                        <option value="role">{{ $t('groupAccounts.role') }}</option>
                      </select></label
                    ><label
                      >{{ $t('common.name')
                      }}<select v-model="grant.principal_id" required>
                        <option value="" disabled>{{ $t('common.choose') }}</option>
                        <option
                          v-for="principal in grant.principal_kind === 'user'
                            ? access.users
                            : access.roles"
                          :key="principal.id"
                          :value="principal.id"
                        >
                          {{ principal.name }}
                        </option>
                      </select></label
                    >
                  </div>
                  <label
                    >{{ $t('common.permission')
                    }}<select v-model="grant.permission">
                      <option v-for="(label, key) in access.permissions" :key="key" :value="key">
                        {{ label }}
                      </option>
                    </select></label
                  >
                  <label
                    >{{ $t('groupAccounts.rule')
                    }}<select v-model="grant.effect">
                      <option value="allow">{{ $t('common.allow') }}</option>
                      <option value="deny">{{ $t('common.deny') }}</option>
                      <option value="inherit">{{ $t('common.inherit') }}</option>
                    </select></label
                  ><button :disabled="busy">{{ $t('common.savePermission') }}</button>
                </form>
                <div class="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>{{ $t('groupAccounts.principal') }}</th>
                        <th>{{ $t('common.permission') }}</th>
                        <th>{{ $t('groupAccounts.rule') }}</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr
                        v-for="rule in access.grants"
                        :key="`${rule.principal_kind}:${rule.principal_id}:${rule.permission}`"
                      >
                        <td>
                          {{
                            (rule.principal_kind === 'user' ? access.users : access.roles).find(
                              (p) => p.id === rule.principal_id,
                            )?.name ?? rule.principal_id
                          }}
                        </td>
                        <td>{{ access.permissions[rule.permission] }}</td>
                        <td>{{ rule.effect }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div></ExpandableContent
            >
          </div>
        </section>
        <section
          v-if="rights.has('view_audit')"
          v-show="section.id === 'audit'"
          class="admin-section"
          aria-labelledby="funding-audit"
        >
          <header class="admin-section-heading">
            <h2 id="funding-audit">{{ $t('common.auditLog') }}</h2>
            <button class="secondary" :disabled="busy" @click="loadEvents">
              {{ $t('common.refresh') }}
            </button>
          </header>
          <p v-if="!busy && !events.length" class="empty">{{ $t('groupAccounts.noEventsYet') }}</p>
          <div class="account-form">
            <div v-for="event in events" :key="event.id" class="request-row">
              <div class="row wrap">
                <strong>{{ event.action.replaceAll('.', ' ').replaceAll('_', ' ') }}</strong
                ><span>{{ event.actor_name }} · {{ date(event.created_at) }}</span>
              </div>
              <pre>{{ JSON.stringify(event.details, null, 2) }}</pre>
            </div>
          </div>
        </section>
      </MotionSurface>
    </div>
    <AdminDialog
      :open="historyOpen && rights.has('request_transfer') && !details?.archived"
      :title="$t('groupAccounts.previousPrintCosts')"
      :busy="busy"
      wide
      @close="historyOpen = false"
    >
      <div class="account-form">
        <Transition name="notice"
          ><p v-if="error" class="alert danger" role="alert">{{ error }}</p></Transition
        >
        <Transition name="notice"
          ><p v-if="success" class="alert success" role="status">{{ success }}</p></Transition
        >
        <div class="row wrap">
          <strong>{{ $t('common.transferTo') }} {{ details?.name }}</strong>
          <button class="secondary" :disabled="busy" @click="loadHistory">
            {{ $t('common.refresh') }}
          </button>
        </div>
        <Transition name="panel-expand" mode="out-in">
          <p v-if="busy" key="loading" role="status">{{ $t('groupAccounts.loading') }}</p>
          <p v-else-if="!history.length" key="empty" class="empty">
            {{ $t('groupAccounts.noEligiblePrints') }}
          </p>
        </Transition>
        <TransitionGroup
          name="collection"
          tag="div"
          class="account-form historical-list"
          @before-leave="freezeLeavingItem"
        >
          <article v-for="item in history" :key="item.batch_id" class="historical-charge">
            <div class="row wrap">
              <span>{{ date(item.created_at) }}</span>
              <RouterLink :to="`/batches/${encodeURIComponent(item.batch_id)}`">{{
                $t('common.viewBatch')
              }}</RouterLink>
            </div>
            <div class="historical-previews">
              <div v-for="preview in item.previews" :key="preview.job_id">
                <label class="checkbox">
                  <input
                    v-model="selections[item.batch_id]"
                    type="checkbox"
                    :value="preview.job_id"
                    :disabled="
                      busy ||
                      item.needs_payment_allocation ||
                      !item.labels.find((l) => l.job_id === preview.job_id)?.available_micros ||
                      item.labels.find((l) => l.job_id === preview.job_id)?.pending
                    "
                  />
                  {{ preview.text }}
                </label>
                <JobPreview
                  :job-id="preview.job_id"
                  :text="preview.text"
                  :preview-url="preview.url"
                  :width-mm="preview.width_mm"
                  :length-mm="preview.length_mm"
                />
                <small
                  >{{ preview.copies }} {{ preview.copies === 1 ? 'copy' : $t('common.copies2') }} ·
                  {{
                    money(
                      item.labels.find((l) => l.job_id === preview.job_id)?.available_micros ?? 0,
                      item.currency,
                    )
                  }}
                  <template v-if="item.labels.find((l) => l.job_id === preview.job_id)?.pending">
                    {{ $t('common.transferPending') }}</template
                  >
                </small>
              </div>
            </div>
            <p v-if="item.needs_payment_allocation" class="muted">
              {{ $t('groupAccounts.existingPaymentsNeedCartridgeAllocationFirst') }}
            </p>
            <p v-if="!item.labels.length" class="muted">
              {{ $t('groupAccounts.perLabelCostsAreUnavailableForThisOlderBatch') }}
            </p>
            <div class="row wrap">
              <strong
                >{{ $t('common.selected') }} {{ money(selectedCost(item), item.currency) }}</strong
              >
              <span v-if="item.paid_micros && selectedCost(item)"
                >{{ $t('groupAccounts.alreadyPaid') }}
                {{ money(Math.min(item.paid_micros, selectedCost(item)), item.currency) }}</span
              >
            </div>
            <div class="row wrap">
              <button
                class="secondary"
                :disabled="busy || item.needs_payment_allocation || !selectedCost(item)"
                @click="transfer(item)"
              >
                {{ $t('groupAccounts.requestTransfer') }}
              </button>
              <button
                v-if="rights.has('direct')"
                class="secondary"
                :disabled="busy || item.needs_payment_allocation || !selectedCost(item)"
                @click="transfer(item, true)"
              >
                {{ $t('groupAccounts.chargeGroupDirectly') }}
              </button>
            </div>
          </article>
        </TransitionGroup>
      </div>
    </AdminDialog>
    <AdminDialog
      :open="!!chargeItem"
      :title="$t('groupAccounts.chargeDetails')"
      wide
      @close="chargeId = ''"
    >
      <div v-if="chargeItem" class="account-form">
        <strong>{{ kind(chargeItem.source_kind) }} · {{ obligation(chargeItem.kind) }}</strong>
        <div class="row wrap">
          <span
            >{{ chargeItem.requester_name }} →
            {{ chargeItem.recipient_name ?? 'Unowned cartridge' }}</span
          ><span>{{ date(chargeItem.created_at) }}</span>
        </div>
        <span>{{ chargeItem.cartridge_name ?? chargeItem.cartridge_id }}</span>
        <div class="row wrap">
          <span
            >{{ $t('groupAccounts.charged') }}
            {{ money(chargeItem.amount_micros, chargeItem.currency) }}</span
          ><span
            >{{ $t('groupAccounts.outstanding2') }}
            {{ money(chargeItem.outstanding_micros, chargeItem.currency) }}</span
          >
        </div>
        <GroupPrintDetails v-if="chargeItem.prints_url" :url="chargeItem.prints_url" />
      </div>
    </AdminDialog>
    <AdminDialog
      :open="createOpen"
      :title="$t('groupAccounts.createGroupAccount')"
      :busy="busy"
      @close="closeCreate"
    >
      <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
      <form class="account-form" @submit.prevent="create">
        <label>{{ $t('common.name') }}<input v-model="createName" maxlength="100" required /></label
        ><button class="primary" :disabled="busy">{{ $t('groupAccounts.createAccount') }}</button>
      </form>
    </AdminDialog>
    <AdminDialog
      :open="!!reviewItem"
      :title="reviewItem ? kind(reviewItem.kind) : 'Funding request'"
      :busy="busy"
      @close="closeRequest"
    >
      <div v-if="reviewItem" class="account-form">
        <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
        <GroupPrintDetails
          v-if="reviewItem.prints_url"
          :key="reviewItem.id"
          :url="reviewItem.prints_url"
        />
        <div class="row wrap">
          <strong>{{ reviewItem.requester_name }}</strong
          ><span class="muted">{{ reviewItem.status }} · {{ date(reviewItem.created_at) }}</span>
        </div>
        <div class="row wrap">
          <span
            v-if="reviewItem.details.amount_micros !== undefined && reviewItem.details.currency"
            >{{ money(reviewItem.details.amount_micros, reviewItem.details.currency) }}</span
          >
          <span v-for="(amount, currency) in reviewItem.details.pricing?.quotes" :key="currency"
            >{{ $t('common.upTo') }} {{ money(amount, currency) }}</span
          >
          <span v-if="reviewItem.kind === 'job' && reviewItem.status === 'pending'">{{
            reviewItem.mode === 'wait'
              ? 'Printing waits for approval'
              : 'Requester pays until approved'
          }}</span>
        </div>
        <p v-if="reviewItem.reason">{{ reviewItem.reason }}</p>
        <p v-if="reviewItem.details.note">{{ reviewItem.details.note }}</p>
        <div v-if="reviewItem.can_decide" class="account-form">
          <label
            >{{ $t('groupAccounts.decisionNote')
            }}<input v-model="reasons[reviewItem.id]" maxlength="500"
          /></label>
          <div class="row wrap">
            <button class="primary" :disabled="busy" @click="decide(reviewItem, true)">
              {{ reviewItem.kind === 'payment' ? 'Confirm receipt' : 'Approve' }}</button
            ><button class="secondary" :disabled="busy" @click="decide(reviewItem, false)">
              {{ $t('groupAccounts.reject') }}
            </button>
          </div>
        </div>
        <div v-if="reviewItem.can_resolve" class="row wrap">
          <button class="secondary" :disabled="busy" @click="resolve(reviewItem, false)">
            {{ $t('groupAccounts.payPersonally') }}</button
          ><button class="secondary" :disabled="busy" @click="resolve(reviewItem, true)">
            {{ $t('groupAccounts.cancelQueuedLabels') }}
          </button>
        </div>
      </div>
    </AdminDialog>
  </div>
</template>
<style scoped>
.group-accounts {
  display: grid;
  gap: 24px;
  min-width: 0;
}
.historical-charge {
  display: grid;
  gap: 16px;
  padding-block: 16px;
  border-bottom: 1px solid var(--line);
}
.historical-list {
  position: relative;
}
.historical-previews {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr));
  gap: 16px;
}
.historical-previews > div {
  min-width: 0;
  overflow-wrap: anywhere;
}
.historical-previews strong {
  display: block;
  margin-bottom: 8px;
}
.account-toolbar {
  display: flex;
  align-items: end;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 20px;
  padding-bottom: 24px;
  border-bottom: 1px solid var(--line);
}
.account-toolbar > label {
  width: 360px;
  max-width: 100%;
}
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
.section-count {
  margin-left: auto;
  font-variant-numeric: tabular-nums;
}
.administration-content,
.admin-section {
  min-width: 0;
}
.administration-mobile-nav {
  display: none;
}
.admin-section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 24px;
  flex-wrap: wrap;
}
.admin-section-heading h2 {
  font-size: 20px;
  margin: 0;
}
.admin-section h3 {
  margin: 24px 0 16px;
}
.admin-record {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 16px 0;
  border-bottom: 1px solid var(--line);
}
.admin-record > div {
  min-width: 0;
  flex: 1;
}
.admin-record strong,
.admin-record small {
  overflow-wrap: anywhere;
}
.admin-record small {
  display: block;
  margin-top: 4px;
  color: var(--muted);
}
.admin-record button {
  flex-shrink: 0;
}
.account-form {
  display: grid;
  gap: 16px;
  padding-block: 12px;
}
.account-form > button,
.request-row > button {
  justify-self: start;
}
.admin-section > .account-form {
  max-width: 600px;
}
.account-form label {
  min-width: 0;
}
.account-form .row > label {
  flex: 1 1 160px;
}
.account-form fieldset {
  display: grid;
  gap: 10px;
  min-width: 0;
}
.request-row {
  display: grid;
  gap: 12px;
  padding-block: 16px;
  border-bottom: 1px solid var(--line);
}
.admin-section pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
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
  .admin-record {
    flex-wrap: wrap;
    gap: 12px;
  }
  .admin-record > div {
    flex-basis: calc(100% - 100px);
  }
}
</style>
