<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ text: string }>()
// Only recognize the inline formatting used by our release notes. All content
// remains Vue text nodes; release notes never supply HTML or arbitrary URLs.
const parts = computed(() => {
  const result: { tag: 'span' | 'strong' | 'code' | 'a'; text: string; href?: string }[] = []
  const pattern = /`([^`]+)`|\*\*([^*]+)\*\*|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g
  let start = 0
  for (const match of props.text.matchAll(pattern)) {
    result.push({ tag: 'span', text: props.text.slice(start, match.index) })
    if (match[1]) result.push({ tag: 'code', text: match[1] })
    else if (match[2]) result.push({ tag: 'strong', text: match[2] })
    else result.push({ tag: 'a', text: match[3]!, href: match[4] })
    start = match.index! + match[0].length
  }
  result.push({ tag: 'span', text: props.text.slice(start) })
  return result
})
</script>

<template>
  <component v-for="(part, index) in parts" :is="part.tag" :key="index" :href="part.href">{{
    part.text
  }}</component>
</template>
