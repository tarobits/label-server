<script setup lang="ts">
import { oppositeSubmissionPermission } from '../printing/printerPermissions'
const props = defineProps<{
  allowed: string[]
  denied: string[]
  options: { id: string; label: string }[]
  disabled?: boolean
  hints?: Record<string, string>
}>()
const emit = defineEmits<{ change: [allowed: string[], denied: string[]] }>()
function change(permission: string, effect: string) {
  let allowed = props.allowed.filter((value) => value !== permission)
  const denied = props.denied.filter((value) => value !== permission)
  if (effect === 'allow') {
    allowed = allowed.filter((value) => value !== oppositeSubmissionPermission(permission))
    allowed.push(permission)
  }
  if (effect === 'deny') denied.push(permission)
  emit('change', allowed, denied)
}
</script>
<template>
  <div class="permission-rules">
    <div v-for="option in options" :key="option.id" class="permission-rule">
      <label
        >{{ option.label
        }}<select
          :disabled="disabled"
          :value="
            denied.includes(option.id) ? 'deny' : allowed.includes(option.id) ? 'allow' : 'inherit'
          "
          @change="change(option.id, ($event.target as HTMLSelectElement).value)"
        >
          <option value="inherit">{{ $t('common.inherit') }}</option>
          <option value="allow">{{ $t('common.allow') }}</option>
          <option value="deny">{{ $t('common.deny') }}</option>
        </select></label
      >
      <p v-if="hints?.[option.id]" class="muted">{{ hints[option.id] }}</p>
    </div>
  </div>
</template>
<style scoped>
.permission-rules {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px 24px;
}
.permission-rule {
  min-width: 0;
}
.permission-rule p {
  margin: 6px 0 0;
  font-size: 0.85rem;
}
@media (max-width: 600px) {
  .permission-rules {
    grid-template-columns: 1fr;
  }
}
</style>
