<script setup lang="ts">
import { api } from '../api'
import { useWorkspaceStore, date } from '../workspace'
const w = useWorkspaceStore()
import { confirmAction } from '../confirmation'
import JobPreview from '../components/JobPreview.vue'
import type { AccessHold } from '../types'
async function resolve(hold: AccessHold, release: boolean) {
  if (
    !(await confirmAction(
      release
        ? 'Release these saved copies for printing despite the access change? They may print automatically.'
        : 'Cancel these paused queued copies? Printed copies stay in history.',
    ))
  )
    return
  await w.action(
    () => api(`/access-holds/${hold.job_id}/${release ? 'release' : 'cancel'}`, 'POST', {}),
    release ? 'Paused copies released by an administrator.' : 'Paused copies cancelled.',
  )
}
</script>
<template>
  <div class="panel">
    <p>
      These queued labels were paused because an account lost access or required content was
      deleted. Restore deleted content before releasing affected labels. Restoring access or content
      alone does not release a hold.
    </p>
  </div>
  <p v-if="!w.accessHolds.length" class="panel empty">No labels are paused for access review.</p>
  <article v-for="hold in w.accessHolds" :key="hold.job_id" class="panel">
    <div class="section-heading">
      <h2>{{ hold.owner_name }}</h2>
      <span class="badge">Paused</span>
    </div>
    <p>{{ hold.reason }} · {{ date(hold.held_at) }}</p>
    <p class="help">
      {{ w.destinationName(hold.job.destination_id) }} ·
      {{ hold.job.labels.filter((copy) => copy.state === 'queued').length }} queued copies
    </p>
    <JobPreview
      :job-id="hold.job_id"
      :text="Object.values(hold.job.payload).join(' · ') || 'Image label'"
      :width-mm="hold.job.width_mm"
      :length-mm="hold.job.length_mm"
    />
    <div class="row wrap">
      <button
        class="primary"
        :disabled="w.busy || hold.can_release === false"
        @click="resolve(hold, true)"
      >
        Release copies</button
      ><button class="secondary danger-text" :disabled="w.busy" @click="resolve(hold, false)">
        Cancel copies
      </button>
    </div>
  </article>
</template>
