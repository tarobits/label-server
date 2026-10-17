import { shallowRef } from 'vue'

interface Confirmation {
  message: string
  confirmLabel: string
  resolve: (accepted: boolean) => void
}
export class ActionCancelled extends Error {}
export const confirmation = shallowRef<Confirmation | null>(null)
export function confirmAction(message: string, confirmLabel = 'Confirm'): Promise<boolean> {
  if (confirmation.value) return Promise.resolve(false)
  return new Promise((resolve) => {
    confirmation.value = { message, confirmLabel, resolve }
  })
}
export function resolveConfirmation(accepted: boolean) {
  const pending = confirmation.value
  confirmation.value = null
  pending?.resolve(accepted)
}
