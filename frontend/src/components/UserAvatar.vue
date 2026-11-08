<script setup lang="ts">
import { ref, watch } from 'vue'
const props = defineProps<{ username: string; src?: string | null }>()
const failed = ref(false)
watch(
  () => props.src,
  () => (failed.value = false),
)
</script>

<template>
  <span class="user-avatar" aria-hidden="true">
    <img v-if="src && !failed" :src="src" alt="" @error="failed = true" />
    <span v-else>{{ Array.from(username.trim())[0]?.toLocaleUpperCase() ?? '?' }}</span>
  </span>
</template>

<style scoped>
.user-avatar {
  display: inline-grid;
  place-items: center;
  width: 64px;
  height: 64px;
  flex-shrink: 0;
  overflow: hidden;
  border-radius: 12px;
  background: var(--surface-deepest);
  color: var(--ink);
  font-size: 1.75rem;
  font-weight: 600;
}
.user-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
</style>
