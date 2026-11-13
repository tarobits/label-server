<script setup lang="ts">
import { t } from '../shared/i18n'
import { api } from '../shared/api'
import { useWorkspaceStore, date } from '../shared/workspace'
const w = useWorkspaceStore()
import { confirmAction } from '../shared/confirmation'
import JobPreview from '../components/JobPreview.vue'
import type { AccessHold } from '../shared/types'
async function resolve(hold: AccessHold, release: boolean) {
  if (
    !(await confirmAction(
      release
        ? t(
            'uiMessages.releaseTheseSavedCopiesForPrintingDespiteTheAccessChangeTheyMayPrintAutomatically',
          )
        : t('uiMessages.cancelThesePausedQueuedCopiesPrintedCopiesStayInHistory'),
    ))
  )
    return
  await w.action(
    () => api(`/access-holds/${hold.job_id}/${release ? 'release' : 'cancel'}`, 'POST', {}),
    release
      ? t('uiMessages.pausedCopiesReleasedByAnAdministrator')
      : t('uiMessages.pausedCopiesCancelled'),
  )
}
</script>
<template>
  <div class="panel">
    <p>
      {{ $t('common.theseQueuedLabelsWerePausedBecauseAnAccountLost') }}
    </p>
  </div>
  <p v-if="!w.accessHolds.length" class="panel empty">
    {{ $t('accessHolds.noLabelsArePausedForAccessReview') }}
  </p>
  <article v-for="hold in w.accessHolds" :key="hold.job_id" class="panel">
    <div class="section-heading">
      <h2>{{ hold.owner_name }}</h2>
      <span class="badge">{{ $t('accessHolds.paused') }}</span>
    </div>
    <p>{{ hold.reason }} · {{ date(hold.held_at) }}</p>
    <p class="help">
      {{ w.destinationName(hold.job.destination_id) }} ·
      {{ hold.job.labels.filter((copy) => copy.state === 'queued').length }}
      {{ $t('common.queuedCopies') }}
    </p>
    <JobPreview
      :job-id="hold.job_id"
      :text="Object.values(hold.job.payload).join(' · ') || $t('uiMessages.imageLabel')"
      :width-mm="hold.job.width_mm"
      :length-mm="hold.job.length_mm"
    />
    <div class="row wrap">
      <button
        class="primary"
        :disabled="w.busy || hold.can_release === false"
        @click="resolve(hold, true)"
      >
        {{ $t('accessHolds.releaseCopies') }}</button
      ><button class="secondary danger-text" :disabled="w.busy" @click="resolve(hold, false)">
        {{ $t('accessHolds.cancelCopies') }}
      </button>
    </div>
  </article>
</template>
