<script setup lang="ts">
import type { SocketType } from '../templates/logicGraph'
defineProps<{
  type: SocketType
  label: string
  selected: boolean
  connected: boolean
  node: string
  port: number
  disabled?: boolean
}>()
defineEmits<{ choose: []; start: [event: PointerEvent] }>()
</script>
<template>
  <button
    type="button"
    class="logic-socket"
    :disabled="disabled"
    :class="[`socket-${type}`, { connected }]"
    :aria-label="label"
    :aria-pressed="selected"
    :data-node="node"
    :data-port="port"
    @click.stop="$emit('choose')"
    @pointerdown.stop="$emit('start', $event)"
  >
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle v-if="type === 'text'" cx="12" cy="12" r="7" />
      <path v-else-if="type === 'number'" d="M12 3 21 12 12 21 3 12Z" />
      <rect v-else-if="type === 'boolean'" x="5" y="5" width="14" height="14" />
      <path v-else-if="type === 'image'" d="M12 3 22 20H2Z" />
      <path v-else d="m7 4-5 8 5 8h10l5-8-5-8Z" />
    </svg>
  </button>
</template>
<style scoped>
.logic-socket {
  width: 36px;
  height: 36px;
  min-height: 36px;
  padding: 6px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--ink);
  flex-shrink: 0;
}
.logic-socket svg {
  display: block;
  width: 22px;
  height: 22px;
  fill: var(--surface-deepest);
  stroke: currentColor;
  stroke-width: 2;
}
.logic-socket:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.socket-text {
  color: var(--ink);
}
.socket-number {
  color: var(--accent-hover);
}
.socket-boolean {
  color: var(--success-text);
}
.socket-image {
  color: var(--link-hover);
}
.connected svg {
  fill: currentColor;
}
.logic-socket[aria-pressed='true'] {
  outline: 2px solid var(--ink);
  outline-offset: 1px;
}
</style>
