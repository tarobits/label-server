<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { t } from '../shared/i18n'
import Icon from './Icon.vue'
import MotionTrack from './MotionTrack.vue'
import ExpandableContent from './ExpandableContent.vue'

const props = defineProps<{
  links: string[][]
  active: string
  counts: Record<string, number>
}>()
const route = useRoute()
const root = ref<HTMLElement | null>(null)
const measure = ref<HTMLElement | null>(null)
const trigger = ref<HTMLButtonElement | null>(null)
const compact = ref(false)
const open = ref(false)
const current = computed(() => props.links.find(([path]) => path === props.active))
let observer: ResizeObserver | undefined
let header: MediaQueryList | undefined

function update() {
  if (!root.value || !measure.value) return
  const next =
    !!header?.matches && measure.value.getBoundingClientRect().width > root.value.clientWidth
  if (next !== compact.value) {
    const focused = root.value.contains(document.activeElement)
    compact.value = next
    open.value = false
    if (focused)
      void nextTick(() => {
        if (next) trigger.value?.focus()
        else root.value?.querySelector<HTMLElement>('a.selected')?.focus()
      })
  }
}
function close(restoreFocus = false) {
  open.value = false
  if (restoreFocus) trigger.value?.focus()
}
watch(
  () => route.path,
  () => close(),
)
watch(
  () => props.links.map(([path]) => path).join('\n'),
  () => close(),
)
onMounted(() => {
  header = matchMedia('(max-width: 850px)')
  header.addEventListener('change', update)
  observer = new ResizeObserver(update)
  if (root.value) observer.observe(root.value)
  if (measure.value) observer.observe(measure.value)
  update()
})
onBeforeUnmount(() => {
  observer?.disconnect()
  header?.removeEventListener('change', update)
})
</script>

<template>
  <nav
    ref="root"
    class="main-navigation"
    :class="{ compact }"
    :aria-label="t('app.mainNavigation')"
    @keydown.esc.stop.prevent="close(true)"
  >
    <div class="navigation-measure-clip" aria-hidden="true" inert>
      <div ref="measure" class="navigation-measure">
        <span v-for="[path, label, icon] in links" :key="path" class="navigation-item">
          <Icon :name="icon!" /><span>{{ t(label!) }}</span>
          <span v-if="counts[path!]" class="nav-count">{{ counts[path!] }}</span>
        </span>
      </div>
    </div>
    <div v-if="compact" class="navigation-heading">
      <span class="navigation-current">{{
        current ? t(current[1]!) : t('app.mainNavigation')
      }}</span>
      <button
        ref="trigger"
        class="secondary"
        :aria-expanded="open"
        aria-controls="main-navigation-links"
        @click="open = !open"
      >
        <Icon name="menu" />{{ t('navigation.menu') }}
      </button>
    </div>
    <ExpandableContent :open="!compact || open">
      <MotionTrack
        id="main-navigation-links"
        class="navigation-links"
        :identity="active"
        selector="a.selected"
      >
        <RouterLink
          v-for="[path, label, icon] in links"
          :key="path"
          :to="path!"
          class="navigation-item"
          :class="{ selected: active === path }"
          :aria-current="route.path === path ? 'page' : active === path ? 'location' : undefined"
          @click="close(true)"
        >
          <Icon :name="icon!" /><span>{{ t(label!) }}</span>
          <Transition name="notice"
            ><span v-if="counts[path!]" class="nav-count motion-reveal">{{
              counts[path!]
            }}</span></Transition
          >
        </RouterLink>
      </MotionTrack>
    </ExpandableContent>
  </nav>
</template>

<style scoped>
.sidebar .main-navigation {
  position: relative;
  display: block;
  min-width: 0;
  overflow-x: hidden;
}
.navigation-measure-clip {
  position: absolute;
  inset: 0;
  overflow: hidden;
  visibility: hidden;
  pointer-events: none;
}
.navigation-measure {
  display: flex;
  width: max-content;
  gap: 4px;
  padding: 6px;
}
.navigation-measure .navigation-item {
  display: flex;
  align-items: center;
  gap: 13px;
  padding: 8px 12px;
  font-size: 12px;
  white-space: nowrap;
}
.navigation-links {
  display: grid;
  gap: 5px;
}
.sidebar .navigation-item {
  min-width: 0;
  white-space: normal;
  overflow-wrap: anywhere;
}
.navigation-item svg {
  flex-shrink: 0;
}
.navigation-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 6px;
}
.navigation-current {
  min-width: 0;
  overflow-wrap: anywhere;
  font-weight: 600;
}
.navigation-heading button {
  flex-shrink: 0;
  min-height: 44px;
}
@media (max-width: 850px) {
  .main-navigation:not(.compact) .navigation-links {
    display: flex;
    gap: 4px;
  }
  .compact .navigation-links {
    max-height: 60dvh;
    overflow-y: auto;
    padding: 6px;
    margin-top: 10px;
    overscroll-behavior: contain;
  }
}
</style>
