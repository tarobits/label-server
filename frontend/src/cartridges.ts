import { api, ApiError } from './api'
import { ActionCancelled, confirmAction, chooseAction } from './confirmation'

export async function installCartridge(
  printerId: string,
  cartridgeId: string | null,
  options: {
    explicitSelection?: boolean
    chooseCartridge?: () => Promise<unknown>
    apiPrefix?: '' | '/proxy'
  } = {},
) {
  let confirmation: string | undefined
  let moveLocation: boolean | undefined
  let locationConfirmation: string | undefined
  for (let attempt = 0; ; attempt++) {
    try {
      return await api(
        `${options.apiPrefix ?? ''}/printer/active-tape?printer_id=${encodeURIComponent(printerId)}`,
        'PUT',
        {
          cartridge_id: cartridgeId,
          ...(options.explicitSelection ? { confirm_matching_cartridge: true } : {}),
          ...(confirmation ? { media_confirmation: confirmation } : {}),
          ...(moveLocation !== undefined ? { move_location: moveLocation } : {}),
          ...(locationConfirmation ? { location_confirmation: locationConfirmation } : {}),
        },
      )
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 409) throw error
      if (attempt >= 5)
        throw new Error('Cartridge details keep changing. Check them and try again.')
      const detail = error.detail as {
        code?: string
        message?: string
        confirmation?: string
        reason?: string
        owner_loss_warning?: boolean
        affected_users?: {
          name: string
          before: Record<string, string[]>
          after: Record<string, string[]>
        }[]
      } | null
      if (detail?.code === 'cartridge_location' && detail.message && detail.confirmation) {
        const changes = (detail.affected_users ?? [])
          .map((user) => {
            const before = Object.values(user.before).flat(),
              after = Object.values(user.after).flat()
            const added = after
              .filter((permission) => !before.includes(permission))
              .map((permission) => permission.replace('cartridge.', '').replaceAll('_', ' '))
            const removed = before
              .filter((permission) => !after.includes(permission))
              .map((permission) => permission.replace('cartridge.', '').replaceAll('_', ' '))
            return `${user.name}: ${[added.length ? `adds ${added.join(', ')}` : '', removed.length ? `removes ${removed.join(', ')}` : ''].filter(Boolean).join('; ')}`
          })
          .join('\n')
        const warning = detail.owner_loss_warning
          ? '\nApprove use can reduce the cartridge owner’s income.'
          : ''
        const choice = await chooseAction(
          [detail.message, changes, warning].filter(Boolean).join('\n\n'),
          {
            title: 'Cartridge location',
            confirmLabel: 'Move location and install',
            alternateLabel: 'Keep location and install',
            cancelLabel: 'Cancel',
          },
        )
        if (choice === 'cancel') throw new ActionCancelled()
        moveLocation = choice === 'confirm'
        locationConfirmation = detail.confirmation
        continue
      }
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
