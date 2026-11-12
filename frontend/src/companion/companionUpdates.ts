// Companion pages have no service worker. Compare the installed shell with the
// loaded shell, and never reload while an operator is using station controls.
const currentBuild = document.querySelector<HTMLMetaElement>('meta[name="app-build"]')?.content
const attemptKey = 'label-companion-update-attempt'
let checking = false
let reloading = false

export async function reloadUpdatedCompanion(
  build: string | null | undefined,
  safe: () => boolean,
): Promise<boolean> {
  if (
    checking ||
    reloading ||
    !currentBuild ||
    !build ||
    !/^[a-f0-9]{64}$/.test(build) ||
    currentBuild === build ||
    !safe()
  )
    return false
  checking = true
  try {
    const attempt = `${currentBuild}:${build}`
    // Avoid a reload loop if a proxy keeps serving an older shell. If storage
    // is unavailable, leave the existing page usable instead of risking a loop.
    if (sessionStorage.getItem(attemptKey) === attempt) return false
    const response = await fetch('/', {
      cache: 'no-store',
      credentials: 'same-origin',
      headers: { Accept: 'text/html' },
      signal: AbortSignal.timeout(5000),
    })
    if (!response.ok || !response.headers.get('content-type')?.includes('text/html')) return false
    const shell = new DOMParser().parseFromString(await response.text(), 'text/html')
    if (shell.querySelector<HTMLMetaElement>('meta[name="app-build"]')?.content !== build)
      return false
    // A dialog or control request may have started during the shell fetch.
    if (!safe()) return false
    sessionStorage.setItem(attemptKey, attempt)
    reloading = true
    window.location.reload()
    return true
  } catch {
    return false
  } finally {
    checking = false
  }
}
