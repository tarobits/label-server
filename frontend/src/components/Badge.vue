<script setup lang="ts">
import { stateLabel } from '../workspace'
defineProps<{ state: string }>()
</script>
<template>
  <span class="badge status-badge" :class="state">{{ stateLabel(state) }}</span>
</template>
