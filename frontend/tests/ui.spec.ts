import { test, expect } from '@playwright/test'

test('HTTP errors are safe, retries keep the key, mobile input stays usable', async ({ page }) => {
  // Error-injection UI test only; real business flows are in e2e.spec.ts.
  await page.route('**/health/live', route => route.fulfill({ json: { api: 'ok' } }))
  await page.route('**/health', route => route.fulfill({ json: { api: 'ok', database: 'ok' } }))
  await page.route('**/status', route => route.fulfill({ json: { api: 'ok', database: 'ok', agent_provider: 'fake', embedding_provider: 'fake', user: { id: 'ui-test', display_name: '测试用户' } } }))
  let status = 500
  const bodies: unknown[] = []
  await page.route('**/agent/requests', route => {
    bodies.push(route.request().postDataJSON())
    return route.fulfill({ status, body: 'SQL private_traceback secret' })
  })
  await page.goto('/')
  await page.getByLabel('消息', { exact: true }).fill('查询订单 SEED-O003')
  await page.getByRole('button', { name: '发送 ↑', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('服务暂时出错')
  await expect(page.locator('body')).not.toContainText('private_traceback')
  status = 422
  await page.getByRole('button', { name: '重试原请求', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('格式有误')
  expect(bodies[0]).toEqual(bodies[1])
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '＋ 新建会话', exact: true }).click()
  await expect(page.getByLabel('消息', { exact: true })).toBeEnabled()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
})
