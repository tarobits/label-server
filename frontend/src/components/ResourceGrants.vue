<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, errorMessage } from '../shared/api'
import type {
  AccessCatalog,
  Grant,
  ResourceKind,
  AccessExplanation,
} from '../shared/resourceAccess'
import { permissionLabel, decisionSummary } from '../shared/resourceAccess'
import PermissionRules from './PermissionRules.vue'
import ExpandableContent from './ExpandableContent.vue'
const props = defineProps<{
  modelValue: Grant[]
  catalog: AccessCatalog
  kind: ResourceKind
  identifier?: string
  roles: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: Grant[]] }>()
const principal = ref('')
const explanation = ref<AccessExplanation>()
const error = ref('')
let generation = 0
const people = computed(() => [
  ...props.catalog.users.map((user) => ({ value: `user:${user.id}`, label: user.name })),
  ...(props.roles
    ? props.catalog.roles.map((role) => ({ value: `role:${role.id}`, label: `Role: ${role.name}` }))
    : []),
])
const sections = computed(() =>
  (props.kind === 'location' ? (['printer', 'cartridge'] as const) : [props.kind]).map((kind) => ({
    title: kind === 'printer' ? 'Printer permissions' : 'Cartridge permissions',
    options: props.catalog.permissions[kind as 'printer' | 'cartridge'].map((id) => ({
      id,
      label: permissionLabel(id),
    })),
  })),
)
const selected = computed(() =>
  props.modelValue.filter(
    (grant) => `${grant.principal_kind}:${grant.principal_id}` === principal.value,
  ),
)
const hints = computed(() =>
  Object.fromEntries(
    (explanation.value?.resources[0]?.permissions ?? [])
      .filter((decision) => decision.rules.length)
      .map((decision) => [decision.permission, `Saved: ${decisionSummary(decision)}`]),
  ),
)
function change(options: { id: string }[], allowed: string[], denied: string[]) {
  const permissionIds = new Set(options.map((option) => option.id))
  const next = props.modelValue.filter(
    (grant) => !selected.value.includes(grant) || !permissionIds.has(grant.permission),
  )
  const split = principal.value.indexOf(':')
  if (split < 1) return
  for (const [effect, permissions] of [
    ['allow', allowed],
    ['deny', denied],
  ] as const) {
    for (const permission of permissions.filter((id) => permissionIds.has(id)))
      next.push({
        principal_kind: principal.value.slice(0, split) as 'user' | 'role',
        principal_id: principal.value.slice(split + 1),
        permission,
        effect,
      })
  }
  emit('update:modelValue', next)
}
watch(
  () => [principal.value, props.identifier, props.kind],
  async () => {
    const ticket = ++generation
    explanation.value = undefined
    error.value = ''
    if (
      !principal.value.startsWith('user:') ||
      !props.identifier ||
      !props.catalog.resources.some(
        (item) => item.id === props.identifier && item.kind === props.kind,
      )
    )
      return
    try {
      const query = new URLSearchParams({
        user_id: principal.value.slice(5),
        kind: props.kind,
        identifier: props.identifier,
      })
      const result = await api<AccessExplanation>(`/resource-access/explain?${query}`)
      if (ticket === generation) explanation.value = result
    } catch (issue) {
      if (ticket === generation) error.value = errorMessage(issue)
    }
  },
)
</script>
<template>
  <fieldset class="resource-grants form-stack">
    <legend>{{ $t('common.permissions') }}</legend>
    <label
      >{{ $t('common.userOrRole')
      }}<select v-model="principal">
        <option value="">{{ $t('common.chooseAUserOrRole') }}</option>
        <option v-for="person in people" :key="person.value" :value="person.value">
          {{ person.label }}
        </option>
      </select></label
    >
    <ExpandableContent :open="!!error"
      ><p class="alert danger" role="alert">{{ error }}</p></ExpandableContent
    >
    <fieldset v-for="section in sections" :key="section.title" class="permission-section">
      <legend>{{ section.title }}</legend>
      <PermissionRules
        :options="section.options"
        :allowed="
          selected.filter((grant) => grant.effect !== 'deny').map((grant) => grant.permission)
        "
        :denied="
          selected.filter((grant) => grant.effect === 'deny').map((grant) => grant.permission)
        "
        :disabled="!principal"
        :hints="hints"
        @change="(allowed, denied) => change(section.options, allowed, denied)"
      />
    </fieldset>
  </fieldset>
</template>
<style scoped>
.resource-grants,
.permission-section {
  border: 0;
  padding: 0;
  margin: 0;
  min-width: 0;
}
.resource-grants legend,
.permission-section legend {
  font-weight: 700;
  margin-bottom: 16px;
}
.permission-section + .permission-section {
  padding-top: 24px;
  border-top: 1px solid var(--line);
}
</style>
