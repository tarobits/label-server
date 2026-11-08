import { api, ApiError } from './api'
import { ActionCancelled, ActionDeferred, confirmAction } from './confirmation'
import { askCartridgeConsent, type CartridgeConsent } from './cartridgeConsent'

interface TapeShortage {
  code: 'tape_shortage'
  message: string
  confirmation: string
}
function tapeShortage(error: unknown): TapeShortage | undefined {
  if (!(error instanceof ApiError) || error.status !== 409) return
  const detail = error.detail as Partial<TapeShortage> | null
  if (
    detail?.code === 'tape_shortage' &&
    typeof detail.message === 'string' &&
    typeof detail.confirmation === 'string'
  )
    return detail as TapeShortage
}

export async function requestPrinting<T>(path: string, body?: unknown): Promise<T> {
  let confirmation: string | undefined
  for (let attempt = 0; ; attempt++) {
    try {
      return await api<T>(
        path,
        'POST',
        body,
        confirmation ? { 'X-Tape-Shortage-Confirmation': confirmation } : {},
      )
    } catch (error) {
      if (
        error instanceof ApiError &&
        error.status === 409 &&
        (error.detail as { code?: string })?.code === 'cartridge_quote_required'
      ) {
        const proposal = error.detail as {
          message: string
          printer_id: string
          cartridge_id: string
          job_ids: string[]
        }
        if (!(await confirmAction(proposal.message, 'Request price approval')))
          throw new ActionCancelled()
        const prefix = path.startsWith('/proxy/') ? '/proxy' : ''
        await api(
          `${prefix}/cartridge-quotes?printer_id=${encodeURIComponent(proposal.printer_id)}`,
          'POST',
          {
            printer_id: proposal.printer_id,
            cartridge_id: proposal.cartridge_id,
            job_ids: proposal.job_ids,
          },
        )
        throw new ActionDeferred(
          'Price approval requested. The labels remain queued until their requesters respond.',
        )
      }
      if (
        error instanceof ApiError &&
        error.status === 409 &&
        (error.detail as { code?: string })?.code === 'cartridge_use'
      ) {
        const consent = error.detail as CartridgeConsent
        if (attempt >= 5)
          throw new Error('Print authorization keeps changing. Review the queue and try again.')
        if (path.startsWith('/proxy/'))
          consent.items = consent.items.map((item) => ({
            ...item,
            preview: item.preview?.replace(/^\/api\//, '/api/proxy/') ?? null,
          }))
        const selected = await askCartridgeConsent(consent)
        if (!selected) throw new ActionCancelled()
        const old = (body ?? {}) as {
          copy_ids?: string[]
          approve_copy_ids?: string[]
          use_confirmations?: Record<string, string>
        }
        const blocked = new Set(consent.items.map((item) => item.copy_id))
        body = {
          ...old,
          copy_ids: (old.copy_ids ?? consent.copy_ids).filter(
            (id) => !blocked.has(id) || selected.includes(id),
          ),
          approve_copy_ids: [
            ...new Set([
              ...(old.approve_copy_ids ?? []).filter((id) => !blocked.has(id)),
              ...selected,
            ]),
          ],
          use_confirmations: { ...old.use_confirmations, ...consent.confirmations },
        }
        continue
      }
      const shortage = tapeShortage(error)
      if (!shortage) throw error
      if (attempt >= 3)
        throw new Error('The tape estimate changed repeatedly. Please try printing again.')
      if (!(await confirmAction(shortage.message, 'Print anyway'))) throw new ActionCancelled()
      confirmation = shortage.confirmation
    }
  }
}
