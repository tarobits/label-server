<script setup lang="ts">
import { onBeforeUnmount } from 'vue'
import licenseText from '../../../LICENSE?raw'

// Modified deployments must link to the corresponding source they actually run.
const sourceUrl = 'https://github.com/tarobits/label-server'
const licenseUrl = URL.createObjectURL(
  new Blob([licenseText], { type: 'text/plain;charset=utf-8' }),
)
onBeforeUnmount(() => URL.revokeObjectURL(licenseUrl))
</script>

<template>
  <span class="source-links">
    <a :href="sourceUrl" target="_blank" rel="noopener noreferrer">{{ $t('common.source') }}</a>
    <a
      :href="licenseUrl"
      download="AGPL-3.0.txt"
      :aria-label="$t('sourceLink.downloadAgplLicense')"
      >{{ $t('sourceLink.agplv3') }}</a
    >
  </span>
</template>

<style scoped>
.source-links {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 10px;
}
.source-links a {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
}
</style>
