<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api, errorMessage } from '../api'
import { useAuthStore } from '../auth'
import { useLiveRefresh } from '../live'
import { date } from '../workspace'
import AdminDialog from './AdminDialog.vue'
import Icon from './Icon.vue'
interface Notice {
  id: string
  title: string
  message: string
  path: string
  created_at: number
  read_at: number | null
}
const auth = useAuthStore(),
  router = useRouter()
const open = ref(false),
  busy = ref(false),
  error = ref(''),
  unreadOnly = ref(false)
const items = ref<Notice[]>([]),
  unread = ref(0),
  total = ref(0),
  offset = ref(0)
let sequence = 0
async function refresh() {
  const ticket = ++sequence
  if (!auth.user) return
  try {
    const result = await api<{ items: Notice[]; unread: number; total: number }>(
      `/inbox?offset=${open.value ? offset.value : 0}&limit=${open.value ? 20 : 1}&unread_only=${open.value && unreadOnly.value}`,
    )
    if (ticket !== sequence) return
    unread.value = result.unread
    total.value = result.total
    if (open.value) items.value = result.items
    error.value = ''
  } catch (e) {
    if (open.value && ticket === sequence) error.value = errorMessage(e)
  }
}
async function show() {
  open.value = true
  offset.value = 0
  await refresh()
  try {
    await api('/inbox/opened', 'POST', {})
  } catch (e) {
    error.value = errorMessage(e)
  }
}
async function mark(notice?: Notice, read = true) {
  busy.value = true
  try {
    await api(`/inbox/${notice ? `${notice.id}/` : ''}read`, 'PUT', { read })
    await refresh()
    return true
  } catch (e) {
    error.value = errorMessage(e)
    return false
  } finally {
    busy.value = false
  }
}
async function visit(notice: Notice) {
  if (!(await mark(notice))) return
  open.value = false
  await router.push(notice.path.startsWith('/#/') ? notice.path.slice(2) : '/')
}
watch(unreadOnly, () => {
  offset.value = 0
  void refresh()
})
watch(offset, refresh)
watch(
  () => auth.user?.id,
  () => {
    sequence++
    open.value = false
    unread.value = 0
    items.value = []
    void refresh()
  },
)
useLiveRefresh(refresh)
</script>
<template>
  <button
    class="notification-bell text-button"
    :aria-label="unread ? `Notifications, ${unread} unread` : 'Notifications'"
    :aria-expanded="open"
    @click="show"
  >
    <Icon name="bell" /><Transition name="notice"
      ><span v-if="unread" class="notification-count motion-reveal">{{
        unread > 99 ? '99+' : unread
      }}</span></Transition
    >
  </button>
  <AdminDialog :open="open" title="Notifications" :busy="busy" @close="open = false">
    <div class="row wrap spread">
      <label class="checkbox"><input v-model="unreadOnly" type="checkbox" />Unread only</label
      ><button class="text-button" :disabled="busy || !unread" @click="mark()">
        Mark all read
      </button>
    </div>
    <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
    <p v-if="!items.length && !error" class="empty">
      {{ unreadOnly ? 'No unread notifications.' : 'No notifications yet.' }}
    </p>
    <TransitionGroup name="notice" tag="div" class="notification-list">
      <article v-for="notice in items" :key="notice.id" :class="{ unread: !notice.read_at }">
        <button class="notification-content text-button" @click="visit(notice)">
          <strong>{{ notice.title }}</strong
          ><span>{{ notice.message }}</span
          ><small>{{ date(notice.created_at) }}</small>
        </button>
        <button class="text-button" :disabled="busy" @click="mark(notice, notice.read_at === null)">
          {{ notice.read_at ? 'Mark unread' : 'Mark read' }}
        </button>
      </article>
    </TransitionGroup>
    <div v-if="total > 20" class="row spread">
      <button
        class="secondary"
        :disabled="offset === 0 || busy"
        @click="offset = Math.max(0, offset - 20)"
      >
        Previous</button
      ><span>{{ offset + 1 }}–{{ Math.min(offset + 20, total) }} of {{ total }}</span
      ><button class="secondary" :disabled="offset + 20 >= total || busy" @click="offset += 20">
        Next
      </button>
    </div>
  </AdminDialog>
</template>
<style scoped>
.notification-bell {
  position: relative;
  min-width: 44px;
  min-height: 44px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
}
.notification-count {
  position: absolute;
  right: -2px;
  top: 0;
  background: var(--accent);
  color: white;
  border-radius: 12px;
  font-size: 10px;
  line-height: 16px;
  min-width: 16px;
  padding: 0 3px;
}
.notification-list article {
  padding: 1rem 0;
  border-bottom: 1px solid var(--line);
}
.notification-list article:last-child {
  border-bottom: 0;
}
.notification-content {
  display: grid;
  justify-items: start;
  justify-content: stretch;
  gap: 0.5rem;
  text-align: left;
  width: 100%;
  color: var(--ink);
  padding: 0;
  white-space: normal;
  overflow-wrap: anywhere;
}
.notification-content span {
  font-weight: 400;
}
.notification-content small {
  color: var(--text-secondary);
  font-weight: 400;
}
.unread .notification-content strong::before {
  content: '';
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  margin-right: 0.5rem;
}
</style>
