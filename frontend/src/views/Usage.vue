<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../auth'
import { errorMessage } from '../api'
import { useResourceStore } from '../stores/resources'
import { useLiveRefresh } from '../live'
import { date, metres } from '../workspace'
import AnimatedDetails from '../components/AnimatedDetails.vue'
import Badge from '../components/Badge.vue'
import AccountAdjustment from '../components/AccountAdjustment.vue'
import type { UsageReport, UsageUser } from '../types'
const auth = useAuthStore()
const resources = useResourceStore()
const route = useRoute()
const router = useRouter()
const canViewOthers = computed(() => auth.can('usage.view_others'))
const canEditAccounts = computed(() => auth.can('usage.edit_accounts'))
const selected = computed({
  get: () => (canViewOthers.value && typeof route.query.user === 'string' ? route.query.user : ''),
  set: (user: string) => {
    void router.replace({ query: user ? { user } : {} })
  },
})
const allUsers = computed(() => selected.value === 'all')
const users = ref<UsageUser[]>([])
const adjustmentUser = computed(() => (allUsers.value ? '' : selected.value || auth.user?.id || ''))
const report = ref<UsageReport | null>(null)
const error = ref('')
let sequence = 0
async function refresh() {
  const ticket = ++sequence
  try {
    const query = allUsers.value
      ? '?all_users=true'
      : selected.value
        ? `?user_id=${encodeURIComponent(selected.value)}`
        : ''
    const [value, names] = await Promise.all([
      resources.get<UsageReport>(`/usage${query}`, { ttl: 2000 }),
      canViewOthers.value || canEditAccounts.value
        ? resources.get<UsageUser[]>('/usage/users', { ttl: 2000 })
        : Promise.resolve([]),
    ])
    if (ticket === sequence) {
      report.value = value
      users.value = names
      error.value = ''
    }
  } catch (cause) {
    if (ticket === sequence) {
      report.value = null
      users.value = []
      error.value = errorMessage(cause)
    }
  }
}
watch([selected, canViewOthers, canEditAccounts, () => auth.user?.id], () => {
  report.value = null
  users.value = []
  void refresh()
})
useLiveRefresh(refresh)
onUnmounted(() => {
  sequence++
})
function money(value: string, currency: string) {
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 6,
  }).format(Number(value))
}
</script>
<template>
  <div v-if="canViewOthers" class="section-heading">
    <label
      >View<select v-model="selected">
        <option value="">My usage</option>
        <option value="all">All users</option>
        <option
          v-for="user in users.filter((user) => user.user_id !== auth.user?.id)"
          :key="user.user_id"
          :value="user.user_id"
        >
          {{ user.username }}
        </option>
      </select></label
    >
  </div>
  <Transition name="notice"
    ><p v-if="error" class="alert danger" role="alert">{{ error }}</p></Transition
  >
  <div v-if="!report && !error" class="panel empty" role="status">Loading tape usage…</div>
  <template v-if="report">
    <section class="panel usage-accounts">
      <h2>{{ allUsers ? 'Account balances' : 'Account balance' }}</h2>
      <p class="help">
        Negative balances are amounts owed. Unpriced and pending tape are excluded.
      </p>
      <article v-for="account in report.accounts" :key="account.user_id" class="list-row">
        <div class="grow">
          <RouterLink
            v-if="allUsers"
            :to="{
              path: '/usage',
              query: account.user_id === auth.user?.id ? {} : { user: account.user_id },
            }"
            >{{ account.username }}</RouterLink
          >
          <strong v-else>{{ account.username }}</strong>
        </div>
        <div class="usage-costs account-balance">
          <strong v-for="(balance, currency) in account.balances" :key="currency">{{
            money(balance, currency)
          }}</strong>
          <span v-if="!Object.keys(account.balances).length" class="muted"
            >No charges or payments yet</span
          >
        </div>
      </article>
      <AnimatedDetails v-if="canEditAccounts" class="account-adjustment">
        <template #summary>Adjust account</template>
        <AccountAdjustment :users="users" :user-id="adjustmentUser" @saved="refresh" />
      </AnimatedDetails>
    </section>
    <section class="panel">
      <h2>Allocated tape and cost</h2>
      <p class="help">
        Includes design, feed, unused tape and a proportional share of the batch leader. Prices are
        frozen per attempt.
      </p>
      <div v-if="!report.users.length" class="empty compact">No tracked print attempts yet.</div>
      <article v-for="user in report.users" :key="user.user_id" class="list-row">
        <div class="grow">
          <strong>{{ user.username }}</strong>
          <small
            >{{ metres(user.consumed_mm) }} used<span v-if="user.pending_mm">
              · {{ metres(user.pending_mm) }} pending review or completion</span
            ><span v-if="user.unpriced_mm"> · {{ metres(user.unpriced_mm) }} unpriced</span></small
          >
        </div>
        <div class="usage-costs">
          <strong v-for="(cost, currency) in user.costs" :key="currency">{{
            money(cost, currency)
          }}</strong>
        </div>
      </article>
    </section>
    <section v-if="report.adjustments.length" class="panel">
      <h2>Recent adjustments</h2>
      <article
        v-for="adjustment in report.adjustments"
        :key="adjustment.id"
        class="list-row adjustment-entry"
      >
        <div class="grow">
          <strong>{{ adjustment.note }}</strong>
          <small
            ><span v-if="allUsers">{{ adjustment.username }} · </span
            >{{ date(adjustment.created_at) }} · {{ adjustment.actor_name }}</small
          >
        </div>
        <strong class="usage-costs"
          >{{ adjustment.amount_minor > 0 ? '+' : ''
          }}{{ money(String(adjustment.amount_minor / 100), adjustment.currency) }}</strong
        >
      </article>
    </section>
    <section v-if="report.entries.length" class="panel">
      <h2>Recent allocations</h2>
      <AnimatedDetails
        v-for="entry in report.entries"
        :key="`${entry.batch_id}:${entry.user_id}`"
        class="usage-entry"
      >
        <template #summary
          >{{ entry.username }} · {{ date(entry.created_at) }} ·
          {{ metres(entry.consumed_mm ?? entry.planned_mm) }} ·
          {{
            entry.consumed_mm === null
              ? 'Pending'
              : entry.cost === null
                ? 'Unpriced'
                : money(entry.cost, entry.currency)
          }}</template
        >
        <div class="form-stack inset">
          <div class="row">
            <Badge :state="entry.state" /><span
              >{{
                entry.consumed_mm === null ? 'Planned' : (entry.consumption_source ?? 'Accounted')
              }}
              tape: {{ metres(entry.consumed_mm ?? entry.planned_mm) }}</span
            >
          </div>
          <span
            >Cartridge price:
            {{
              entry.price_minor === null
                ? 'Not set'
                : `${(entry.price_minor / 100).toFixed(2)} ${entry.currency}`
            }}
            / {{ metres(entry.nominal_length_mm) }}</span
          >
          <RouterLink v-if="auth.user?.is_admin" :to="`/batches/${entry.batch_id}`"
            >Batch details →</RouterLink
          >
        </div>
      </AnimatedDetails>
    </section>
  </template>
</template>
<style scoped>
.usage-entry {
  padding: 14px 0;
  border-bottom: 1px solid var(--line);
}
.usage-entry:last-child {
  border-bottom: 0;
}
.usage-costs {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-variant-numeric: tabular-nums;
}
.account-adjustment {
  padding-top: 14px;
}
.adjustment-entry .grow {
  min-width: 0;
  overflow-wrap: anywhere;
}
.account-balance {
  justify-content: flex-end;
}
</style>
