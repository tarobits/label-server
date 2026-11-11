<script setup lang="ts">
import { computed } from 'vue'
import MotionTrack from './MotionTrack.vue'
import MotionSurface from './MotionSurface.vue'
const props = defineProps<{
  label: string
  active: string
  groups: { title: string; sections: { id: string; title: string }[] }[]
}>()
defineEmits<{ select: [id: string] }>()
const sections = computed(() => props.groups.flatMap((group) => group.sections))
</script>

<template>
  <div class="section-layout">
    <MotionTrack
      tag="nav"
      class="administration-nav section-nav"
      :identity="active"
      selector="button.active"
      :aria-label="`${label} sections`"
    >
      <div v-for="group in groups" :key="group.title" class="section-nav-group">
        <h2>{{ group.title }}</h2>
        <button
          v-for="item in group.sections"
          :key="item.id"
          :class="{ active: item.id === active }"
          :aria-current="item.id === active ? 'page' : undefined"
          @click="$emit('select', item.id)"
        >
          {{ item.title }}
        </button>
      </div>
    </MotionTrack>
    <label class="administration-mobile-nav section-mobile-nav"
      ><span class="sr-only">{{ label }} section</span
      ><select
        :value="active"
        @change="$emit('select', ($event.target as HTMLSelectElement).value)"
      >
        <optgroup v-for="group in groups" :key="group.title" :label="group.title">
          <option v-for="item in group.sections" :key="item.id" :value="item.id">
            {{ item.title }}
          </option>
        </optgroup>
      </select></label
    >
    <MotionSurface
      class="administration-content"
      :identity="active"
      :order="sections.findIndex((item) => item.id === active)"
      ><slot
    /></MotionSurface>
  </div>
</template>

<style scoped>
.section-layout {
  display: grid;
  grid-template-columns: 184px minmax(0, 1fr);
  gap: 32px;
  align-items: start;
}
.section-nav {
  display: grid;
  gap: 24px;
  position: sticky;
  top: 24px;
}
.section-nav-group {
  display: grid;
  gap: 4px;
}
.section-nav h2 {
  margin: 0 12px 8px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
}
.section-nav button {
  text-align: left;
  justify-content: flex-start;
  background: transparent;
  border-color: transparent;
  color: var(--text-secondary);
  font-weight: 500;
  padding: 12px;
}
.section-nav button.active {
  background: var(--surface-secondary);
  color: var(--ink);
}
.administration-content {
  min-width: 0;
}
.section-mobile-nav {
  display: none;
}
@media (max-width: 1000px) {
  .section-layout {
    grid-template-columns: 160px minmax(0, 1fr);
    gap: 20px;
  }
}
@media (max-width: 700px) {
  .section-layout {
    grid-template-columns: minmax(0, 1fr);
    gap: 24px;
  }
  .section-nav {
    display: none;
  }
  .section-mobile-nav {
    display: block;
  }
}
</style>
