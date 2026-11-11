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
import PairAccounts from '../components/PairAccounts.vue'
import SectionLayout from '../components/SectionLayout.vue'
import ExpandableContent from '../components/ExpandableContent.vue'
import type { UsageReport, UsageUser } from '../types'
const auth = useAuthStore()
const resources = useResourceStore()
const route = useRoute()
const router = useRouter()
const navigationGroups = [
  { title: 'Usage', sections: [{ id: 'usage', title: 'Tape & allocations' }] },
  {
    title: 'Accounting',
    sections: [
      { id: 'balances', title: 'Account balances' },
      { id: 'cartridges', title: 'Debts by cartridge' },
      { id: 'charges', title: 'Charges & receivables' },
      { id: 'payments', title: 'Repayments & corrections' },
    ],
  },
]
const section = computed(
  () =>
    navigationGroups
      .flatMap((group) => group.sections)
      .find((item) => item.id === route.query.section)?.id ?? 'usage',
)
function navigate(value: string) {
  void router.replace({ query: { ...route.query, section: value } })
}
const canViewOthers = computed(() => auth.can('usage.view_others'))
const canEditAccounts = computed(() => auth.can('usage.edit_accounts'))
function filterQuery(key: string, value: string) {
  const query = { ...route.query }
  if (value) query[key] = value
  else delete query[key]
  return query
}
const selected = computed({
  get: () => (canViewOthers.value && typeof route.query.user === 'string' ? route.query.user : ''),
  set: (user: string) => {
    void router.replace({ query: filterQuery('user', user) })
  },
})
const cartridge = computed({
  get: () => (typeof route.query.cartridge === 'string' ? route.query.cartridge : ''),
  set: (value: string) => {
    void router.replace({ query: filterQuery('cartridge', value) })
  },
})
const cartridges = ref<UsageReport['cartridges']>([])
const allUsers = computed(() => selected.value === 'all')
const users = ref<UsageUser[]>([])
const report = ref<UsageReport | null>(null)
const error = ref('')
let sequence = 0
async function refresh() {
  const ticket = ++sequence
  try {
    const parameters = new URLSearchParams()
    if (allUsers.value) parameters.set('all_users', 'true')
    else if (selected.value) parameters.set('user_id', selected.value)
    if (cartridge.value) parameters.set('cartridge_id', cartridge.value)
    const query = parameters.size ? `?${parameters}` : ''
    const [value, names] = await Promise.all([
      resources.get<UsageReport>(`/usage${query}`, { ttl: 2000 }),
      canViewOthers.value || canEditAccounts.value
        ? resources.get<UsageUser[]>('/usage/users', { ttl: 2000 })
        : Promise.resolve([]),
    ])
    if (ticket === sequence) {
      report.value = value
      cartridges.value = value.cartridges
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
watch([selected, cartridge, canViewOthers, canEditAccounts, () => auth.user?.id], () => {
  report.value = null
  users.value = []
  void refresh()
})
watch([selected, canViewOthers, () => auth.user?.id], () => {
  cartridges.value = []
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
  <div class="row wrap usage-filters">
    <label v-if="canViewOthers"
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
    <ExpandableContent :open="section === 'usage'" class="usage-cartridge-filter"
      ><label>
        Cartridge<select v-model="cartridge">
          <option value="">All cartridges</option>
          <option
            v-if="cartridge && !cartridges.some((item) => item.id === cartridge)"
            :value="cartridge"
          >
            Selected cartridge (no tracked usage)
          </option>
          <option v-for="item in cartridges" :key="item.id" :value="item.id">
            {{ item.name }} · {{ item.profile_name }}
          </option>
        </select>
      </label></ExpandableContent
    >
  </div>
  <Transition name="notice"
    ><p v-if="error" class="alert danger" role="alert">{{ error }}</p></Transition
  >
  <SectionLayout label="Tape usage" :groups="navigationGroups" :active="section" @select="navigate">
    <div v-show="section === 'usage'" class="usage-content">
      <div v-if="!report && !error" class="empty" role="status">Loading tape usage…</div>
      <template v-if="report">
        <section>
          <h2>Allocated tape and cost</h2>
          <p class="help">
            Includes design, feed, unused tape and a proportional share of the batch leader. Prices
            are frozen per attempt.
          </p>
          <div v-if="!report.users.length" class="empty compact">
            {{
              cartridge ? 'No tracked usage for this cartridge.' : 'No tracked print attempts yet.'
            }}
          </div>
          <article v-for="user in report.users" :key="user.user_id" class="list-row">
            <div class="grow">
              <strong>{{ user.username }}</strong>
              <small
                >{{ metres(user.consumed_mm) }} used<span v-if="user.pending_mm">
                  · {{ metres(user.pending_mm) }} pending review or completion</span
                ><span v-if="user.unpriced_mm">
                  · {{ metres(user.unpriced_mm) }} unpriced</span
                ></small
              >
            </div>
            <div class="usage-costs">
              <strong v-for="(cost, currency) in user.costs" :key="currency">{{
                money(cost, currency)
              }}</strong>
            </div>
          </article>
        </section>
        <section v-if="report.entries.length">
          <h2>Recent allocations</h2>
          <AnimatedDetails
            v-for="entry in report.entries"
            :key="`${entry.batch_id}:${entry.user_id}`"
            class="usage-entry"
          >
            <template #summary
              >{{ entry.username }} · {{ date(entry.created_at) }} · {{ entry.cartridge_name }} ·
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
              <span>Cartridge: {{ entry.cartridge_name }} · {{ entry.profile_name }}</span>
              <div class="row">
                <Badge :state="entry.state" /><span
                  >{{
                    entry.consumed_mm === null
                      ? 'Planned'
                      : (entry.consumption_source ?? 'Accounted')
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
    </div>
    <PairAccounts
      v-show="section !== 'usage'"
      :section="section"
      :user-id="selected === 'all' ? '' : selected"
      :all-users="allUsers"
    />
  </SectionLayout>
</template>
<style scoped>
.usage-filters {
  align-items: end;
  margin-bottom: 24px;
  padding-bottom: 24px;
  border-bottom: 1px solid var(--line);
}
.usage-content {
  display: grid;
  gap: 32px;
  min-width: 0;
}
.usage-content h2 {
  font-size: 20px;
  margin-bottom: 24px;
}
.usage-filters > label,
.usage-cartridge-filter {
  flex: 1 1 240px;
  min-width: 0;
  max-width: 360px;
}
.usage-filters label {
  flex: 1 1 240px;
  min-width: 0;
  max-width: 100%;
}
.usage-entry {
  overflow-wrap: anywhere;
}
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
