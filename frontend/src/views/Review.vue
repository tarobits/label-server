<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, errorMessage } from '../api'
import type { BatchDetail } from '../types'
import { workspace as w, date, metres } from '../workspace'
import Badge from '../components/Badge.vue'
import JobPreview from '../components/JobPreview.vue'
import PrintAttribution from '../components/PrintAttribution.vue'
import BatchTrigger from '../components/BatchTrigger.vue'
const route = useRoute(),
  batch = ref<BatchDetail | null>(null),
  error = ref('')
const decisions = ref<Record<string, string>>({}),
  consumed = ref<number | null>(null)
const uncertain = computed(
  () => batch.value?.items.filter((i) => i.outcome === 'needs_review') ?? [],
)
let timer: ReturnType<typeof setTimeout> | undefined,
  stopped = false,
  generation = 0
async function load() {
  const ticket = ++generation,
    id = String(route.params.id)
  try {
    const result = await api<BatchDetail>(`/batches/${encodeURIComponent(id)}`)
    if (ticket === generation) {
      batch.value = result
      error.value = ''
    }
  } catch (e) {
    if (ticket === generation) error.value = errorMessage(e)
  }
}
async function poll() {
  await load()
  if (!stopped) timer = setTimeout(poll, 2500)
}
watch(
  () => route.params.id,
  () => {
    batch.value = null
    decisions.value = {}
    consumed.value = null
    void load()
  },
)
onMounted(poll)
onUnmounted(() => {
  stopped = true
  generation++
  clearTimeout(timer)
})
async function resolve() {
  if (!batch.value) return
  const payload = Object.fromEntries(
    uncertain.value.map((item) => [item.copy_id, decisions.value[item.copy_id]]),
  )
  if (
    await w.action(
      () =>
        api(`/batches/${batch.value!.id}/review`, 'POST', {
          decisions: payload,
          consumed_mm: consumed.value,
        }),
      'Review saved. Printing can resume; requeued copies follow the normal threshold.',
    )
  )
    await load()
}
</script>
<template>
  <RouterLink class="back-link" to="/activity">← Back to activity</RouterLink>
  <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
  <section v-if="batch" class="panel">
    <div class="section-heading">
      <div>
        <h2>{{ w.cartridgeName(batch.cartridge_id) }}</h2>
        <p>
          {{ w.destinationName(batch.printer_id) }} · {{ date(batch.created_at) }} · Estimated
          {{ metres(batch.estimated_mm) }}
        </p>
      </div>
      <Badge :state="batch.state" />
    </div>
    <BatchTrigger :trigger="batch.trigger" />
    <p v-if="batch.error" class="alert warning">{{ batch.error }}</p>
    <form @submit.prevent="resolve">
      <p v-if="batch.state === 'needs_review'" class="help">
        Inspect the output and choose an outcome for each uncertain copy. Confirmed copies are
        locked.
      </p>
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Label</th>
              <th>People</th>
              <th>Copy</th>
              <th>Outcome</th>
              <th v-if="batch.state === 'needs_review'">Your decision</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in batch.items" :key="item.copy_id">
              <td class="review-text">
                <JobPreview
                  :preview-url="`/api/batches/${batch.id}/items/${item.copy_id}/preview`"
                  :job-id="item.job_id"
                  :text="item.text"
                  :width-mm="item.width_mm"
                  :length-mm="item.length_mm"
                />
                <span>{{ item.text }}</span>
              </td>
              <td class="review-attribution">
                <PrintAttribution :attribution="item.attribution" />
              </td>
              <td>{{ item.copy_number }}</td>
              <td><Badge :state="item.outcome" /></td>
              <td v-if="batch.state === 'needs_review'">
                <select
                  v-if="item.outcome === 'needs_review'"
                  v-model="decisions[item.copy_id]"
                  required
                  :aria-label="`Decision for label ${item.position + 1}`"
                >
                  <option disabled value="">Choose outcome</option>
                  <option value="printed">It printed</option>
                  <option value="queued">Requeue this copy</option>
                  <option value="cancelled">Cancel this copy</option></select
                ><span v-else class="muted">Confirmed — no action needed</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="batch.state === 'needs_review'" class="review-resolution">
        <label
          >Total tape consumed by this attempt (mm)<input
            v-model.number="consumed"
            type="number"
            min="0"
            step="0.1"
            required
            placeholder="Include printed copies and waste"
        /></label>
        <p class="help">
          Include confirmed labels, partial labels, and feed waste. This total is deducted once from
          the cartridge.
        </p>
        <button
          class="primary"
          :disabled="
            w.busy.value || consumed === null || uncertain.some((i) => !decisions[i.copy_id])
          "
        >
          Save review and resume
        </button>
      </div>
      <p v-else-if="batch.consumed_mm !== null" class="help">
        Tape consumed: {{ metres(batch.consumed_mm) }}. This attempt has been accounted for.
      </p>
    </form>
  </section>
  <div v-else-if="!error" class="panel empty">Loading batch…</div>
</template>

<style scoped>
.review-attribution {
  min-width: 220px;
  vertical-align: top;
}
</style>
