<script setup lang="ts">
import { ref } from 'vue'
const props = defineProps<{
  keypad?: boolean
  shuffle?: 'none' | 'once' | 'each_keypress'
  disabled?: boolean
}>()
const pin = defineModel<string>({ required: true })
const input = ref<HTMLInputElement>()
const digits = ref(['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'])
function shuffleDigits() {
  const next = [...digits.value]
  const random = crypto.getRandomValues(new Uint32Array(9))
  for (let index = next.length - 1; index > 0; index--) {
    const other = Math.floor((random[index - 1]! / 2 ** 32) * (index + 1))
    ;[next[index], next[other]] = [next[other]!, next[index]!]
  }
  if (next.every((digit, index) => digit === digits.value[index])) next.push(next.shift()!)
  digits.value = next
}
if (props.keypad && props.shuffle && props.shuffle !== 'none') shuffleDigits()
function changed() {
  if (props.keypad && props.shuffle === 'each_keypress') shuffleDigits()
}
function press(key: string) {
  if (props.disabled || !input.value) return
  const field = input.value
  const start = field.selectionStart ?? pin.value.length
  const end = field.selectionEnd ?? start
  const from = key === 'backspace' && start === end ? Math.max(0, start - 1) : start
  const insertion = key === 'backspace' ? '' : key
  const next = key === 'clear' ? '' : pin.value.slice(0, from) + insertion + pin.value.slice(end)
  if (next.length > 12) return
  field.value = next
  // Use the same input event as typing, including the form's validation handling.
  field.dispatchEvent(new Event('input', { bubbles: true }))
  const caret = key === 'clear' ? 0 : from + insertion.length
  field.setSelectionRange(caret, caret)
}
</script>

<template>
  <div class="form-stack pin-entry">
    <label
      >PIN<input
        ref="input"
        v-model="pin"
        type="password"
        :inputmode="keypad ? 'none' : 'numeric'"
        pattern="[0-9]{4,12}"
        minlength="4"
        maxlength="12"
        autocomplete="off"
        required
        :disabled="disabled"
        @input="changed"
    /></label>
    <div v-if="keypad" class="pin-keypad" role="group" aria-label="PIN keypad">
      <button
        v-for="(digit, index) in digits.slice(0, 9)"
        :key="index"
        class="secondary pin-digit"
        type="button"
        :disabled="disabled"
        @click="press(digit)"
      >
        {{ digit }}
      </button>
      <button class="secondary" type="button" :disabled="disabled" @click="press('clear')">
        Clear
      </button>
      <button
        class="secondary pin-digit"
        type="button"
        :disabled="disabled"
        @click="press(digits[9]!)"
      >
        {{ digits[9] }}
      </button>
      <button class="secondary" type="button" :disabled="disabled" @click="press('backspace')">
        Backspace
      </button>
    </div>
  </div>
</template>

<style scoped>
.pin-keypad {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}
.pin-keypad button {
  min-height: 56px;
  padding: 12px 4px;
  touch-action: manipulation;
}
.pin-digit {
  font-size: 1.4rem;
  font-variant-numeric: tabular-nums;
}
</style>
