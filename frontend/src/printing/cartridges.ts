import { t } from '../shared/i18n'
import { api, ApiError } from '../shared/api'
import { ActionCancelled, confirmAction, chooseAction } from '../shared/confirmation'
import { permissionLabel } from '../shared/resourceAccess'

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
        throw new Error(t('remainingUi.cartridgeDetailsKeepChangingCheckThemAndTryAgain'))
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
              .map(permissionLabel)
            const removed = before
              .filter((permission) => !after.includes(permission))
              .map(permissionLabel)
            return `${user.name}: ${[added.length ? t('uiRemainder.adds', { permissions: added.join(', ') }) : '', removed.length ? t('uiRemainder.removes', { permissions: removed.join(', ') }) : ''].filter(Boolean).join('; ')}`
          })
          .join('\n')
        const warning = detail.owner_loss_warning
          ? t('remainingUi.approveUseCanReduceTheCartridgeOwnersIncome')
          : ''
        const choice = await chooseAction(
          [detail.message, changes, warning].filter(Boolean).join('\n\n'),
          {
            title: t('remainingUi.cartridgeLocation'),
            confirmLabel: t('remainingUi.moveLocationAndInstall'),
            alternateLabel: t('remainingUi.keepLocationAndInstall'),
            cancelLabel: t('common.cancel'),
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
        throw new Error(
          t('remainingUi.cartridgeDetectionKeepsChangingCheckTheCartridgeAndTryAgain'),
        )
      if (detail.reason === 'cartridge_check' && options.chooseCartridge) {
        const choice = await chooseAction(detail.message, {
          get title() {
            return t('cartridgeDetection.confirmCartridge')
          },
          confirmLabel: t('remainingUi.yesItIs'),
          cancelLabel: t('remainingUi.noIWillChangeItLater'),
          alternateLabel: t('remainingUi.noTakeMeToCartridges'),
        })
        if (choice === 'alternate') await options.chooseCartridge()
        if (choice !== 'confirm') throw new ActionCancelled()
      } else if (!(await confirmAction(detail.message, t('remainingUi.yesImSure'))))
        throw new ActionCancelled()
      confirmation = detail.confirmation
    }
  }
}
