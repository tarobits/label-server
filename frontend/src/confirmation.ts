import { shallowRef } from 'vue'

type ConfirmationChoice = 'confirm' | 'cancel' | 'alternate'
interface ConfirmationOptions {
  title?: string
  confirmLabel?: string
  cancelLabel?: string
  alternateLabel?: string
}
interface Confirmation extends ConfirmationOptions {
  message: string
  confirmLabel: string
  resolve: (choice: ConfirmationChoice) => void
}
export class ActionCancelled extends Error {}
export const confirmation = shallowRef<Confirmation | null>(null)
export function confirmAction(message: string, confirmLabel = 'Confirm'): Promise<boolean> {
  return chooseAction(message, { confirmLabel }).then((choice) => choice === 'confirm')
}
export function chooseAction(
  message: string,
  options: ConfirmationOptions,
): Promise<ConfirmationChoice> {
  if (confirmation.value) return Promise.resolve('cancel')
  return new Promise((resolve) => {
    confirmation.value = { confirmLabel: 'Confirm', ...options, message, resolve }
  })
}
export function resolveConfirmation(accepted: boolean) {
  resolveChoice(accepted ? 'confirm' : 'cancel')
}
export function resolveChoice(choice: ConfirmationChoice) {
  const pending = confirmation.value
  confirmation.value = null
  pending?.resolve(choice)
}
