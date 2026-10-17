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
export async function api<T>(
  path: string,
  method = 'GET',
  body?: unknown,
  headers: Record<string, string> = {},
): Promise<T> {
  const requestToken = csrfToken
  const response = await fetch(`/api${path}`, {
    method,
    credentials: 'same-origin',
    headers: {
      ...(!['GET', 'HEAD', 'OPTIONS'].includes(method) && csrfToken
        ? { 'X-CSRF-Token': csrfToken }
        : {}),
      ...(body === undefined
        ? {}
        : {
            'Content-Type': body instanceof Blob ? 'application/octet-stream' : 'application/json',
          }),
      ...headers,
    },
    body: body === undefined ? undefined : body instanceof Blob ? body : JSON.stringify(body),
    signal: AbortSignal.timeout(15000),
  })
  const result = await response.json().catch(() => null)
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith('/auth/') && requestToken === csrfToken)
      unauthorized?.()
    const detail = result?.detail
    const message =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail
              .map(
                (issue: { loc: string[]; msg: string }) =>
                  `${issue.loc.slice(1).join('.')}: ${issue.msg}`,
              )
              .join('; ')
          : typeof detail?.message === 'string'
            ? detail.message
            : `Request failed (${response.status})`
    throw new ApiError(message, response.status, detail)
  }
  if (
    !['GET', 'HEAD', 'OPTIONS'].includes(method) &&
    !['/preview', '/runs/inspect', '/admin/access-preview'].includes(path)
  )
    for (const listener of mutationListeners) listener(path.split('?')[0]!)
  return result as T
}
export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.'
}
