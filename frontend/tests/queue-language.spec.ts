import { test, expect } from './fixtures'

for (const language of ['en', 'de']) {
  test(`queue status uses protocol values in ${language}`, async ({ page, request }) => {
    const saved = await request.put('/api/auth/language', {
      data: { language, browser_language: language },
    })
    expect(saved.ok(), await saved.text()).toBeTruthy()
    const states: string[] = []
    const failures: number[] = []
    page.on('response', (response) => {
      const url = new URL(response.url())
      if (url.pathname === '/api/queue/groups') {
        states.push(url.searchParams.get('copy_state') ?? '')
        if (!response.ok()) failures.push(response.status())
      }
    })
    await page.goto('/#/queue')
    await expect(page.locator('#queue-filter')).toHaveValue('queued')
    await expect.poll(() => states.includes('queued')).toBe(true)

    // Query changes reuse the mounted view; unsupported states must also default safely.
    await page.evaluate(() => {
      window.location.hash = '/queue?state=printed'
    })
    await expect(page.locator('#queue-filter')).toHaveValue('printed')
    await expect.poll(() => states.includes('printed')).toBe(true)
    await page.evaluate(() => {
      window.location.hash = '/queue?state=invalid'
    })
    await expect(page.locator('#queue-filter')).toHaveValue('queued')
    expect(states.every((state) => ['queued', 'printed'].includes(state))).toBe(true)
    expect(failures).toEqual([])
  })
}
