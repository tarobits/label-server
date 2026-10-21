<script setup lang="ts">
import AdminDialog from './AdminDialog.vue'
import type { ReleaseNotes } from '../changelog'

defineProps<{ open: boolean; title: string; releases: ReleaseNotes[] }>()
const emit = defineEmits<{ close: [] }>()
</script>

<template>
  <Teleport to="body">
    <AdminDialog :open="open" :title="title" @close="emit('close')">
      <section v-for="release in releases" :key="release.version" class="release-notes">
        <header>
          <h3>v{{ release.version }}</h3>
          <time v-if="release.date" :datetime="release.date">{{ release.date }}</time>
        </header>
        <template v-for="(block, index) in release.blocks" :key="index">
          <h4 v-if="block.kind === 'heading'">{{ block.text }}</h4>
          <ul v-else-if="block.kind === 'list'">
            <li v-for="(item, itemIndex) in block.items" :key="itemIndex">{{ item }}</li>
          </ul>
          <p v-else>{{ block.text }}</p>
        </template>
      </section>
    </AdminDialog>
  </Teleport>
</template>

<style scoped>
.release-notes + .release-notes {
  margin-top: 28px;
  padding-top: 24px;
  border-top: 1px solid var(--line);
}
.release-notes header {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px 16px;
}
.release-notes h3 {
  margin: 0;
  font-size: 18px;
}
.release-notes time {
  color: var(--text-secondary);
  font-size: 12px;
}
.release-notes h4 {
  margin: 20px 0 8px;
  font-size: 14px;
}
.release-notes ul {
  margin: 0;
  padding-left: 20px;
}
.release-notes li + li {
  margin-top: 8px;
}
.release-notes li,
.release-notes p {
  color: var(--text-secondary);
  overflow-wrap: anywhere;
}
</style>
