import { onMounted, onUnmounted } from 'vue'

type Subscriber = { task: () => Promise<unknown>; interval: number; due: number; running: boolean }
const subscribers = new Set<Subscriber>()
let timer: ReturnType<typeof setTimeout> | undefined
let listening = false
function schedule() {
  clearTimeout(timer)
  if (document.hidden || !subscribers.size) return
  const due = Math.min(...[...subscribers].filter((s) => !s.running).map((s) => s.due))
  if (Number.isFinite(due)) timer = setTimeout(tick, Math.max(0, due - Date.now()))
}
function tick() {
  for (const subscriber of subscribers) {
    if (subscriber.running || subscriber.due > Date.now() || document.hidden) continue
    subscriber.running = true
    void Promise.resolve()
      .then(subscriber.task)
      .catch(() => {})
      .finally(() => {
        subscriber.running = false
        subscriber.due = Date.now() + subscriber.interval
        schedule()
      })
  }
  schedule()
}
function resume() {
  if (!document.hidden) for (const subscriber of subscribers) subscriber.due = 0
  schedule()
}
export function useLiveRefresh(task: () => Promise<unknown>, interval = 5000) {
  const subscriber: Subscriber = { task, interval, due: 0, running: false }
  onMounted(() => {
    subscribers.add(subscriber)
    if (!listening) {
      document.addEventListener('visibilitychange', resume)
      window.addEventListener('focus', resume)
      listening = true
    }
    schedule()
  })
  onUnmounted(() => {
    subscribers.delete(subscriber)
    if (!subscribers.size) {
      document.removeEventListener('visibilitychange', resume)
      window.removeEventListener('focus', resume)
      listening = false
    }
    schedule()
  })
}
