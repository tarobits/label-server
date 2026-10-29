<script setup lang="ts">
import type { GroupRights, Membership } from '../auth'
const props = defineProps<{ modelValue: Membership; subject: string; invitation?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: Membership] }>()
const kinds = ['templates', 'images', 'fonts'] as const
const rights = [
  { key: 'can_create', title: 'Create', action: 'create group' },
  { key: 'can_edit_others', title: 'Edit others', action: 'edit others’' },
  { key: 'can_delete_others', title: 'Delete others', action: 'delete others’' },
] as const
function checked(kind: (typeof kinds)[number], key: keyof GroupRights) {
  return !!(kind === 'templates' ? props.modelValue[key] : props.modelValue[kind]?.[key])
}
function update(kind: (typeof kinds)[number], key: keyof GroupRights, event: Event) {
  const value = (event.target as HTMLInputElement).checked
  emit(
    'update:modelValue',
    kind === 'templates'
      ? { ...props.modelValue, [key]: value }
      : {
          ...props.modelValue,
          [kind]: {
            can_create: false,
            can_edit_others: false,
            can_delete_others: false,
            ...props.modelValue[kind],
            [key]: value,
          },
        },
  )
}
function label(kind: (typeof kinds)[number], right: (typeof rights)[number]) {
  return props.invitation
    ? `${right.title === 'Create' ? 'Create' : right.title.replace('others', 'others’')} ${kind} in ${props.subject}`
    : `Allow ${props.subject} to ${right.action} ${kind}`
}
</script>
<template>
  <div class="group-rights">
    <div class="rights-row rights-heading" aria-hidden="true">
      <span>Resource</span><span v-for="right in rights" :key="right.key">{{ right.title }}</span>
    </div>
    <div v-for="kind in kinds" :key="kind" class="rights-row">
      <strong>{{
        kind === 'templates' ? 'Templates' : kind === 'images' ? 'Images' : 'Fonts'
      }}</strong>
      <label v-for="right in rights" :key="right.key" class="checkbox"
        ><input
          type="checkbox"
          :checked="checked(kind, right.key)"
          :aria-label="label(kind, right)"
          @change="update(kind, right.key, $event)"
        /><span>{{ right.title }}</span></label
      >
    </div>
  </div>
</template>
<style scoped>
.group-rights {
  padding: 12px 0 0 28px;
}
.rights-row {
  display: grid;
  grid-template-columns: minmax(85px, 1fr) repeat(3, minmax(72px, 100px));
  gap: 8px;
  align-items: center;
  padding: 6px 0;
  font-size: 13px;
}
.rights-heading {
  font-size: 12px;
  color: var(--muted);
}
.rights-heading span:not(:first-child) {
  text-align: center;
}
.checkbox {
  justify-content: center;
  min-height: 32px;
}
.checkbox span {
  display: none;
}
@media (max-width: 600px) {
  .rights-heading {
    display: none;
  }
  .rights-row {
    grid-template-columns: minmax(0, 1fr);
  }
  .checkbox {
    justify-content: flex-start;
  }
  .checkbox span {
    display: inline;
  }
}
</style>
