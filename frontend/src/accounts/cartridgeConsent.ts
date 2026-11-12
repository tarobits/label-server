import { shallowRef } from 'vue'

export interface CartridgeConsent {
  code: 'cartridge_use'
  message: string
  confirmations: Record<string, string>
  copy_ids: string[]
  items: {
    copy_id: string
    job_id: string
    requester: string
    ordinal: number
    actual: string
    maximum_charge: string
    currency: string
    preview: string | null
  }[]
}
export const cartridgeConsent = shallowRef<
  (CartridgeConsent & { resolve: (selected: string[] | null) => void }) | null
>(null)
export function askCartridgeConsent(value: CartridgeConsent): Promise<string[] | null> {
  if (cartridgeConsent.value) return Promise.resolve(null)
  return new Promise((resolve) => {
    cartridgeConsent.value = { ...value, resolve }
  })
}
export function resolveCartridgeConsent(selected: string[] | null) {
  const pending = cartridgeConsent.value
  cartridgeConsent.value = null
  pending?.resolve(selected)
}
