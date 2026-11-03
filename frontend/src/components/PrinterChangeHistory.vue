<script setup lang="ts">
import { reactive } from 'vue'
import { useHistoryPage } from '../history'
import { date } from '../workspace'
import type { PrinterChange } from '../types'
import HistoryPagination from './HistoryPagination.vue'
import MotionSurface from './MotionSurface.vue'
const history = reactive(useHistoryPage<PrinterChange>('printer-changes'))
</script>
<template>
  <section class="panel" aria-labelledby="printer-change-title" :aria-busy="history.loading">
    <div class="section-heading">
      <h2 id="printer-change-title">Printer changes</h2>
      <span class="muted">{{ history.total }} changes</span>
    </div>
    <HistoryPagination
      v-bind="history.pagination"
      label="Printer change pages"
      @change="history.go($event)"
    />
    <Transition name="notice"
      ><div v-if="history.error" class="alert danger motion-reveal" role="alert">
        {{ history.error
        }}<button class="secondary small" :disabled="history.loading" @click="history.retry()">
          Retry
        </button>
      </div></Transition
    >
    <Transition name="notice"
      ><p v-if="history.loading" class="muted motion-reveal" role="status">
        Loading page {{ history.page }}…
      </p></Transition
    >
    <p v-if="!history.items.length && !history.loading && !history.error" class="empty compact">
      No printer changes yet.
    </p>
    <MotionSurface :identity="String(history.loadedPage)" :order="history.loadedPage">
      <article v-for="change in history.items" :key="change.id" class="list-row">
        <div class="grow change-record">
          <strong>{{ change.source.name }} → {{ change.target.name }}</strong>
          <small
            >{{ change.actor.name }} · {{ date(change.created_at) }} ·
            {{ change.copy_ids.length }} copies · {{ change.job_name }}</small
          >
          <small v-if="change.previous_assignment"
            >Previously assigned to {{ change.previous_assignment.name }}</small
          >
          <p v-if="change.reason">{{ change.reason }}</p>
        </div>
      </article>
    </MotionSurface>
    <HistoryPagination
      v-if="history.items.length"
      v-bind="history.pagination"
      label="Printer change pages, bottom"
      @change="history.go($event)"
    />
  </section>
</template>
<style scoped>
.change-record {
  min-width: 0;
  overflow-wrap: anywhere;
}
.change-record p {
  margin-bottom: 0;
  white-space: pre-wrap;
}
</style>
