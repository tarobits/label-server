<script setup lang="ts">
defineProps<{ name: string }>()
const paths: Record<string, string> = {
  overview: 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
  queue: 'M8 6h13 M8 12h13 M8 18h13 M3 6h.01 M3 12h.01 M3 18h.01',
  csv: 'M3 3h18v18H3z M3 9h18 M3 15h18 M9 9v12 M15 9v12',
  image: 'M3 3h18v18H3z M3 17l6-6 4 4 3-3 5 5 M15 7h.01',
  font: 'M3 20 9 4l6 16 M5 15h8 M16 10h6 M19 10v10',
  tape: 'M4 4h16v16H4z M8 8h8v5H8z M8 17h8',
  cartridge: 'M6 3h12l3 6v12H3V9z M3 9h18 M9 13h6v4H9z',
  template: 'M4 3h16v18H4z M8 7h8 M8 11h4 M8 15h8 M8 18h5',
  activity: 'M3 12h4l3-8 4 16 3-8h4',
  settings: 'M4 6h16 M4 12h16 M4 18h16 M8 3v6 M16 9v6 M10 15v6',
  printer: 'M6 9V3h12v6 M6 17H3V9h18v8h-3 M6 14h12v7H6z M17 11h.01',
  plus: 'M12 5v14 M5 12h14',
  arrow: 'M5 12h14 M13 6l6 6-6 6',
}
</script>
<template>
  <svg
    width="20"
    height="20"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.6"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path :d="paths[name] || paths.tape" />
  </svg>
</template>
