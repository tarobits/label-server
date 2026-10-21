<script setup lang="ts">
import { provide, shallowReactive, watch } from 'vue'
import { routeLocationKey, type RouteLocationNormalizedLoaded } from 'vue-router'

const props = defineProps<{ location: RouteLocationNormalizedLoaded }>()
// Query changes update the mounted form. Once its keyed page leaves, it keeps
// its own route until disposal instead of reacting to the incoming page's URL.
const location = shallowReactive({ ...props.location })
provide(routeLocationKey, location)
watch(
  () => props.location,
  (value) => Object.assign(location, value),
  { flush: 'sync' },
)
</script>

<template>
  <div class="route-surface"><slot /></div>
</template>
