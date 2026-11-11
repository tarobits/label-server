import type { Page } from '@playwright/test'

export async function usageSection(page: Page, section: string) {
  const titles: Record<string, string> = {
    usage: 'Tape & allocations',
    balances: 'Account balances',
    cartridges: 'Debts by cartridge',
    charges: 'Charges & receivables',
    payments: 'Repayments & corrections',
  }
  const mobile = page.getByRole('combobox', { name: 'Tape usage section', exact: true })
  if (await mobile.isVisible()) await mobile.selectOption(section)
  else
    await page
      .getByRole('navigation', { name: 'Tape usage sections' })
      .getByRole('button', { name: titles[section], exact: true })
      .click()
}

export async function toggleAdjustment(page: Page) {
  const dialog = page.getByRole('dialog', { name: 'Record repayment or correction', exact: true })
  if (await dialog.isVisible())
    await dialog.getByRole('button', { name: 'Close', exact: true }).click()
  else {
    await usageSection(page, 'payments')
    await page.getByRole('button', { name: 'Record repayment or correction', exact: true }).click()
  }
}
