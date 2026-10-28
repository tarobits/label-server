<script setup lang="ts">
import { ref, watch } from 'vue'
import { useAuthStore } from '../auth'
import { errorMessage } from '../api'
import { useResourceStore } from '../stores/resources'
import { useLiveRefresh } from '../live'
import { date, metres } from '../workspace'
import AnimatedDetails from '../components/AnimatedDetails.vue'
import Badge from '../components/Badge.vue'
import type { UsageReport } from '../types'
const auth = useAuthStore()
const resources = useResourceStore()
const allUsers = ref(false)
const report = ref<UsageReport | null>(null)
const error = ref('')
let sequence = 0
async function refresh() {
  const ticket = ++sequence
  try {
    const value = await resources.get<UsageReport>(`/usage?all_users=${allUsers.value}`, {
      ttl: 2000,
    })
    if (ticket === sequence) {
      report.value = value
      error.value = ''
    }
  } catch (cause) {
    if (ticket === sequence) error.value = errorMessage(cause)
  }
}
watch(allUsers, () => {
  report.value = null
  void refresh()
})
useLiveRefresh(refresh)
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
  <div v-if="auth.user?.is_admin" class="section-heading">
    <label
      >View<select v-model="allUsers">
        <option :value="false">My usage</option>
        <option :value="true">All users</option>
      </select></label
    >
  </div>
  <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
  <div v-if="!report && !error" class="panel empty" role="status">Loading tape usage…</div>
  <template v-if="report">
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
</style>
