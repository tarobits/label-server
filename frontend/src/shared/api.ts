import { checkServer, serverUnavailable, serverUnavailableMessage } from './serverConnection'
import { browserLanguage, locale, t } from './i18n'

let csrfToken: string | null = null
let unauthorized: (() => void) | undefined
const mutationListeners = new Set<(path: string) => void>()
export function onApiMutation(listener: (path: string) => void) {
  mutationListeners.add(listener)
}
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public detail?: unknown,
  ) {
    super(message)
  }
}
export function configureSession(token: string | null, onUnauthorized?: () => void) {
  csrfToken = token
  if (onUnauthorized) unauthorized = onUnauthorized
}
function responseMessage(detail: unknown, status: number): string {
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const messages = detail.flatMap((issue) => {
      if (!issue || typeof issue.msg !== 'string') return []
      const path = Array.isArray(issue.loc)
        ? issue.loc
            .slice(1)
            .filter((part: unknown) => typeof part === 'string' || typeof part === 'number')
            .join('.')
        : ''
      return [path ? `${path}: ${issue.msg}` : issue.msg]
    })
    if (messages.length) return messages.join('; ')
  }
  if (
    detail &&
    typeof detail === 'object' &&
    'message' in detail &&
    typeof detail.message === 'string'
  )
    return detail.message
  if (status === 401) return t('requestErrors.sessionExpired')
  if (status === 403) return t('requestErrors.forbidden')
  if (status === 404) return t('requestErrors.notFound')
  if (status === 429) return t('requestErrors.tooManyRequests')
  if (status >= 500) return t('requestErrors.serverError')
  return t('requestErrors.requestFailed', { status })
}
function transportError(error: unknown, safeToRetry: boolean) {
  const timedOut = error instanceof Error && ['TimeoutError', 'AbortError'].includes(error.name)
  return new ApiError(
    timedOut
      ? safeToRetry
        ? t('requestErrors.timeout')
        : t('requestErrors.timeoutMutation')
      : t('requestErrors.connection'),
    0,
  )
}
export async function api<T>(
  path: string,
  method = 'GET',
  body?: unknown,
  headers: Record<string, string> = {},
): Promise<T> {
  // Never queue or replay mutations during an outage.
  if (serverUnavailable.value) throw new ApiError(serverUnavailableMessage.value, 0)
  const requestToken = csrfToken
  const readOnly = ['GET', 'HEAD', 'OPTIONS'].includes(method)
  const safeToRetry =
    readOnly ||
    [
      '/preview',
      '/logic/inspect',
      '/logic/compile',
      '/runs/inspect',
      '/admin/access-preview',
    ].includes(path.split('?')[0]!)
  const options: RequestInit = {
    method,
    credentials: 'same-origin',
    headers: {
      'Accept-Language': locale.value,
      'X-Browser-Language': browserLanguage.value,
      ...(!readOnly && csrfToken ? { 'X-CSRF-Token': csrfToken } : {}),
      ...(body === undefined
        ? {}
        : {
            'Content-Type': body instanceof Blob ? 'application/octet-stream' : 'application/json',
          }),
      ...headers,
    },
    body: body === undefined ? undefined : body instanceof Blob ? body : JSON.stringify(body),
    signal: AbortSignal.timeout(15000),
  }
  let response: Response
  try {
    response = await fetch(`/api${path}`, options)
  } catch (error) {
    void checkServer()
    throw transportError(error, safeToRetry)
  }
  let result = null
  if (![204, 205].includes(response.status) && method !== 'HEAD') {
    try {
      result = await response.json()
    } catch (error) {
      void checkServer()
      if (response.ok) {
        if (error instanceof Error && ['TimeoutError', 'AbortError'].includes(error.name))
          throw transportError(error, safeToRetry)
        throw new ApiError(
          safeToRetry ? t('requestErrors.unreadable') : t('requestErrors.unreadableMutation'),
          response.status,
        )
      }
    }
  }
  if (!response.ok) {
    if (response.status >= 500) void checkServer()
    if (response.status === 401 && !path.startsWith('/auth/') && requestToken === csrfToken)
      unauthorized?.()
    const detail = result?.detail
    const message = responseMessage(detail, response.status)
    throw new ApiError(message, response.status, detail)
  }
  if (!safeToRetry) for (const listener of mutationListeners) listener(path.split('?')[0]!)
  return result as T
}
export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : t('requestErrors.unexpected')
}
