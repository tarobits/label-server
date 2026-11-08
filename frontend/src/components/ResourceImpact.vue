<script setup lang="ts">
import type { AccessImpact, ResourceEntry } from '../resourceAccess'
import AnimatedDetails from './AnimatedDetails.vue'
import { printerPermissionLabel } from '../printerPermissions'
defineProps<{ changes: AccessImpact[]; resources: ResourceEntry[] }>()
const difference = (a: string[], b: string[]) => a.filter((value) => !b.includes(value))
function label(permission: string) {
  return permission.startsWith('printer.')
    ? printerPermissionLabel(permission)
    : permission.replace('cartridge.', '').replaceAll('_', ' ')
}
</script>
<template>
  <p v-if="!changes.length">Effective permissions are unchanged.</p>
  <AnimatedDetails v-for="change in changes" :key="change.id" class="settings-details">
    <template #summary>{{ change.name }}</template>
    <template v-for="(permissions, key) in change.after" :key="key">
      <div
        v-if="JSON.stringify(change.before[key] ?? []) !== JSON.stringify(permissions)"
        class="access-impact-resource"
      >
        <strong>{{
          resources.find((item) => `${item.kind}:${item.id}` === key)?.name ?? key
        }}</strong>
        <p v-if="difference(permissions, change.before[key] ?? []).length">
          Added:
          {{
            difference(permissions, change.before[key] ?? [])
              .map(label)
              .join(', ')
          }}
        </p>
        <p v-if="difference(change.before[key] ?? [], permissions).length">
          Removed:
          {{
            difference(change.before[key] ?? [], permissions)
              .map(label)
              .join(', ')
          }}
        </p>
      </div>
    </template>
  </AnimatedDetails>
</template>
<style scoped>
.access-impact-resource {
  margin: 1rem 0;
  overflow-wrap: anywhere;
}
.access-impact-resource p {
  margin: 0.4rem 0;
}
</style>
