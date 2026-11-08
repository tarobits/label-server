<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errorMessage } from '../api'
import { useAuthStore } from '../auth'
import { useWorkspaceStore, date } from '../workspace'
import { confirmAction } from '../confirmation'
import { useLiveRefresh } from '../live'
import { useResourceStore } from '../stores/resources'
import ChangeCopies from '../components/ChangeCopies.vue'
interface PrintRequest {
  id: string
  owner_id: string
  owner_name?: string
  destination_id: string
  status: 'pending' | 'approved' | 'rejected'
  revision: number
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
  loading = ref(true),
  reason = ref(''),
  position = ref(0),
  previewFailed = ref(false),
  previewAttempt = ref(0)
const changedElsewhere = ref(false)
const visible = computed(() =>
  requests.value.filter((r) => !filter.value || r.status === filter.value),
)
const label = computed(() => selected.value?.labels[position.value])
const copies = computed(
  () => selected.value?.labels.reduce((total, item) => total + item.copies, 0) ?? 0,
)
watch([() => selected.value?.id, position], () => {
  previewFailed.value = false
  previewAttempt.value = 0
})
function retryPreview() {
  previewAttempt.value++
  previewFailed.value = false
}
let stopped = false,
  generation = 0
async function load(force = false) {
  const ticket = ++generation,
    actor = auth.user?.id,
    id = typeof route.params.id === 'string' ? route.params.id : ''
  const current = () => !stopped && ticket === generation && auth.user?.id === actor
  loading.value = true
  try {
    if (id) {
      const detail = await resources.get<PrintRequest>(`/requests/${encodeURIComponent(id)}`, {
        ttl: 5000,
        force,
      })
      if (!current() || detail.id !== route.params.id) return
      if (
        !force &&
        selected.value?.id === detail.id &&
        selected.value.revision !== detail.revision
      ) {
        changedElsewhere.value = true
        error.value = ''
        return
      }
      if (JSON.stringify(selected.value) !== JSON.stringify(detail)) selected.value = detail
      changedElsewhere.value = false
    } else {
      const data = await resources.get<PrintRequest[]>('/requests', { ttl: 5000, force })
      if (!current()) return
      if (JSON.stringify(requests.value) !== JSON.stringify(data)) requests.value = data
      selected.value = null
    }
    error.value = ''
  } catch (e) {
    if (current()) error.value = errorMessage(e)
  } finally {
    if (current()) loading.value = false
  }
}
useLiveRefresh(async () => {
  if (!selected.value || selected.value.status === 'pending') await load()
}, 5000)
async function decide(approve: boolean) {
  if (!selected.value || busy.value || changedElsewhere.value) return
  const reviewed = { id: selected.value.id, revision: selected.value.revision }
  if (
    !(await confirmAction(
      approve
        ? 'Approve this request? Its saved labels will enter the print queue and may print automatically.'
        : 'Reject this print request?',
    ))
  )
    return
  if (
    selected.value?.id !== reviewed.id ||
    selected.value.revision !== reviewed.revision ||
    changedElsewhere.value
  )
    return
  busy.value = true
  error.value = ''
  try {
    await api(
      `/requests/${reviewed.id}/${approve ? 'approve' : 'reject'}`,
      'POST',
      approve ? { expected_revision: reviewed.revision } : { reason: reason.value },
    )
    reason.value = ''
    changedElsewhere.value = false
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
    error.value = ''
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
  <p v-if="error" class="alert danger" role="alert">
    {{ error }}
    <button class="text-button" :disabled="loading" @click="load(true)">Retry</button>
  </p>
  <section v-if="selected" class="panel form-stack">
    <Transition name="notice"
      ><p v-if="changedElsewhere" class="alert warning motion-reveal" role="alert">
        This request changed. Reload to review the latest version.
        <button class="text-button" :disabled="loading || busy" @click="load(true)">
          Reload request
        </button>
      </p></Transition
    >
    <div class="section-heading">
      <h2>{{ selected.owner_name || 'Print request' }}</h2>
      <span class="badge">{{ selected.status }}</span>
    </div>
    <p>
      {{ w.destinationName(selected.destination_id) }} · {{ date(selected.created_at) }} ·
      {{ copies }} {{ copies === 1 ? 'copy' : 'copies' }}
    </p>
    <p v-if="selected.status === 'pending'" class="help">
      These labels are saved for review and have not entered the print queue.
    </p>
    <div v-if="label" class="request-preview">
      <p v-if="previewFailed" class="help" role="status">
        Preview unavailable.
        <button type="button" class="small secondary" @click="retryPreview">Retry preview</button>
      </p>
      <img
        v-else
        :key="`${selected.id}-${position}-${previewAttempt}`"
        :src="`/api/requests/${selected.id}/labels/${position}/preview${previewAttempt ? `?retry=${previewAttempt}` : ''}`"
        :alt="`Requested label ${position + 1}`"
        :style="{ '--label-ratio': label.length_mm / label.width_mm }"
        @error="previewFailed = true"
      />
      <p>
        {{ label.length_mm }} × {{ label.width_mm }} mm · {{ label.copies }}
        {{ label.copies === 1 ? 'copy' : 'copies' }}
      </p>
      <ChangeCopies
        v-if="
          selected.status === 'pending' &&
          (selected.owner_id === auth.user?.id ||
            auth.printer(selected.destination_id, 'manage_queue'))
        "
        :url="`/requests/${selected.id}/labels/${position}/copies`"
        :copies="label.copies"
        :revision="selected.revision"
        :disabled="busy || changedElsewhere"
        @changed="load(true)"
      />
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
      v-if="
        selected.status === 'pending' && auth.printer(selected.destination_id, 'approve_requests')
      "
    >
      <label>Reason for rejection<input v-model="reason" maxlength="1000" /></label>
      <div class="row wrap">
        <button class="primary" :disabled="busy || changedElsewhere" @click="decide(true)">
          Approve and queue</button
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
  <section v-else-if="!route.params.id" class="panel">
    <div class="section-heading">
      <h2>{{ auth.anyPrinter('approve_requests') ? 'Print requests' : 'Your print requests' }}</h2>
      <label
        >Request status<select v-model="filter">
          <option value="pending">Pending approval</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
          <option value="">All requests</option>
        </select></label
      >
    </div>
    <p v-if="loading && !requests.length" class="empty" role="status">Loading requests…</p>
    <p v-else-if="!visible.length && !error" class="empty">No {{ filter || 'print' }} requests.</p>
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
  <p v-else-if="loading" class="panel empty" role="status">Loading request…</p>
</template>
<style scoped>
.request-preview {
  padding: 24px;
  border-radius: 12px;
  background: var(--surface-secondary);
  text-align: center;
}
.request-preview img {
  display: block;
  width: min(100%, calc(320px * var(--label-ratio)));
  height: auto;
  aspect-ratio: var(--label-ratio);
  margin-inline: auto;
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
