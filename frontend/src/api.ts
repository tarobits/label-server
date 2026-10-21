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
  if (status === 401) return 'Your session has expired. Sign in again.'
  if (status === 403) return 'You do not have permission to perform this action.'
  if (status === 404) return 'This item is no longer available.'
  if (status === 429) return 'Too many requests. Wait a moment and try again.'
  if (status >= 500) return 'The server could not complete the request. Try again.'
  return `Request failed (${status}). Try again.`
}
function transportError(error: unknown, safeToRetry: boolean) {
  const timedOut = error instanceof Error && ['TimeoutError', 'AbortError'].includes(error.name)
  return new ApiError(
    timedOut
      ? safeToRetry
        ? 'The request timed out. Try again.'
        : 'The request timed out. Check its status before trying again.'
      : 'Cannot reach the server. Check your connection and try again.',
    0,
  )
}
export async function api<T>(
  path: string,
  method = 'GET',
  body?: unknown,
  headers: Record<string, string> = {},
): Promise<T> {
  const requestToken = csrfToken
  const readOnly = ['GET', 'HEAD', 'OPTIONS'].includes(method)
  const safeToRetry =
    readOnly || ['/preview', '/runs/inspect', '/admin/access-preview'].includes(path)
  const options: RequestInit = {
    method,
    credentials: 'same-origin',
    headers: {
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
    throw transportError(error, safeToRetry)
  }
  let result = null
  if (![204, 205].includes(response.status) && method !== 'HEAD') {
    try {
      result = await response.json()
    } catch (error) {
      if (response.ok) {
        if (error instanceof Error && ['TimeoutError', 'AbortError'].includes(error.name))
          throw transportError(error, safeToRetry)
        throw new ApiError(
          safeToRetry
            ? 'The server returned an unreadable response. Try again.'
            : 'The server returned an unreadable response. Check its status before trying again.',
          response.status,
        )
      }
    }
  }
  if (!response.ok) {
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
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.'
}
