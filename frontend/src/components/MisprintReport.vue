<script setup lang="ts">
import { t } from '../shared/i18n'
import { computed, ref, watch } from 'vue'
import { api } from '../shared/api'
import { useAuthStore } from '../auth/auth'
import { useWorkspaceStore } from '../shared/workspace'
import { randomUUID } from '../shared/uuid'
import type { BatchDetail } from '../shared/types'
import AdminDialog from './AdminDialog.vue'
import ReviewEvidence from './ReviewEvidence.vue'
import JobPreview from './JobPreview.vue'
const props = defineProps<{ batch: BatchDetail }>()
const emit = defineEmits<{ saved: [] }>()
const auth = useAuthStore(),
  w = useWorkspaceStore()
const opened = ref(false),
  selected = ref<string[]>([]),
  reason = ref(''),
  photo = ref<string | null>(null),
  error = ref('')
const printed = computed(() => props.batch.items.filter((item) => item.outcome === 'printed'))
let requestId = randomUUID()
watch(
  [selected, reason, photo],
  () => {
    requestId = randomUUID()
  },
  { deep: true, flush: 'sync' },
)
function open() {
  selected.value = []
  reason.value = ''
  photo.value = null
  error.value = ''
  opened.value = true
}
async function save() {
  if (
    w.busy ||
    !selected.value.length ||
    !reason.value.trim() ||
    (props.batch.evidence_policy === 'required' && !photo.value)
  )
    return
  if (
    await w.action(
      () =>
        api(`/batches/${props.batch.id}/misprints`, 'POST', {
          request_id: requestId,
          copy_ids: selected.value,
          reason: reason.value,
          evidence_photo: photo.value,
        }),
      t('uiMessages.misprintRecordedChooseRetryFundingSeparately'),
    )
  ) {
    opened.value = false
    emit('saved')
  } else error.value = w.actionError
}
</script>
<template>
  <button
    v-if="
      printed.length &&
      batch.finished_at &&
      !['printing', 'needs_review'].includes(batch.state) &&
      auth.printer(batch.printer_id, 'review')
    "
    type="button"
    class="secondary"
    @click="open"
  >
    {{ $t('misprintReport.reportMisprint') }}
  </button>
  <AdminDialog
    :open="opened"
    :title="$t('misprintReport.reportMisprint')"
    :busy="w.busy"
    @close="opened = false"
  >
    <form class="form-stack" @submit.prevent="save">
      <Transition name="notice"
        ><p v-if="error" role="alert" class="alert danger">{{ error }}</p></Transition
      >
      <div class="misprint-copies">
        <div v-for="item in printed" :key="item.copy_id" class="misprint-copy">
          <label class="checkbox"
            ><input v-model="selected" type="checkbox" :value="item.copy_id" />{{
              item.process_name
            }}
            · {{ item.attribution?.requested_by?.name ?? $t('uiMessages.unknownRequester') }}
            {{ $t('common.copy') }} {{ item.copy_number }}</label
          >
          <JobPreview
            :preview-url="`/api/batches/${batch.id}/items/${item.copy_id}/preview`"
            :job-id="item.job_id"
            :text="item.text"
            :width-mm="item.width_mm"
            :length-mm="item.length_mm"
          />
        </div>
      </div>
      <label
        >{{ $t('common.reason') }}<textarea v-model="reason" required maxlength="1000" rows="3" />
      </label>
      <ReviewEvidence
        v-model="photo"
        :policy="batch.evidence_policy ?? 'optional'"
        :disabled="w.busy"
      />
      <p class="alert warning">
        {{ $t('common.selectedCopiesWillBeMarkedAsFailedRecordedTape') }}
      </p>
      <div class="admin-actions">
        <button
          :disabled="
            w.busy ||
            !selected.length ||
            !reason.trim() ||
            (batch.evidence_policy === 'required' && !photo)
          "
        >
          {{ $t('common.saveMisprintReport') }}
        </button>
      </div>
    </form>
  </AdminDialog>
</template>
<style scoped>
.misprint-copies {
  display: grid;
  gap: 16px;
  max-height: 40vh;
  overflow: auto;
}
.misprint-copy {
  display: grid;
  gap: 8px;
}
</style>
