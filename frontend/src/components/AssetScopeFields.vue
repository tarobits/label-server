<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useAuthStore } from '../auth'
import { useResourceStore } from '../stores/resources'
import { useLiveRefresh } from '../live'
import { errorMessage } from '../api'
import type { AssetSharing } from '../types'

const props = defineProps<{
  kind: 'images' | 'fonts'
  original?: AssetSharing
  disabled?: boolean
}>()
const model = defineModel<AssetSharing>({ required: true })
const auth = useAuthStore(),
  resources = useResourceStore()
const groups = ref<{ id: string; name: string }[]>([])
const error = ref('')
const options = computed(() =>
  groups.value.filter(
    (group) =>
      auth.user?.is_admin ||
      auth.user?.group_memberships[group.id]?.[props.kind]?.can_create ||
      group.id === props.original?.group_id,
  ),
)
const scopes = computed(() =>
  (['personal', 'group', 'global'] as const).filter(
    (scope) =>
      scope === props.original?.scope ||
      (scope === 'group' ? options.value.length > 0 : auth.can(`${props.kind}.create_${scope}`)),
  ),
)
useLiveRefresh(async () => {
  try {
    const values = await resources.get<{ id: string; name: string }[]>('/user-groups')
    groups.value =
      props.original?.group_id && !values.some((group) => group.id === props.original?.group_id)
        ? [...values, { id: props.original.group_id, name: 'Current group' }]
        : values
    error.value = ''
  } catch (cause) {
    error.value = errorMessage(cause)
  }
}, 30000)
watch(
  [scopes, options],
  () => {
    if (props.disabled) return
    let scope = model.value.scope
    if (!scopes.value.includes(scope) && scopes.value[0]) scope = scopes.value[0]
    const group_id =
      scope === 'group'
        ? options.value.some((group) => group.id === model.value.group_id)
          ? model.value.group_id
          : (options.value[0]?.id ?? null)
        : null
    if (scope !== model.value.scope || group_id !== model.value.group_id)
      model.value = { scope, group_id }
  },
  { immediate: true },
)
function setScope(event: Event) {
  const scope = (event.target as HTMLSelectElement).value as AssetSharing['scope']
  model.value = { scope, group_id: scope === 'group' ? (options.value[0]?.id ?? null) : null }
}
</script>
<template>
  <div class="field-row">
    <label
      >Visibility<select
        :value="model.scope"
        :disabled="disabled || !scopes.length"
        @change="setScope"
      >
        <option v-for="scope in scopes" :key="scope" :value="scope">
          {{ scope === 'personal' ? 'Personal' : scope === 'global' ? 'Global' : 'Group' }}
        </option>
      </select></label
    >
    <Transition name="panel-expand">
      <label v-if="model.scope === 'group'"
        >Group<select v-model="model.group_id" required :disabled="disabled">
          <option v-for="group in options" :key="group.id" :value="group.id">
            {{ group.name }}
          </option>
        </select></label
      >
    </Transition>
  </div>
  <Transition name="notice"
    ><p v-if="error" class="alert danger" role="alert">{{ error }}</p></Transition
  >
</template>
