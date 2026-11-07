<script setup lang="ts">
import { computed, nextTick, onMounted, ref, useId, watch } from 'vue'
import { api, errorMessage } from '../api'
import { useAuthStore } from '../auth'
import { confirmAction } from '../confirmation'
import ExpandableContent from './ExpandableContent.vue'

const props = defineProps<{ refreshKey: number }>()
interface LoginSession {
  id: string
  current: boolean
  created_at: number
  last_seen_at: number | null
  ip_address: string | null
  location: string | null
  user_agent: string | null
  device: string
  browser: string
  os: string
}
const auth = useAuthStore()
const sessions = ref<LoginSession[]>([])
const expanded = ref<string[]>([])
const busy = ref(false),
  loaded = ref(false),
  error = ref(''),
  success = ref('')
const refreshButton = ref<HTMLButtonElement | null>(null)
const prefix = useId()
const hasOthers = computed(() => sessions.value.some((session) => !session.current))
const date = (value: number | null) =>
  value === null ? 'Not recorded' : new Date(value * 1000).toLocaleString()
async function load() {
  sessions.value = await api<LoginSession[]>('/auth/sessions')
  loaded.value = true
}
async function refresh() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await load()
  } catch (cause) {
    error.value = errorMessage(cause)
  } finally {
    busy.value = false
  }
}
async function revoke(session?: LoginSession) {
  if (busy.value) return
  const message = session
    ? `Sign out ${session.current ? 'this session' : `${session.browser} on ${session.device}`}? Its push notifications will also stop.`
    : 'Sign out all other sessions? Their push notifications will also stop.'
  if (!(await confirmAction(message, session ? 'Sign out' : 'Sign out other sessions'))) return
  busy.value = true
  error.value = ''
  success.value = ''
  try {
    if (session?.current) {
      await auth.logout()
      return
    }
    await api(`/auth/sessions/${session?.id ?? 'others'}`, 'DELETE')
    await load()
    success.value = session ? 'Session signed out.' : 'Other sessions signed out.'
  } catch (cause) {
    error.value = errorMessage(cause)
  } finally {
    busy.value = false
  }
  await nextTick()
  refreshButton.value?.focus()
}
function toggle(id: string) {
  expanded.value = expanded.value.includes(id)
    ? expanded.value.filter((value) => value !== id)
    : [...expanded.value, id]
}
onMounted(refresh)
watch(() => props.refreshKey, refresh)
</script>

<template>
  <div class="account-sessions">
    <div class="row wrap session-heading">
      <h2>Logged-in sessions</h2>
      <button ref="refreshButton" class="text-button" :disabled="busy" @click="refresh">
        Refresh sessions
      </button>
    </div>
    <Transition name="notice"
      ><p v-if="error" class="alert danger motion-reveal" role="alert">{{ error }}</p></Transition
    >
    <Transition name="notice"
      ><p v-if="success" class="alert success motion-reveal" role="status">
        {{ success }}
      </p></Transition
    >
    <p v-if="!loaded && !error" class="help" role="status">Loading sessions…</p>
    <TransitionGroup name="notice" tag="ul" class="session-list" aria-label="Logged-in sessions">
      <li v-for="session in sessions" :key="session.id" class="motion-reveal">
        <div class="row wrap session-summary">
          <div class="session-name">
            <strong>{{ session.browser }} · {{ session.device }}</strong
            ><span v-if="session.current" class="badge">This session</span>
          </div>
          <button class="danger-text" :disabled="busy" @click="revoke(session)">Sign out</button>
        </div>
        <p class="session-seen">Last seen {{ date(session.last_seen_at) }}</p>
        <button
          class="text-button"
          :aria-expanded="expanded.includes(session.id)"
          :aria-controls="`${prefix}-${session.id}`"
          @click="toggle(session.id)"
        >
          Session details
        </button>
        <ExpandableContent :id="`${prefix}-${session.id}`" :open="expanded.includes(session.id)">
          <dl class="session-details">
            <dt>IP address</dt>
            <dd>{{ session.ip_address || 'Not recorded' }}</dd>
            <dt>Approximate location</dt>
            <dd>{{ session.location || 'Unavailable' }}</dd>
            <dt>Browser</dt>
            <dd>{{ session.browser }}</dd>
            <dt>Operating system</dt>
            <dd>{{ session.os }}</dd>
            <dt>Device</dt>
            <dd>{{ session.device }}</dd>
            <dt>First signed in</dt>
            <dd>{{ date(session.created_at) }}</dd>
            <dt>Last seen</dt>
            <dd>{{ date(session.last_seen_at) }}</dd>
            <dt>User agent</dt>
            <dd>{{ session.user_agent || 'Not recorded' }}</dd>
          </dl>
        </ExpandableContent>
      </li>
    </TransitionGroup>
    <button v-if="loaded" class="danger-text" :disabled="busy || !hasOthers" @click="revoke()">
      Sign out other sessions
    </button>
  </div>
</template>

<style scoped>
.session-heading {
  justify-content: space-between;
  margin-bottom: 16px;
}
.session-heading h2 {
  margin: 0;
}
.session-list {
  list-style: none;
  padding: 0;
  margin: 0 0 20px;
}
.session-list > li {
  padding-block: 20px;
  border-bottom: 1px solid var(--line);
}
.session-summary {
  justify-content: space-between;
  align-items: start;
}
.session-name {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  min-width: 0;
  overflow-wrap: anywhere;
}
.session-seen {
  color: var(--muted);
  margin: 8px 0;
}
.session-details {
  display: grid;
  grid-template-columns: minmax(130px, 1fr) minmax(0, 3fr);
  gap: 12px 20px;
  margin: 16px 0 0;
}
.session-details dt {
  color: var(--muted);
}
.session-details dd {
  margin: 0;
  overflow-wrap: anywhere;
  user-select: text;
}
@media (max-width: 600px) {
  .session-details {
    grid-template-columns: 1fr;
    gap: 4px;
  }
  .session-details dd + dt {
    margin-top: 10px;
  }
}
</style>
