import { computed, ref, watch } from 'vue'

export type MotionPreference = 'browser' | 'on' | 'off'
const storageKey = 'label-room.motion'
const valid = (value: unknown): MotionPreference =>
  value === 'on' || value === 'off' ? value : 'browser'
function read(): MotionPreference {
  try {
    return valid(localStorage.getItem(storageKey))
  } catch {
    return 'browser'
  }
}
export const motionPreference = ref<MotionPreference>(read())
const browser = window.matchMedia('(prefers-reduced-motion: reduce)')
const browserReduced = ref(browser.matches)
browser.addEventListener('change', (event) => {
  browserReduced.value = event.matches
})
export const reducedMotion = computed(() =>
  motionPreference.value === 'browser' ? browserReduced.value : motionPreference.value === 'on',
)
// One effective preference drives CSS and JavaScript, including live changes.
watch(
  reducedMotion,
  (value) => {
    document.documentElement.dataset.motion = value ? 'reduce' : 'full'
  },
  { immediate: true, flush: 'sync' },
)
watch(
  motionPreference,
  (value) => {
    try {
      localStorage.setItem(storageKey, value)
    } catch {
      // Preferences still work for this session when browser storage is blocked.
    }
  },
  { flush: 'sync' },
)
window.addEventListener('storage', (event) => {
  if (event.key === storageKey || event.key === null) motionPreference.value = read()
})
