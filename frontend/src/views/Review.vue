<script setup lang="ts">
import { vValidateForm } from '../formValidation'
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, errorMessage } from '../api'
import type { BatchDetail } from '../types'
import { useWorkspaceStore, date, metres } from '../workspace'
import Badge from '../components/Badge.vue'
import JobPreview from '../components/JobPreview.vue'
import LabelDetails from '../components/LabelDetails.vue'
import PrintAttribution from '../components/PrintAttribution.vue'
import BatchTrigger from '../components/BatchTrigger.vue'
import PrintPlanNotice from '../components/PrintPlanNotice.vue'
import TapeUsage from '../components/TapeUsage.vue'
import AnimatedDetails from '../components/AnimatedDetails.vue'
import { useAuthStore } from '../auth'
import { useLiveRefresh } from '../live'
import { useResourceStore } from '../stores/resources'
const w = useWorkspaceStore()
const auth = useAuthStore()
const route = useRoute(),
  resources = useResourceStore(),
  batch = ref<BatchDetail | null>(null),
  error = ref('')
const decisions = ref<Record<string, string>>({}),
  cartridgeId = ref(''),
  consumed = ref<number | null>(null),
  selected = ref<string[]>([]),
  bulkDecision = ref('')
const uncertain = computed(
  () => batch.value?.items.filter((i) => i.outcome === 'needs_review') ?? [],
)
const allSelected = computed(
  () => uncertain.value.length > 0 && selected.value.length === uncertain.value.length,
)
function selectAll(event: Event) {
  selected.value = (event.target as HTMLInputElement).checked
    ? uncertain.value.map((item) => item.copy_id)
    : []
}
function selectFollowing(copyId: string) {
  const start = uncertain.value.findIndex((item) => item.copy_id === copyId)
  if (start >= 0) selected.value = uncertain.value.slice(start).map((item) => item.copy_id)
}
function applyDecision() {
  if (!bulkDecision.value) return
  for (const item of uncertain.value)
    if (selected.value.includes(item.copy_id)) decisions.value[item.copy_id] = bulkDecision.value
}
let stopped = false,
  generation = 0
async function load(force = false) {
  const ticket = ++generation,
    id = String(route.params.id),
    actor = auth.user?.id
  try {
    const result = await resources.get<BatchDetail>(`/batches/${encodeURIComponent(id)}`, {
      ttl: 5000,
      force,
    })
    if (!stopped && ticket === generation && auth.user?.id === actor) {
      if (!batch.value) cartridgeId.value = result.cartridge_id
      if (JSON.stringify(batch.value) !== JSON.stringify(result)) batch.value = result
      const ids = new Set(uncertain.value.map((item) => item.copy_id))
      selected.value = selected.value.filter((id) => ids.has(id))
      error.value = ''
    }
  } catch (e) {
    if (!stopped && ticket === generation && auth.user?.id === actor) error.value = errorMessage(e)
  }
}
useLiveRefresh(async () => {
  if (!batch.value || batch.value.state === 'printing' || batch.value.state === 'needs_review')
    await load()
}, 5000)
watch(
  () => route.params.id,
  () => {
    generation++
    batch.value = null
    decisions.value = {}
    selected.value = []
    bulkDecision.value = ''
    consumed.value = null
    cartridgeId.value = ''
    void load()
  },
)
onUnmounted(() => {
  stopped = true
  generation++
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
          cartridge_id: cartridgeId.value,
        }),
      'Review saved. Requeued copies follow the printer’s hold and queue settings.',
    )
  ) {
    resources.invalidate(['/batches'])
    await load(true)
  }
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
    <PrintPlanNotice :plan="batch.print_plan" />
    <AnimatedDetails class="batch-tape-details">
      <template #summary>Tape details</template>
      <TapeUsage :plan="batch.print_plan" caption="Saved estimate for this attempt" />
    </AnimatedDetails>
    <p v-if="batch.error" class="alert warning">{{ batch.error }}</p>
    <form v-validate-form @submit.prevent="resolve">
      <p v-if="batch.state === 'needs_review'" class="help">
        Inspect the output and choose an outcome for each uncertain copy. Select from a row to
        include that copy and all following uncertain copies.
      </p>
      <div v-if="batch.state === 'needs_review'" class="review-bulk">
        <label
          >Action for selected copies<select
            v-model="bulkDecision"
            aria-label="Action for selected copies"
          >
            <option disabled value="">Choose outcome</option>
            <option value="printed">Printed</option>
            <option value="queued">Requeue</option>
            <option value="cancelled">Cancel</option>
          </select></label
        >
        <button
          type="button"
          class="secondary"
          :disabled="!selected.length || !bulkDecision || w.busy"
          @click="applyDecision"
        >
          Apply to selected
        </button>
        <span class="muted" role="status">{{ selected.length }} selected</span>
      </div>
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th v-if="batch.state === 'needs_review'" class="review-selection">
                <label class="checkbox-target">
                  <input
                    type="checkbox"
                    :checked="allSelected"
                    :indeterminate="selected.length > 0 && !allSelected"
                    aria-label="Select all uncertain copies"
                    @change="selectAll"
                  />
                </label>
              </th>
              <th>Label</th>
              <th>People</th>
              <th>Copy</th>
              <th>Outcome</th>
              <th v-if="batch.state === 'needs_review'">Your decision</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in batch.items" :key="item.copy_id">
              <td v-if="batch.state === 'needs_review'" class="review-selection">
                <label class="checkbox-target" v-if="item.outcome === 'needs_review'"
                  ><input
                    v-model="selected"
                    type="checkbox"
                    :value="item.copy_id"
                    :aria-label="`Select label ${item.position + 1}`"
                /></label>
              </td>
              <td class="review-text">
                <strong>{{ item.process_name }}</strong>
                <LabelDetails :label="item" />
                <p
                  v-if="
                    item.output_plan &&
                    (item.output_plan.minimum_padding_mm || item.output_plan.template_padding_mm)
                  "
                  class="help"
                >
                  Estimated cut length {{ item.output_plan.output_length_mm.toFixed(1) }} mm ·
                  {{
                    (
                      item.output_plan.minimum_padding_mm +
                      (item.output_plan.template_padding_mm ?? 0)
                    ).toFixed(1)
                  }}
                  mm extra unused tape · Hand trimming required
                </p>
                <JobPreview
                  :preview-url="`/api/batches/${batch.id}/items/${item.copy_id}/preview`"
                  :job-id="item.job_id"
                  :text="item.text"
                  :width-mm="item.width_mm"
                  :length-mm="item.length_mm"
                />
              </td>
              <td class="review-attribution">
                <PrintAttribution :attribution="item.attribution" queue />
              </td>
              <td>{{ item.copy_number }}</td>
              <td><Badge :state="item.outcome" /></td>
              <td v-if="batch.state === 'needs_review'">
                <div v-if="item.outcome === 'needs_review'" class="review-decision">
                  <select
                    v-model="decisions[item.copy_id]"
                    required
                    :aria-label="`Decision for label ${item.position + 1}`"
                  >
                    <option disabled value="">Choose outcome</option>
                    <option value="printed">It printed</option>
                    <option value="queued">Requeue this copy</option>
                    <option value="cancelled">Cancel this copy</option>
                  </select>
                  <button
                    type="button"
                    class="secondary"
                    :aria-label="`Select label ${item.position + 1} and following uncertain labels`"
                    @click="selectFollowing(item.copy_id)"
                  >
                    Select from here
                  </button>
                </div>
                <span v-else class="muted">Confirmed — no action needed</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="batch.state === 'needs_review'" class="review-resolution">
        <label
          >Cartridge used for this attempt<select v-model="cartridgeId" :disabled="w.busy" required>
            <option v-for="cartridge in w.cartridges" :key="cartridge.id" :value="cartridge.id">
              {{ cartridge.name }} · {{ w.profileName(cartridge.profile_id) }}
            </option>
          </select></label
        >
        <label
          >Total tape consumed by this attempt (mm)<input
            v-model.number="consumed"
            type="number"
            min="0"
            step="0.1"
            required
        /></label>
        <p class="help">
          Include confirmed labels, partial labels, and feed waste. This total is deducted once from
          the selected cartridge. The installed cartridge stays unchanged.
        </p>
        <button
          class="primary"
          :disabled="
            w.busy ||
            !cartridgeId ||
            consumed === null ||
            uncertain.some((i) => !decisions[i.copy_id])
          "
        >
          Save review
        </button>
      </div>
      <p v-else-if="batch.consumed_mm !== null" class="help">
        {{ batch.consumption_source === 'estimated' ? 'Tape use estimated' : 'Tape consumed' }}:
        {{ metres(batch.consumed_mm) }}. This attempt has been accounted for.
      </p>
    </form>
  </section>
  <div v-else-if="!error" class="panel empty">Loading batch…</div>
</template>

<style scoped>
.review-bulk {
  display: flex;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: 15px;
  margin: 20px 0;
}
.review-bulk label {
  width: 250px;
  max-width: 100%;
}
.review-bulk > span {
  align-self: center;
}
.review-selection {
  width: 44px;
}
.review-decision {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 165px;
}
.review-decision button {
  white-space: nowrap;
}
.review-attribution {
  min-width: 220px;
  vertical-align: top;
}
</style>
