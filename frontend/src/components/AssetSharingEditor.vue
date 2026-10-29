<script setup lang="ts">
import { ref, watch } from 'vue'
import { api } from '../api'
import { useWorkspaceStore } from '../workspace'
import type { AssetSharing } from '../types'
import AnimatedDetails from './AnimatedDetails.vue'
import AssetScopeFields from './AssetScopeFields.vue'
const props = defineProps<{ kind: 'images' | 'fonts'; asset: AssetSharing & { id: string } }>()
const w = useWorkspaceStore()
const sharing = ref<AssetSharing>({ scope: props.asset.scope, group_id: props.asset.group_id })
watch(
  () => [props.asset.scope, props.asset.group_id],
  () => {
    sharing.value = { scope: props.asset.scope, group_id: props.asset.group_id }
  },
)
async function save() {
  await w.action(
    () =>
      api(
        `/${props.kind === 'images' ? 'image' : 'font'}-assets/${props.asset.id}/sharing`,
        'PUT',
        sharing.value,
      ),
    'Sharing updated.',
  )
}
</script>
<template>
  <AnimatedDetails class="asset-sharing">
    <template #summary>Sharing</template>
    <form class="form-stack inset" @submit.prevent="save">
      <AssetScopeFields v-model="sharing" :original="asset" :kind="kind" :disabled="w.busy" />
      <button
        class="small primary"
        :disabled="
          w.busy ||
          (sharing.scope === asset.scope && sharing.group_id === asset.group_id) ||
          (sharing.scope === 'group' && !sharing.group_id)
        "
      >
        Save sharing
      </button>
    </form>
  </AnimatedDetails>
</template>
<style scoped>
.asset-sharing {
  margin-top: 10px;
  min-width: 180px;
}
</style>
