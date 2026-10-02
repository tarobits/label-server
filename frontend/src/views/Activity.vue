<script setup lang="ts">
import { workspace as w, date, metres } from '../workspace'
import Badge from '../components/Badge.vue'
const { batches, notices, status } = w
function noticeState(notice: (typeof notices.value)[number]) {
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
  <section class="panel">
    <div class="section-heading">
      <h2>Print batches</h2>
      <span class="muted">Latest 100 attempts</span>
    </div>
    <div v-if="!batches.length" class="empty compact">No batches yet.</div>
    <div v-for="batch in batches" :key="batch.id" class="list-row">
      <div class="grow">
        <strong>{{ w.cartridgeName(batch.cartridge_id) }}</strong
        ><small
          >{{ date(batch.created_at) }} ·
          {{ batch.consumed_mm === null ? 'Estimated' : 'Consumed' }}
          {{ metres(batch.consumed_mm ?? batch.estimated_mm) }}</small
        ><small v-if="batch.shortage_warning" class="danger-text"
          >Batch estimate exceeded remaining tape.</small
        >
      </div>
      <Badge :state="batch.state" /><RouterLink :to="`/batches/${batch.id}`">{{
        batch.state === 'needs_review' ? 'Review batch →' : 'Details →'
      }}</RouterLink>
    </div>
  </section>
  <section class="panel">
    <div class="section-heading">
      <h2>Notifications</h2>
      <span class="badge" :class="status?.notifications_enabled ? 'printed' : 'queued'">{{
        status?.notifications_enabled ? 'ntfy enabled' : 'ntfy not configured'
      }}</span>
    </div>
    <p v-if="!status?.notifications_enabled" class="help">
      Alerts are saved here. Configure ntfy to deliver them to your devices.
    </p>
    <div v-if="!notices.length" class="empty compact">
      All quiet. Alerts and tape reminders will appear here.
    </div>
    <article v-for="notice in notices" :key="notice.id" class="notification">
      <div class="row spread">
        <strong>{{ notice.title }}</strong
        ><Badge :state="noticeState(notice)" />
      </div>
      <p>{{ notice.message }}</p>
      <small
        >{{ date(notice.created_at) }} · {{ notice.attempts }} delivery attempts<span
          v-if="notice.last_error"
        >
          · {{ notice.last_error }}</span
        ></small
      ><a v-if="notice.path.startsWith('/#/')" :href="notice.path">Open details →</a>
    </article>
  </section>
</template>
