export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    headers:
      body === undefined
        ? {}
        : {
            'Content-Type': body instanceof Blob ? 'application/octet-stream' : 'application/json',
          },
    body: body === undefined ? undefined : body instanceof Blob ? body : JSON.stringify(body),
    signal: AbortSignal.timeout(15000),
  })
  const result = await response.json().catch(() => null)
  if (!response.ok) {
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
          : `Request failed (${response.status})`
    throw new Error(message)
  }
  return result as T
}
export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.'
}
