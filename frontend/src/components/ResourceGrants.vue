<script setup lang="ts">
import { computed, ref } from 'vue'
import type { AccessCatalog, Grant, ResourceKind } from '../resourceAccess'
import { printerPermissionLabel } from '../printerPermissions'
const props = defineProps<{
  modelValue: Grant[]
  catalog: AccessCatalog
  kind: ResourceKind
  roles: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: Grant[]] }>()
const principal = ref('')
const people = computed(() => [
  ...props.catalog.users.map((user) => ({ value: `user:${user.id}`, label: user.name })),
  ...(props.roles
    ? props.catalog.roles.map((role) => ({ value: `role:${role.id}`, label: `Role: ${role.name}` }))
    : []),
])
const permissions = computed(() =>
  props.kind === 'location'
    ? [...props.catalog.permissions.printer, ...props.catalog.permissions.cartridge]
    : props.catalog.permissions[props.kind],
)
function matches(grant: Grant, permission: string) {
  return (
    `${grant.principal_kind}:${grant.principal_id}` === principal.value &&
    grant.permission === permission
  )
}
function toggle(permission: string, checked: boolean) {
  const next = props.modelValue.filter((grant) => !matches(grant, permission))
  const split = principal.value.indexOf(':')
  if (checked && split > 0)
    next.push({
      principal_kind: principal.value.slice(0, split) as 'user' | 'role',
      principal_id: principal.value.slice(split + 1),
      permission,
    })
  emit('update:modelValue', next)
}
function label(permission: string) {
  if (permission.startsWith('printer.')) return printerPermissionLabel(permission)
  const labels: Record<string, string> = {
    view: 'View cartridge',
    use: 'Use cartridge',
    approve_use: 'Approve cartridge use',
    edit_notes: 'Edit cartridge notes',
    edit_details: 'Edit cartridge details',
    manage_access: 'Manage cartridge access',
    view_audit: 'View cartridge audit log',
  }
  return labels[permission.split('.')[1]!] ?? permission
}
</script>

<template>
  <fieldset class="resource-grants">
    <legend>Permissions</legend>
    <label
      >User or role<select v-model="principal">
        <option value="">Choose a user or role</option>
        <option v-for="person in people" :key="person.value" :value="person.value">
          {{ person.label }}
        </option>
      </select></label
    >
    <div class="resource-permission-grid">
      <label v-for="permission in permissions" :key="permission" class="checkbox">
        <input
          type="checkbox"
          :disabled="!principal"
          :checked="modelValue.some((grant) => matches(grant, permission))"
          @change="toggle(permission, ($event.target as HTMLInputElement).checked)"
        />{{ label(permission) }}
      </label>
    </div>
  </fieldset>
</template>

<style scoped>
.resource-grants {
  border: 0;
  padding: 0;
  margin: 1.5rem 0;
  min-width: 0;
}
.resource-grants legend {
  font-weight: 700;
  margin-bottom: 0.75rem;
}
.resource-permission-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.75rem 1.5rem;
  margin-top: 1rem;
}
@media (max-width: 600px) {
  .resource-permission-grid {
    grid-template-columns: 1fr;
  }
}
</style>
