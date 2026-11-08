<script setup lang="ts">
import { reactive } from 'vue'
import { storeToRefs } from 'pinia'
import { useWorkspaceStore, date } from '../workspace'
import { useAuthStore } from '../auth'
import { useHistoryPage } from '../history'
import type { Notice } from '../types'
import Badge from '../components/Badge.vue'
import HistoryPagination from '../components/HistoryPagination.vue'
import MotionSurface from '../components/MotionSurface.vue'
const auth = useAuthStore()
const { overview } = storeToRefs(useWorkspaceStore())
const notices = reactive(useHistoryPage<Notice>('notifications', () => !!auth.user?.is_admin))
function deliveryState(delivery: NonNullable<Notice['deliveries']>[number]) {
  return delivery.cancelled
    ? 'cancelled'
    : delivery.delivered_at
      ? 'delivered'
      : delivery.last_error
        ? 'retrying'
        : 'pending'
}
function noticeState(notice: Notice) {
  return notice.cancelled
    ? 'cancelled'
    : notice.delivered_at
      ? 'delivered'
      : notice.last_error
        ? 'retrying'
        : 'pending'
}
</script>
<template>
  <section
    v-if="auth.user?.is_admin"
    class="panel"
    aria-labelledby="notification-history-title"
    :aria-busy="notices.loading"
  >
    <div class="section-heading">
      <h2 id="notification-history-title">Notifications</h2>
      <span class="badge" :class="overview.notifications_enabled ? 'printed' : 'queued'">{{
        overview.notifications_enabled ? 'Delivery enabled' : 'Delivery not configured'
      }}</span>
    </div>
    <p v-if="!overview.notifications_enabled" class="help">
      Add a notification endpoint in Administration to deliver alerts.
    </p>
    <HistoryPagination
      v-bind="notices.pagination"
      label="Notification pages"
      @change="notices.go($event)"
    />
    <Transition name="notice"
      ><div v-if="notices.error" class="alert danger motion-reveal" role="alert">
        {{ notices.error }}
        <button class="secondary small" :disabled="notices.loading" @click="notices.retry()">
          Retry
        </button>
      </div></Transition
    >
    <Transition name="notice"
      ><p v-if="notices.loading" role="status" class="muted motion-reveal">
        Loading page {{ notices.page }}…
      </p></Transition
    >
    <div v-if="!notices.items.length && !notices.loading && !notices.error" class="empty compact">
      All quiet.
    </div>
    <MotionSurface
      :identity="String(notices.loadedPage)"
      :order="notices.loadedPage"
      class="history-items"
      :class="{ 'history-loading': notices.loading }"
    >
      <article v-for="notice in notices.items" :key="notice.id" class="notification">
        <div class="row spread">
          <strong>{{ notice.title }}</strong
          ><Badge :state="noticeState(notice)" />
        </div>
        <p>{{ notice.message }}</p>
        <ul
          v-if="notice.deliveries?.length"
          class="notice-deliveries"
          aria-label="Endpoint deliveries"
        >
          <li v-for="(delivery, index) in notice.deliveries" :key="index">
            <div class="row spread">
              <strong>{{ delivery.endpoint_name }}</strong>
              <Badge :state="deliveryState(delivery)" />
            </div>
            <small
              >{{ delivery.attempts }} delivery attempts<span v-if="delivery.delivered_at">
                · {{ date(delivery.delivered_at) }}</span
              ><span v-if="delivery.last_error"> · {{ delivery.last_error }}</span></small
            >
          </li>
        </ul>
        <small
          >{{ date(notice.created_at) }} · {{ notice.attempts }} delivery attempts<span
            v-if="notice.last_error"
          >
            · {{ notice.last_error }}</span
          ></small
        ><a v-if="notice.path.startsWith('/#/')" :href="notice.path">Open details →</a>
      </article>
    </MotionSurface>
    <HistoryPagination
      v-if="notices.items.length"
      v-bind="notices.pagination"
      label="Notification pages, bottom"
      @change="notices.go($event)"
    />
  </section>
</template>
<style scoped>
.history-items {
  transition: opacity var(--motion-state) var(--motion-ease);
}
.history-loading {
  opacity: 0.55;
  pointer-events: none;
}
.activity-batch {
  padding-bottom: 20px;
  border-bottom: 1px solid var(--line);
}
.activity-batch:last-child {
  padding-bottom: 0;
  border-bottom: 0;
}
.activity-batch > .list-row {
  border-bottom: 0;
  padding-bottom: 0;
}
.batch-attributions {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(320px, 100%), 1fr));
  gap: 12px;
}
.batch-attribution {
  background: var(--surface-secondary);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 14px;
}
.attribution-count {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--text-secondary);
}
.notice-deliveries {
  display: grid;
  gap: 10px;
  margin: 12px 0;
  padding: 0;
  list-style: none;
}
.notice-deliveries li {
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
}
.notice-deliveries strong {
  min-width: 0;
  overflow-wrap: anywhere;
  font-size: 12px;
}
</style>
