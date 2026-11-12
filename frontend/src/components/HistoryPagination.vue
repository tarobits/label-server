<script setup lang="ts">
defineProps<{ page: number; pages: number | null; loading: boolean; label: string }>()
defineEmits<{ change: [page: number] }>()
</script>
<template>
  <nav class="pagination" :aria-label="label">
    <span aria-live="polite">{{
      pages === null
        ? $t('historyPagination.page', { page })
        : $t('historyPagination.pageOf', { page, pages })
    }}</span>
    <button class="secondary" :disabled="page <= 1 || loading" @click="$emit('change', 1)">
      {{ $t('historyPagination.latest') }}
    </button>
    <button class="secondary" :disabled="page <= 1 || loading" @click="$emit('change', page - 1)">
      {{ $t('common.previous') }}
    </button>
    <button
      class="secondary"
      :disabled="pages === null || page >= pages || loading"
      @click="$emit('change', page + 1)"
    >
      {{ $t('common.next') }}
    </button>
  </nav>
</template>
