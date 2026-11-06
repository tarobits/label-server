import { api, ApiError } from './api'
import { ActionCancelled, confirmAction, chooseAction } from './confirmation'

export async function installCartridge(
  printerId: string,
  cartridgeId: string | null,
  options: { explicitSelection?: boolean; chooseCartridge?: () => Promise<unknown> } = {},
) {
  let confirmation: string | undefined
  for (let attempt = 0; ; attempt++) {
    try {
      return await api(`/printer/active-tape?printer_id=${encodeURIComponent(printerId)}`, 'PUT', {
        cartridge_id: cartridgeId,
        ...(options.explicitSelection ? { confirm_matching_cartridge: true } : {}),
        ...(confirmation ? { media_confirmation: confirmation } : {}),
      })
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 409) throw error
      const detail = error.detail as {
        code?: string
        message?: string
        confirmation?: string
        reason?: string
      } | null
      if (
        detail?.code !== 'cartridge_mismatch' ||
        typeof detail.message !== 'string' ||
        typeof detail.confirmation !== 'string'
      )
        throw error
      if (attempt >= 3)
        throw new Error('Cartridge detection keeps changing. Check the cartridge and try again.')
      if (detail.reason === 'cartridge_check' && options.chooseCartridge) {
        const choice = await chooseAction(detail.message, {
          title: 'Confirm cartridge',
          confirmLabel: 'Yes, it is',
          cancelLabel: 'No, I will change it later',
          alternateLabel: 'No, take me to cartridges',
        })
        if (choice === 'alternate') await options.chooseCartridge()
        if (choice !== 'confirm') throw new ActionCancelled()
      } else if (!(await confirmAction(detail.message, 'Yes, I’m sure')))
        throw new ActionCancelled()
      confirmation = detail.confirmation
    }
  }
}
