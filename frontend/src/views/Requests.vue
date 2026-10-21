<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errorMessage } from '../api'
import { useAuthStore } from '../auth'
import { useWorkspaceStore, date } from '../workspace'
import { confirmAction } from '../confirmation'
import { useLiveRefresh } from '../live'
import { useResourceStore } from '../stores/resources'
interface PrintRequest {
  id: string
  owner_id: string
  owner_name?: string
  destination_id: string
  status: 'pending' | 'approved' | 'rejected'
  created_at: number
  decided_at: number | null
  reason: string | null
  job_ids: string[]
  kind: 'job' | 'image' | 'run'
  labels: { payload: Record<string, string>; width_mm: number; length_mm: number; copies: number }[]
}
const w = useWorkspaceStore()
const auth = useAuthStore()
const route = useRoute(),
  router = useRouter(),
  resources = useResourceStore()
const requests = ref<PrintRequest[]>([]),
  selected = ref<PrintRequest | null>(null)
const filter = ref('pending'),
  error = ref(''),
  busy = ref(false),
  reason = ref(''),
  position = ref(0)
const visible = computed(() =>
  requests.value.filter((r) => !filter.value || r.status === filter.value),
)
const label = computed(() => selected.value?.labels[position.value])
let stopped = false,
  generation = 0
async function load(force = false) {
  const ticket = ++generation,
    actor = auth.user?.id,
    id = typeof route.params.id === 'string' ? route.params.id : ''
  const current = () => !stopped && ticket === generation && auth.user?.id === actor
  try {
    if (id) {
      const detail = await resources.get<PrintRequest>(`/requests/${encodeURIComponent(id)}`, {
        ttl: 5000,
        force,
      })
      if (!current() || detail.id !== route.params.id) return
      if (JSON.stringify(selected.value) !== JSON.stringify(detail)) selected.value = detail
    } else {
      const data = await resources.get<PrintRequest[]>('/requests', { ttl: 5000, force })
      if (!current()) return
      if (JSON.stringify(requests.value) !== JSON.stringify(data)) requests.value = data
      selected.value = null
    }
    error.value = ''
  } catch (e) {
    if (current()) error.value = errorMessage(e)
  }
}
useLiveRefresh(async () => {
  if (!selected.value || selected.value.status === 'pending') await load()
}, 5000)
async function decide(approve: boolean) {
  if (!selected.value || busy.value) return
  if (
    !(await confirmAction(
      approve
        ? 'Approve this request? Its saved labels will enter the print queue and may print automatically.'
        : 'Reject this print request?',
    ))
  )
    return
  busy.value = true
  error.value = ''
  try {
    await api(
      `/requests/${selected.value.id}/${approve ? 'approve' : 'reject'}`,
      'POST',
      approve ? {} : { reason: reason.value },
    )
    reason.value = ''
    resources.invalidate(['/requests'])
    await load(true)
    await w.refresh()
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}
watch(
  () => route.params.id,
  () => {
    generation++
    selected.value = null
    position.value = 0
    reason.value = ''
    void load()
  },
)
onUnmounted(() => {
  stopped = true
  generation++
})
</script>
<template>
  <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
  <section v-if="selected" class="panel form-stack">
    <div class="section-heading">
      <h2>{{ selected.owner_name || 'Print request' }}</h2>
      <span class="badge">{{ selected.status }}</span>
    </div>
    <p>
      {{ w.destinationName(selected.destination_id) }} · {{ date(selected.created_at) }} ·
      {{ selected.labels.reduce((total, item) => total + item.copies, 0) }} copies
    </p>
    <p v-if="selected.status === 'pending'" class="help">
      These labels are saved for review and have not entered the print queue.
    </p>
    <div v-if="label" class="request-preview">
      <img
        :key="`${selected.id}-${position}`"
        :src="`/api/requests/${selected.id}/labels/${position}/preview`"
        :alt="`Requested label ${position + 1}`"
        :style="{ aspectRatio: `${label.length_mm} / ${label.width_mm}` }"
      />
      <p>{{ label.length_mm }} × {{ label.width_mm }} mm · {{ label.copies }} copies</p>
      <div class="row">
        <button :disabled="!position" @click="position--">Previous label</button
        ><span>{{ position + 1 }} / {{ selected.labels.length }}</span
        ><button :disabled="position >= selected.labels.length - 1" @click="position++">
          Next label
        </button>
      </div>
    </div>
    <p v-if="selected.reason" class="alert warning">{{ selected.reason }}</p>
    <template
      v-if="selected.status === 'pending' && auth.atLeast(selected.destination_id, 'moderator')"
    >
      <label>Reason for rejection<input v-model="reason" maxlength="1000" /></label>
      <div class="row wrap">
        <button class="primary" :disabled="busy" @click="decide(true)">Approve and queue</button
        ><button
          class="secondary danger-text"
          :disabled="busy || !reason.trim()"
          @click="decide(false)"
        >
          Reject request
        </button>
      </div>
    </template>
    <RouterLink v-if="selected.status === 'approved'" class="button secondary" to="/queue"
      >View print queue</RouterLink
    >
    <button class="text-button" @click="router.push('/requests')">Back to requests</button>
  </section>
  <section v-else class="panel">
    <div class="section-heading">
      <h2>{{ auth.any('moderator') ? 'Print requests' : 'Your print requests' }}</h2>
      <label
        >Request status<select v-model="filter">
          <option value="pending">Pending approval</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
          <option value="">All requests</option>
        </select></label
      >
    </div>
    <p v-if="!visible.length" class="empty">No {{ filter || 'print' }} requests.</p>
    <div v-for="request in visible" :key="request.id" class="list-row">
      <div>
        <strong>{{
          request.labels[0]
            ? Object.values(request.labels[0].payload).join(' · ') || 'Image label'
            : 'Print request'
        }}</strong
        ><small
          >{{ request.owner_name ? request.owner_name + ' · ' : ''
          }}{{ w.destinationName(request.destination_id) }} · {{ date(request.created_at) }}</small
        >
      </div>
      <span class="badge">{{ request.status }}</span
      ><RouterLink class="button secondary" :to="`/requests/${request.id}`"
        >View request</RouterLink
      >
    </div>
  </section>
</template>
<style scoped>
.request-preview {
  padding: 24px;
  border-radius: 12px;
  background: var(--surface-secondary);
  text-align: center;
}
.request-preview img {
  max-width: 100%;
  max-height: 320px;
  object-fit: contain;
  image-rendering: pixelated;
}
.request-preview .row {
  justify-content: center;
  flex-wrap: wrap;
}
.list-row {
  flex-wrap: wrap;
  gap: 12px;
}
.list-row strong {
  overflow-wrap: anywhere;
}
</style>
