<script setup lang="ts">
import { t } from '../shared/i18n'
import { vValidateForm } from '../shared/formValidation'
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, errorMessage } from '../shared/api'
import type { BatchDetail } from '../shared/types'
import { useWorkspaceStore, date, metres } from '../shared/workspace'
import Badge from '../components/Badge.vue'
import JobPreview from '../components/JobPreview.vue'
import LabelDetails from '../components/LabelDetails.vue'
import PrintAttribution from '../components/PrintAttribution.vue'
import BatchTrigger from '../components/BatchTrigger.vue'
import PrintPlanNotice from '../components/PrintPlanNotice.vue'
import TapeUsage from '../components/TapeUsage.vue'
import AnimatedDetails from '../components/AnimatedDetails.vue'
import RetryControls from '../components/RetryControls.vue'
import ReviewEvidence from '../components/ReviewEvidence.vue'
import MisprintReport from '../components/MisprintReport.vue'
import AdminDialog from '../components/AdminDialog.vue'
import { randomUUID } from '../shared/uuid'
import { useAuthStore } from '../auth/auth'
import { useLiveRefresh } from '../shared/live'
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
const canReview = computed(
  () =>
    !!batch.value &&
    batch.value.state === 'needs_review' &&
    auth.printer(batch.value.printer_id, 'review'),
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
const photo = ref<string | null>(null),
  evidenceUrl = ref('')
let requestId = randomUUID()
watch(
  [decisions, consumed, cartridgeId, photo],
  () => {
    requestId = randomUUID()
  },
  { deep: true, flush: 'sync' },
)
async function refresh() {
  resources.invalidate(['/batches'])
  await load(true)
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
    if (!stopped && ticket === generation && auth.user?.id === actor) {
      batch.value = null
      error.value = errorMessage(e)
    }
  }
}
useLiveRefresh(async () => {
  if (!batch.value || batch.value.state === 'printing' || batch.value.state === 'needs_review')
    await load()
}, 5000)
watch([() => route.params.id, () => JSON.stringify(auth.user)], () => {
  generation++
  photo.value = null
  evidenceUrl.value = ''
  batch.value = null
  decisions.value = {}
  selected.value = []
  bulkDecision.value = ''
  consumed.value = null
  cartridgeId.value = ''
  void load()
})
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
          request_id: requestId,
          evidence_photo: photo.value,
          decisions: payload,
          consumed_mm: consumed.value,
          cartridge_id: cartridgeId.value,
        }),
      t('uiMessages.reviewSavedChooseRetryFundingSeparatelyForAnyUnprintedCopies'),
    )
  ) {
    photo.value = null
    await refresh()
  }
}
</script>
<template>
  <RouterLink class="back-link" to="/activity">{{ $t('common.backToActivity') }}</RouterLink>
  <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
  <section v-if="batch" class="panel">
    <div class="section-heading">
      <div>
        <h2>
          {{
            batch.cartridge_id
              ? w.cartridgeName(batch.cartridge_id)
              : $t('uiMessages.restrictedCartridge')
          }}
        </h2>
        <p>
          {{
            batch.printer_id
              ? w.destinationName(batch.printer_id)
              : $t('uiMessages.restrictedPrinter')
          }}
          · {{ date(batch.created_at)
          }}<template v-if="batch.estimated_mm != null">
            {{ $t('common.estimated') }} {{ metres(batch.estimated_mm) }}</template
          >
        </p>
      </div>
      <Badge :state="batch.state" />
    </div>
    <p v-if="batch.redacted" class="muted">{{ $t('common.yourLabels') }}</p>
    <BatchTrigger v-else :trigger="batch.trigger" />
    <PrintPlanNotice :plan="batch.print_plan" />
    <AnimatedDetails v-if="!batch.redacted" class="batch-tape-details">
      <template #summary>{{ $t('common.tapeDetails') }}</template>
      <TapeUsage :plan="batch.print_plan" caption="Saved estimate for this attempt" />
    </AnimatedDetails>
    <p v-if="batch.error" class="alert warning">{{ batch.error }}</p>
    <form v-validate-form @submit.prevent="resolve">
      <p v-if="canReview" class="help">
        {{ $t('review.inspectTheOutputAndChooseAnOutcomeForEach') }}
      </p>
      <div v-if="canReview" class="review-bulk">
        <label
          >{{ $t('review.actionForSelectedCopies')
          }}<select v-model="bulkDecision" :aria-label="$t('review.actionForSelectedCopies')">
            <option disabled value="">{{ $t('review.chooseOutcome') }}</option>
            <option value="printed">{{ $t('common.printed') }}</option>
            <option value="failed">{{ $t('review.didNotPrint') }}</option>
            <option value="cancelled">{{ $t('common.cancel') }}</option>
          </select></label
        >
        <button
          type="button"
          class="secondary"
          :disabled="!selected.length || !bulkDecision || w.busy"
          @click="applyDecision"
        >
          {{ $t('review.applyToSelected') }}
        </button>
        <span class="muted" role="status">{{ selected.length }} {{ $t('common.selected2') }}</span>
      </div>
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th v-if="canReview" class="review-selection">
                <label class="checkbox-target">
                  <input
                    type="checkbox"
                    :checked="allSelected"
                    :indeterminate="selected.length > 0 && !allSelected"
                    :aria-label="$t('common.selectAllUncertainCopies')"
                    @change="selectAll"
                  />
                </label>
              </th>
              <th>{{ $t('common.label') }}</th>
              <th>{{ $t('review.people') }}</th>
              <th>{{ $t('review.copy') }}</th>
              <th>{{ $t('review.outcome') }}</th>
              <th v-if="canReview">{{ $t('common.yourDecision') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in batch.items" :key="item.copy_id">
              <td v-if="canReview" class="review-selection">
                <label class="checkbox-target" v-if="item.outcome === 'needs_review'"
                  ><input
                    v-model="selected"
                    type="checkbox"
                    :value="item.copy_id"
                    :aria-label="
                      $t('uiDetails.selectLabel', { value1: String(item.position + 1) })
                    "
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
                  {{ $t('review.estimatedCutLength') }}
                  {{ item.output_plan.output_length_mm.toFixed(1) }} {{ $t('common.mm2') }}
                  {{
                    (
                      item.output_plan.minimum_padding_mm +
                      (item.output_plan.template_padding_mm ?? 0)
                    ).toFixed(1)
                  }}
                  {{ $t('common.mmExtraUnusedTapeHandTrimmingRequired') }}
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
              <td v-if="canReview">
                <div v-if="item.outcome === 'needs_review'" class="review-decision">
                  <select
                    v-model="decisions[item.copy_id]"
                    required
                    :aria-label="
                      $t('uiDetails.labelDecision', { value1: String(item.position + 1) })
                    "
                  >
                    <option disabled value="">{{ $t('review.chooseOutcome') }}</option>
                    <option value="printed">{{ $t('review.itPrinted') }}</option>
                    <option value="failed">{{ $t('review.itDidNotPrint') }}</option>
                    <option value="cancelled">{{ $t('review.cancelThisCopy') }}</option>
                  </select>
                  <button
                    type="button"
                    class="secondary"
                    :aria-label="
                      $t('uiDetails.selectUncertain', { value1: String(item.position + 1) })
                    "
                    @click="selectFollowing(item.copy_id)"
                  >
                    {{ $t('common.selectFromHere') }}
                  </button>
                </div>
                <span v-else class="muted">{{ $t('review.confirmedNoActionNeeded') }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="canReview" class="review-resolution">
        <label
          >{{ $t('review.cartridgeUsedForThisAttempt')
          }}<select v-model="cartridgeId" :disabled="w.busy" required>
            <option v-for="cartridge in w.cartridges" :key="cartridge.id" :value="cartridge.id">
              {{ cartridge.name }} · {{ w.profileName(cartridge.profile_id) }}
              {{ cartridge.archived ? '(Archived)' : '' }}
            </option>
          </select></label
        >
        <label
          >{{ $t('common.totalTapeConsumedByThisAttemptMm')
          }}<input v-model.number="consumed" type="number" min="0" step="0.1" required
        /></label>
        <p class="help">
          {{ $t('review.includeConfirmedLabelsPartialLabelsAndFeedWasteThis') }}
        </p>
        <ReviewEvidence
          v-model="photo"
          :policy="batch.evidence_policy ?? 'optional'"
          :disabled="w.busy"
        />
        <button
          class="primary"
          :disabled="
            w.busy ||
            !cartridgeId ||
            consumed === null ||
            uncertain.some((i) => !decisions[i.copy_id]) ||
            (batch.evidence_policy === 'required' && !photo)
          "
        >
          {{ $t('common.saveReview') }}
        </button>
      </div>
      <p v-else-if="batch.consumed_mm !== null" class="help">
        {{
          batch.consumption_source === 'estimated'
            ? $t('uiMessages.tapeUseEstimated')
            : $t('uiMessages.tapeConsumed')
        }}: {{ metres(batch.consumed_mm) }}{{ $t('review.thisAttemptHasBeenAccountedFor') }}
      </p>
    </form>
    <div class="batch-actions">
      <MisprintReport :key="batch.id" :batch="batch" @saved="refresh" />
      <RetryControls :batch="batch" />
    </div>
    <AnimatedDetails v-if="batch.reviews?.length" class="review-history">
      <template #summary>{{ $t('review.reviewHistory') }}</template>
      <div class="form-stack">
        <article v-for="review in batch.reviews" :key="review.id" class="form-stack">
          <strong
            >{{
              review.kind === 'misprint'
                ? $t('notificationMessages.misprintTitle')
                : $t('uiMessages.batchReviewed')
            }}
            · {{ review.actor_name }}</strong
          >
          <span class="muted"
            >{{ date(review.created_at) }} · {{ Object.keys(review.decisions).length }}
            {{ $t('common.copies2') }}</span
          >
          <p v-if="review.reason">{{ review.reason }}</p>
          <button
            v-if="review.photo_url"
            type="button"
            class="secondary"
            @click="evidenceUrl = review.photo_url"
          >
            {{ $t('common.viewEvidencePhoto') }}
          </button>
        </article>
      </div>
    </AnimatedDetails>
    <AdminDialog
      :open="!!evidenceUrl"
      :title="$t('common.evidencePhoto')"
      @close="evidenceUrl = ''"
    >
      <img
        v-if="evidenceUrl"
        :src="evidenceUrl"
        :alt="$t('common.batchReviewEvidence')"
        class="review-photo"
      />
    </AdminDialog>
  </section>
  <div v-else-if="!error" class="panel empty">{{ $t('review.loadingBatch') }}</div>
</template>

<style scoped>
.batch-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 20px;
}
.review-history {
  margin-top: 24px;
}
.review-photo {
  display: block;
  width: 100%;
  max-height: 70vh;
  object-fit: contain;
}
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
  gap: 10px;
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
