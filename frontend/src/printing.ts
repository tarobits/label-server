import { api, ApiError } from './api'
import { ActionCancelled, confirmAction } from './confirmation'

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
      const shortage = tapeShortage(error)
      if (!shortage) throw error
      if (attempt >= 3)
        throw new Error('The tape estimate changed repeatedly. Please try printing again.')
      if (!(await confirmAction(shortage.message, 'Print anyway'))) throw new ActionCancelled()
      confirmation = shortage.confirmation
    }
  }
}
