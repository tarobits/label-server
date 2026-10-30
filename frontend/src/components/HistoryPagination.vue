<script setup lang="ts">
defineProps<{ page: number; pages: number | null; loading: boolean; label: string }>()
defineEmits<{ change: [page: number] }>()
</script>
<template>
  <nav class="pagination" :aria-label="label">
    <span aria-live="polite"
      >Page {{ page }}<template v-if="pages !== null"> of {{ pages }}</template></span
    >
    <button class="secondary" :disabled="page <= 1 || loading" @click="$emit('change', 1)">
      Latest
    </button>
    <button class="secondary" :disabled="page <= 1 || loading" @click="$emit('change', page - 1)">
      Previous
    </button>
    <button
      class="secondary"
      :disabled="pages === null || page >= pages || loading"
      @click="$emit('change', page + 1)"
    >
      Next
    </button>
  </nav>
</template>
