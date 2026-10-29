import { api, ApiError } from './api'
import { ActionCancelled, confirmAction } from './confirmation'

export async function installCartridge(printerId: string, cartridgeId: string | null) {
  let confirmation: string | undefined
  for (let attempt = 0; ; attempt++) {
    try {
      return await api(`/printer/active-tape?printer_id=${encodeURIComponent(printerId)}`, 'PUT', {
        cartridge_id: cartridgeId,
        ...(confirmation ? { media_confirmation: confirmation } : {}),
      })
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 409) throw error
      const detail = error.detail as {
        code?: string
        message?: string
        confirmation?: string
      } | null
      if (
        detail?.code !== 'cartridge_mismatch' ||
        typeof detail.message !== 'string' ||
        typeof detail.confirmation !== 'string'
      )
        throw error
      if (attempt >= 3)
        throw new Error('Cartridge detection keeps changing. Check the cartridge and try again.')
      if (!(await confirmAction(detail.message, 'Yes, I’m sure'))) throw new ActionCancelled()
      confirmation = detail.confirmation
    }
  }
}
