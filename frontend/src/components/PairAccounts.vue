<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { api, errorMessage } from '../api'
import { useAuthStore } from '../auth'
import { useLiveRefresh } from '../live'
import { date, metres } from '../workspace'
import type { UsageAdjustment, UsageUser } from '../types'
import type { PairBalance } from '../resourceAccess'
import AccountAdjustment from './AccountAdjustment.vue'
import AnimatedDetails from './AnimatedDetails.vue'
const props = defineProps<{ userId: string; allUsers: boolean }>()
const auth = useAuthStore()
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
const balances = ref<(PairBalance & { unallocated_owed?: string })[]>([]),
  cartridgeBalances = ref<(PairBalance & { cartridge_id: string; cartridge_name: string })[]>([]),
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
        cartridge_balances: typeof cartridgeBalances.value
        adjustments: UsageAdjustment[]
        charges: Charge[]
      }>(`/accounts?${params}`),
      api<UsageUser[]>('/accounts/parties'),
    ])
    if (ticket !== revision) return
    balances.value = result.balances
    cartridgeBalances.value = result.cartridge_balances
    adjustments.value = result.adjustments
    charges.value = result.charges
    users.value = parties
    error.value = ''
  } catch (e) {
    if (ticket === revision) {
      error.value = errorMessage(e)
      balances.value = []
      cartridgeBalances.value = []
      charges.value = []
      adjustments.value = []
    }
  }
}
watch(
  () => [props.userId, props.allUsers, auth.user?.id],
  () => {
    balances.value = []
    cartridgeBalances.value = []
    adjustments.value = []
    charges.value = []
    void refresh()
  },
  { immediate: true },
)
useLiveRefresh(refresh)
const money = (value: string, currency: string) =>
  new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency,
    maximumFractionDigits: 6,
  }).format(Number(value))
</script>
<template>
  <section class="panel usage-accounts">
    <h2>{{ allUsers ? 'Account balances' : `Balances for ${currentName}` }}</h2>
    <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
    <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Payer</th>
            <th>Recipient</th>
            <th>Owed</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="balance in balances"
            :key="`${balance.requester_id}:${balance.recipient_id}:${balance.cartridge_id ?? ''}:${balance.currency}`"
          >
            <td>
              <RouterLink
                v-if="allUsers"
                :to="{ path: '/usage', query: { user: balance.requester_id } }"
                >{{ balance.requester_name }}</RouterLink
              ><template v-else>{{ balance.requester_name }}</template>
            </td>
            <td>
              <RouterLink
                v-if="allUsers && balance.recipient_id"
                :to="{ path: '/usage', query: { user: balance.recipient_id } }"
                >{{ balance.recipient_name }}</RouterLink
              ><template v-else>{{ balance.recipient_name }}</template>
            </td>
            <td class="account-balance">{{ money(balance.owed, balance.currency) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="!balances.length && !error">No debts.</p>
    <AnimatedDetails
      v-if="cartridgeBalances.length || unallocated.length"
      class="cartridge-balances"
    >
      <template #summary>Debts by cartridge</template>
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Payer</th>
              <th>Recipient</th>
              <th>Cartridge</th>
              <th>Owed</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="balance in cartridgeBalances"
              :key="`${balance.requester_id}:${balance.recipient_id}:${balance.cartridge_id}:${balance.currency}`"
            >
              <td>{{ balance.requester_name }}</td>
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
                Unallocated {{ Number(balance.unallocated_owed) < 0 ? 'credit' : 'adjustment' }}
              </td>
              <td>{{ money(balance.unallocated_owed!, balance.currency) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </AnimatedDetails>
    <AnimatedDetails class="account-adjustment"
      ><template #summary>Record repayment or correction</template
      ><AccountAdjustment :users="users" :user-id="userId" @saved="refresh"
    /></AnimatedDetails>
  </section>
  <section v-if="adjustments.length" class="panel">
    <h2>Recent repayments & adjustments</h2>
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
  <section v-if="charges.length" class="panel">
    <h2>Charges & receivables</h2>
    <AnimatedDetails
      v-for="charge in charges"
      :key="`${charge.batch_id}:${charge.requester_id}`"
      class="account-charge"
      ><template #summary
        >{{ charge.requester_name }} · {{ charge.cartridge_name }} ·
        {{ date(charge.created_at) }}</template
      >
      <dl>
        <dt>{{ charge.recipient_assigned_at ? 'Assigned recipient' : 'Recipient' }}</dt>
        <dd>{{ charge.recipient_name ?? charge.cartridge_name }}</dd>
        <dt>Tape used</dt>
        <dd>{{ charge.consumed_mm === null ? 'Pending' : metres(charge.consumed_mm) }}</dd>
        <dt>Actual cost</dt>
        <dd>
          {{
            charge.actual_cost === null
              ? 'Pending or unpriced'
              : money(charge.actual_cost, charge.currency)
          }}
        </dd>
        <dt>Charged</dt>
        <dd>
          {{
            charge.own_cartridge
              ? 'Own cartridge — no debt'
              : charge.charged === null
                ? 'Pending or unpriced'
                : money(charge.charged, charge.currency)
          }}
        </dd>
      </dl>
    </AnimatedDetails>
  </section>
</template>
<style scoped>
.account-adjustment,
.cartridge-balances {
  margin-top: 1rem;
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
