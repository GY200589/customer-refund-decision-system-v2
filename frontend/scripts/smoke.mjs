import { chromium } from 'playwright-core'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'

const baseURL = process.env.SMOKE_BASE_URL || 'http://localhost:5173'
const executablePath = process.env.BROWSER_PATH || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const outputDir = path.resolve('test-results')
await mkdir(outputDir, { recursive: true })

const browser = await chromium.launch({ executablePath, headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: 'zh-CN' })
const page = await context.newPage()
const browserErrors = []
page.on('pageerror', (error) => browserErrors.push(error.message))

async function login(username) {
  await page.goto(`${baseURL}/login`)
  await page.getByLabel('用户名').fill(username)
  await page.getByLabel('密码').fill('password123')
  await page.getByRole('button', { name: /登\s*录/ }).click()
}

await login('customer1')
await page.waitForURL('**/shop')
await page.getByText('男装精选', { exact: true }).waitFor()
await page.getByRole('heading', { name: '城市机能外套季' }).first().waitFor()
await page.locator('.product-card').first().waitFor()
const productCount = await page.locator('.product-card').count()
if (productCount !== 50) throw new Error(`商城应显示 50 件商品，实际 ${productCount}`)
if (await page.getByText('风格分类', { exact: true }).count()) throw new Error('商城仍显示已删除的风格分类')
const floatingCart = page.locator('.floating-cart-button')
await floatingCart.waitFor()
await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
const cartPosition = await floatingCart.evaluate((element) => getComputedStyle(element.closest('.floating-cart-badge') || element).position)
const cartBox = await floatingCart.boundingBox()
if (cartPosition !== 'fixed' || !cartBox || cartBox.y + cartBox.height > 1001) {
  throw new Error('滚动到底部后购物袋没有固定在可视区域')
}
await page.screenshot({ path: path.join(outputDir, 'shop-desktop.png'), fullPage: true })

await page.getByRole('button', { name: '打开智能客服' }).click()
await page.getByRole('dialog').getByText('MISTER 智能客服').waitFor()
if (new URL(page.url()).pathname !== '/shop') throw new Error('打开客服叠层后不应离开购物页面')
await page.getByRole('button', { name: '返回购物页面' }).click()
await page.getByText('MISTER 智能客服').waitFor({ state: 'hidden' })
if (new URL(page.url()).pathname !== '/shop') throw new Error('关闭客服叠层后没有留在购物页面')
await page.getByRole('button', { name: '打开智能客服' }).click()
await page.getByRole('dialog').getByText('MISTER 智能客服').waitFor()
if (await page.getByRole('menuitem', { name: /智能客服/ }).count()) throw new Error('智能客服仍显示在顶部导航')
await page.route('**/api/v1/customer/assistant', async (route) => {
  const body = route.request().postDataJSON()
  if (!body.use_model_fallback) return route.continue()
  return route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      session_id: body.session_id || 'smoke-model-session', input_source: 'text', intents: ['other'], entities: {}, confidence: 0.3,
      answer: '面试穿搭建议选择深色西装或夹克，内搭素色衬衫，整体保持简洁合身。', citations: [], retrieved: [],
      action: 'model_fallback', data: null, generator: 'deepseek',
    }),
  })
})
const overlay = page.getByRole('dialog')
await overlay.getByPlaceholder('找衣服、输入订单号，或咨询退款和尺码').fill('参加面试怎么搭配会更稳重')
await overlay.getByRole('button', { name: '发送' }).click()
await overlay.getByRole('button', { name: '转人工客服' }).waitFor()
await overlay.getByRole('button', { name: '转人工客服' }).click()
await overlay.getByText('大模型客服 · DeepSeek').waitFor()
await page.screenshot({ path: path.join(outputDir, 'assistant-model-fallback.png') })
await page.getByRole('dialog').getByRole('button', { name: '找灰色连帽拉链卫衣' }).click()
const productResult = page.locator('.assistant-product-result').first()
await productResult.waitFor()
if (!(await productResult.innerText()).includes('灰色连帽拉链卫衣')) throw new Error('商品关键词没有命中指定卫衣')
await page.screenshot({ path: path.join(outputDir, 'assistant-product-search.png'), fullPage: true })
await productResult.click()
await page.waitForURL(/\/shop\?product=\d+$/)
await page.getByText('MISTER 智能客服').waitFor({ state: 'hidden' })
await page.getByRole('dialog', { name: '灰色连帽拉链卫衣' }).waitFor()
await page.getByRole('button', { name: '继续浏览' }).click()

await page.goto(`${baseURL}/assistant`)
const assistantInput = page.getByPlaceholder('找衣服、输入订单号，或咨询退款和尺码')
await assistantInput.fill('查询订单 SO2026090100001 的详情')
await page.getByRole('button', { name: '发送' }).click()
const orderResult = page.locator('.assistant-record-result').first()
await orderResult.waitFor()
if (!(await orderResult.innerText()).includes('SO2026090100001')) throw new Error('订单号没有命中准确订单')
await orderResult.click()
await page.waitForURL('**/orders?order=SO2026090100001')
await page.getByText('物流进度').waitFor()
await page.goto(`${baseURL}/orders`)

await page.waitForURL('**/orders')
const brokenOrderImages = await page.locator('.order-card img').evaluateAll((images) => images.filter((image) => image.naturalWidth === 0).length)
if (brokenOrderImages) throw new Error(`订单列表存在 ${brokenOrderImages} 张破图`)
await page.getByRole('button', { name: '订单详情' }).first().click()
await page.getByText('物流进度').waitFor()
await page.getByText('商品清单').waitFor()
await page.screenshot({ path: path.join(outputDir, 'order-detail-desktop.png'), fullPage: true })

await page.goto(`${baseURL}/refunds`)
await page.waitForURL('**/refunds')
const refundCards = page.locator('.refund-list-card')
if (await refundCards.count()) {
  await refundCards.first().click()
} else {
  await page.route('**/api/v1/customer/refunds/smoke-refund', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      case_id: 'smoke-refund', order_no: 'SO202609030001', product_name: '经典直筒牛仔裤', sub_category: 'jeans',
      product_id: 1, order_item_id: 1, amount_cent: 12900, amount_yuan: '129.00', status: 'RUNNING',
      friendly_status: '正在核对资料', reason: '尺码不合适', description: '裤腰偏小，希望退款',
      created_at: '2026-09-03T12:00:00+08:00', updated_at: '2026-09-03T12:01:00+08:00', refund_status: null, refund_ref: null,
      timeline: [
        { key: 'submitted', title: '已提交', description: '退款申请已收到', state: 'finish', at: '2026-09-03T12:00:00+08:00' },
        { key: 'review', title: '资料核对', description: '正在核对订单和凭证', state: 'process', at: '2026-09-03T12:01:00+08:00' },
        { key: 'completed', title: '处理完成', description: '核对完成后会原路退款', state: 'wait', at: null },
      ],
      evidence: [], friendly_explanation: '资料正在自动核对，请耐心等待。',
    }),
  }))
  await page.goto(`${baseURL}/refunds/smoke-refund`)
}
await page.waitForURL(/\/refunds\/[^/]+$/)
await page.getByText('退款进度', { exact: true }).last().waitFor()
await page.getByText('申请信息', { exact: true }).waitFor()
await page.getByText('凭证信息', { exact: true }).waitFor()
await page.screenshot({ path: path.join(outputDir, 'refund-detail-desktop.png'), fullPage: true })

await page.goto(`${baseURL}/shop`)
await page.waitForURL('**/shop')

await page.setViewportSize({ width: 390, height: 844 })
await page.reload()
await page.getByRole('heading', { name: '城市机能外套季' }).first().waitFor()
await page.locator('.product-card').first().waitFor()
await page.screenshot({ path: path.join(outputDir, 'shop-mobile.png'), fullPage: true })
const horizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)
if (horizontalOverflow) throw new Error('手机尺寸存在页面横向溢出')
await page.getByRole('button', { name: '打开智能客服' }).click()
await page.getByRole('dialog').getByText('MISTER 智能客服').waitFor()
if (new URL(page.url()).pathname !== '/shop') throw new Error('手机端客服应覆盖在购物页面上方')
await page.getByRole('dialog').getByRole('button', { name: '给我看看黑色的裤子' }).click()
await page.locator('.assistant-product-result').first().waitFor()
const assistantMobileOverflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)
if (assistantMobileOverflow) throw new Error('手机尺寸下智能客服存在横向溢出')
await page.screenshot({ path: path.join(outputDir, 'assistant-mobile.png') })

await context.clearCookies()
await page.evaluate(() => localStorage.clear())
await page.setViewportSize({ width: 1440, height: 1000 })
await login('agent1')
await page.waitForURL((url) => url.pathname === '/')
await page.getByText('最新案件').waitFor()
await page.screenshot({ path: path.join(outputDir, 'dashboard-desktop.png'), fullPage: true })

if (browserErrors.length) throw new Error(`浏览器脚本错误: ${browserErrors.join('; ')}`)
console.log(JSON.stringify({ productCount, horizontalOverflow, browserErrors, outputDir }))
await browser.close()
