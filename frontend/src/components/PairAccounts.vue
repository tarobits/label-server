<script setup lang="ts">
import { locale } from '../shared/i18n'

import { computed, onUnmounted, ref, watch } from 'vue'
import { api, errorMessage } from '../shared/api'
import { useAuthStore } from '../auth/auth'
import { useLiveRefresh } from '../shared/live'
import { date, metres } from '../shared/workspace'
import type { UsageAdjustment, UsageUser } from '../shared/types'
import type { PairBalance } from '../shared/resourceAccess'
import AccountAdjustment from './AccountAdjustment.vue'
import AnimatedDetails from './AnimatedDetails.vue'
import AdminDialog from './AdminDialog.vue'
const props = defineProps<{ userId: string; allUsers: boolean; section: string }>()
const auth = useAuthStore()
const editing = ref(false)
const saving = ref(false)
function openAdjustment(event: MouseEvent) {
  ;(event.currentTarget as HTMLElement).focus()
  editing.value = true
}
interface Charge {
  batch_id: string
  requester_id: string
  requester_name: string
  recipient_name: string | null
  recipient_assigned_at: number | null
  cartridge_name: string
  created_at: number
  actual_cost: string | null
  charged: string | null
  currency: string
  consumed_mm: number | null
  own_cartridge: boolean
}
type GroupBalance = PairBalance & { group_account_id?: string }
const groupBalances = ref<GroupBalance[]>([]),
  groupCartridges = ref<(GroupBalance & { cartridge_id: string; cartridge_name: string })[]>([])
const displayedBalances = computed(() => [...balances.value, ...groupBalances.value])
const displayedCartridges = computed(() => [...cartridgeBalances.value, ...groupCartridges.value])
const balances = ref<(GroupBalance & { unallocated_owed?: string })[]>([]),
  cartridgeBalances = ref<(GroupBalance & { cartridge_id: string; cartridge_name: string })[]>([]),
  adjustments = ref<UsageAdjustment[]>([]),
  charges = ref<Charge[]>([]),
  users = ref<UsageUser[]>([])
const error = ref('')
const currentName = computed(
  () =>
    users.value.find((user) => user.user_id === (props.userId || auth.user?.id))?.username ?? '',
)
let revision = 0
onUnmounted(() => {
  revision++
})
const unallocated = computed(() => balances.value.filter((row) => Number(row.unallocated_owed)))
async function refresh() {
  const ticket = ++revision
  try {
    const params = new URLSearchParams()
    if (props.allUsers) params.set('all_users', 'true')
    else if (props.userId) params.set('user_id', props.userId)
    const [result, parties] = await Promise.all([
      api<{
        balances: typeof balances.value
        group_balances: typeof groupBalances.value
        group_cartridge_balances: typeof groupCartridges.value
        cartridge_balances: typeof cartridgeBalances.value
        adjustments: UsageAdjustment[]
        charges: Charge[]
      }>(`/accounts?${params}`),
      api<UsageUser[]>('/accounts/parties'),
    ])
    if (ticket !== revision) return
    balances.value = result.balances
    groupBalances.value = result.group_balances ?? []
    groupCartridges.value = result.group_cartridge_balances ?? []
    cartridgeBalances.value = result.cartridge_balances
    adjustments.value = result.adjustments
    charges.value = result.charges
    users.value = parties
    error.value = ''
  } catch (e) {
    if (ticket === revision) {
      error.value = errorMessage(e)
      balances.value = []
      groupBalances.value = []
      groupCartridges.value = []
      cartridgeBalances.value = []
      charges.value = []
      adjustments.value = []
    }
  }
}
watch(
  () => [props.userId, props.allUsers, auth.user?.id],
  () => {
    editing.value = false
    balances.value = []
    groupBalances.value = []
    groupCartridges.value = []
    cartridgeBalances.value = []
    adjustments.value = []
    charges.value = []
    void refresh()
  },
  { immediate: true },
)
useLiveRefresh(refresh)
const money = (value: string, currency: string) =>
  new Intl.NumberFormat(locale.value, {
    style: 'currency',
    currency,
    maximumFractionDigits: 6,
  }).format(Number(value))
</script>
<template>
  <div class="pair-accounts">
    <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
    <section v-show="section === 'balances'" class="usage-accounts">
      <h2>
        {{
          allUsers
            ? $t('uiMessages.accountBalances')
            : $t('uiDetails.balances', { value1: String(currentName) })
        }}
      </h2>
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>{{ $t('common.payer') }}</th>
              <th>{{ $t('common.recipient') }}</th>
              <th>{{ $t('common.owed') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="balance in displayedBalances"
              :key="`${balance.group_account_id ? 'group' : 'user'}:${balance.requester_id}:${balance.recipient_id}:${balance.cartridge_id ?? ''}:${balance.currency}`"
            >
              <td>
                <RouterLink
                  v-if="balance.group_account_id"
                  :to="{
                    path: '/group-accounts',
                    query: { account: balance.group_account_id, section: 'balances' },
                  }"
                  >{{ balance.requester_name }}</RouterLink
                ><RouterLink
                  v-else-if="allUsers"
                  :to="{
                    path: '/usage',
                    query: { user: balance.requester_id, section: 'balances' },
                  }"
                  >{{ balance.requester_name }}</RouterLink
                ><template v-else>{{ balance.requester_name }}</template>
                <small v-if="balance.group_account_id">{{ $t('common.groupAccount') }}</small>
              </td>
              <td>
                <RouterLink
                  v-if="allUsers && balance.recipient_id"
                  :to="{
                    path: '/usage',
                    query: { user: balance.recipient_id, section: 'balances' },
                  }"
                  >{{ balance.recipient_name }}</RouterLink
                ><template v-else>{{ balance.recipient_name }}</template>
              </td>
              <td class="account-balance">{{ money(balance.owed, balance.currency) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!displayedBalances.length && !error">{{ $t('pairAccounts.noDebts') }}</p>
    </section>
    <section v-show="section === 'cartridges'" class="cartridge-balances">
      <h2>{{ $t('pairAccounts.debtsByCartridge') }}</h2>
      <p v-if="!displayedCartridges.length && !unallocated.length && !error" class="empty">
        {{ $t('pairAccounts.noCartridgeDebts') }}
      </p>
      <template v-else>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>{{ $t('common.payer') }}</th>
                <th>{{ $t('common.recipient') }}</th>
                <th>{{ $t('common.cartridge') }}</th>
                <th>{{ $t('common.owed') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="balance in displayedCartridges"
                :key="`${balance.group_account_id ? 'group' : 'user'}:${balance.requester_id}:${balance.recipient_id}:${balance.cartridge_id}:${balance.currency}`"
              >
                <td>
                  <RouterLink
                    v-if="balance.group_account_id"
                    :to="{
                      path: '/group-accounts',
                      query: { account: balance.group_account_id, section: 'balances' },
                    }"
                    >{{ balance.requester_name }}</RouterLink
                  >
                  <template v-else>{{ balance.requester_name }}</template>
                  <small v-if="balance.group_account_id">{{ $t('common.groupAccount') }}</small>
                </td>
                <td>{{ balance.recipient_name ?? balance.cartridge_name }}</td>
                <td>{{ balance.cartridge_name }}</td>
                <td>{{ money(balance.owed, balance.currency) }}</td>
              </tr>
              <tr
                v-for="balance in unallocated"
                :key="`unallocated:${balance.requester_id}:${balance.recipient_id}:${balance.currency}`"
              >
                <td>{{ balance.requester_name }}</td>
                <td>{{ balance.recipient_name }}</td>
                <td>
                  {{ $t('common.unallocated') }}
                  {{ Number(balance.unallocated_owed) < 0 ? 'credit' : 'adjustment' }}
                </td>
                <td>{{ money(balance.unallocated_owed!, balance.currency) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </section>
    <section v-show="section === 'payments'">
      <header class="account-section-heading">
        <h2>{{ $t('pairAccounts.repaymentsCorrections') }}</h2>
        <button class="primary" @click="openAdjustment">
          {{ $t('pairAccounts.recordRepaymentOrCorrection') }}
        </button>
      </header>
      <p v-if="!adjustments.length && !error" class="empty">
        {{ $t('pairAccounts.noRepaymentsOrCorrections') }}
      </p>
      <article
        v-for="adjustment in adjustments"
        :key="adjustment.id"
        class="list-row adjustment-entry"
      >
        <div class="grow">
          <strong>{{ adjustment.note }}</strong
          ><small
            >{{ adjustment.username }} → {{ adjustment.recipient_name }} ·
            {{ date(adjustment.created_at) }} · {{ adjustment.actor_name }}</small
          >
        </div>
        <strong>{{ money(String(adjustment.amount_minor / 100), adjustment.currency) }}</strong>
      </article>
    </section>
    <section v-show="section === 'charges'">
      <h2>{{ $t('pairAccounts.chargesReceivables') }}</h2>
      <p v-if="!charges.length && !error" class="empty">{{ $t('common.noChargesYet') }}</p>
      <AnimatedDetails
        v-for="charge in charges"
        :key="`${charge.batch_id}:${charge.requester_id}`"
        class="account-charge"
        ><template #summary
          >{{ charge.requester_name }} · {{ charge.cartridge_name }} ·
          {{ date(charge.created_at) }}</template
        >
        <dl>
          <dt>
            {{
              charge.recipient_assigned_at
                ? $t('uiMessages.assignedRecipient')
                : $t('common.recipient')
            }}
          </dt>
          <dd>{{ charge.recipient_name ?? charge.cartridge_name }}</dd>
          <dt>{{ $t('common.tapeUsed') }}</dt>
          <dd>
            {{
              charge.consumed_mm === null ? $t('uiMessages.pending') : metres(charge.consumed_mm)
            }}
          </dd>
          <dt>{{ $t('pairAccounts.actualCost') }}</dt>
          <dd>
            {{
              charge.actual_cost === null
                ? $t('uiMessages.pendingOrUnpriced')
                : money(charge.actual_cost, charge.currency)
            }}
          </dd>
          <dt>{{ $t('common.charged') }}</dt>
          <dd>
            {{
              charge.own_cartridge
                ? $t('uiMessages.ownCartridgeNoDebt')
                : charge.charged === null
                  ? $t('uiMessages.pendingOrUnpriced')
                  : money(charge.charged, charge.currency)
            }}
          </dd>
        </dl>
      </AnimatedDetails>
    </section>
    <AdminDialog
      :open="editing"
      :title="$t('pairAccounts.recordRepaymentOrCorrection')"
      :busy="saving"
      @close="editing = false"
    >
      <AccountAdjustment
        class="account-adjustment"
        :users="users"
        :user-id="userId"
        @saved="refresh"
        @busy="saving = $event"
      />
    </AdminDialog>
  </div>
</template>
<style scoped>
.pair-accounts {
  min-width: 0;
}
.pair-accounts h2 {
  font-size: 20px;
  margin: 0 0 24px;
}
.account-section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 24px;
}
.account-section-heading h2 {
  margin: 0;
}
.adjustment-entry .grow {
  min-width: 0;
  overflow-wrap: anywhere;
}
.account-charge {
  padding: 0.75rem 0;
  border-bottom: 1px solid var(--line);
}
.account-charge:last-child {
  border-bottom: 0;
}
.account-balance {
  font-variant-numeric: tabular-nums;
}
.account-charge dl {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 0.6rem;
}
.account-charge dd {
  margin: 0;
  overflow-wrap: anywhere;
}
</style>
