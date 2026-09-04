import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { chromium } from 'playwright-core'

const baseURL = process.env.SMOKE_BASE_URL || 'http://localhost:5173'
const executablePath = process.env.BROWSER_PATH || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const browser = await chromium.launch({ executablePath, headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, locale: 'zh-CN' })
const browserErrors = []
page.on('pageerror', (error) => browserErrors.push(error.message))
page.on('request', (request) => {
  if (request.url().includes('/customer/uploads')) console.log(`upload-request ${request.method()} ${request.url()}`)
})
page.on('console', (entry) => {
  if (entry.type() === 'error') console.log(`browser-console ${entry.text()}`)
})

await page.goto(`${baseURL}/login`)
await page.getByLabel('用户名').fill('customer1')
await page.getByLabel('密码').fill('password123')
await page.getByRole('button', { name: /登\s*录/ }).click()
await page.waitForURL('**/shop')

const order = await page.evaluate(async () => {
  const token = localStorage.getItem('token')
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }
  const products = await fetch('/api/v1/customer/products?page_size=50', { headers }).then((response) => response.json())
  const product = products.items.find((item) => item.sub_category === 'joggers') || products.items[0]
  const response = await fetch('/api/v1/customer/orders', {
    method: 'POST',
    headers,
    body: JSON.stringify({ items: [{ product_id: product.id, size: product.sizes[0], quantity: 1 }] }),
  })
  if (!response.ok) throw new Error(`测试订单创建失败: ${response.status}`)
  return response.json()
})

await page.goto(`${baseURL}/orders?order=${order.order_no}`)
const orderDialog = page.getByRole('dialog', { name: /订单详情/ })
await orderDialog.waitFor()
await orderDialog.getByRole('button', { name: '申请退款' }).click()

const refundDialog = page.getByRole('dialog', { name: '提交退款申请' })
await refundDialog.waitFor()
await refundDialog.locator('.ant-form-item').filter({ hasText: '退款原因' }).locator('.ant-select-selector').click()
await page.getByText('商品质量问题', { exact: true }).last().click()
await refundDialog.getByText('轻微', { exact: true }).click()
await refundDialog.getByText(/轻微问题建议补偿商品可退金额的 15%/).waitFor()

const amountInput = refundDialog.getByLabel('申请退款金额')
const recommendedYuan = Number(await amountInput.inputValue())
if (!(recommendedYuan > 0 && recommendedYuan < order.total_cent / 100)) {
  throw new Error(`轻微瑕疵应建议部分退款，实际 ${recommendedYuan}`)
}

const image = await readFile(path.resolve('test-results/shop-desktop.png'))
const chooserPromise = page.waitForEvent('filechooser')
await refundDialog.getByRole('button', { name: '上传凭证' }).click()
const chooser = await chooserPromise
await chooser.setFiles({
  name: 'amount-1.00.png',
  mimeType: 'image/png',
  buffer: image,
})
await refundDialog.getByText(/金额待人工核对/).waitFor()
await page.screenshot({ path: path.resolve('test-results/refund-partial-ocr-warning.png') })

await refundDialog.getByLabel('问题说明').fill('裤脚有一点小线头，希望按建议金额补偿')
await refundDialog.getByRole('button', { name: '确认提交' }).click()
await refundDialog.waitFor({ state: 'hidden' })

let refund = null
for (let attempt = 0; attempt < 30; attempt += 1) {
  refund = await page.evaluate(async (orderNo) => {
    const token = localStorage.getItem('token')
    const rows = await fetch('/api/v1/customer/refunds', { headers: { Authorization: `Bearer ${token}` } }).then((response) => response.json())
    return rows.find((row) => row.order_no === orderNo) || null
  }, order.order_no)
  if (refund?.status === 'SUSPENDED') break
  await page.waitForTimeout(500)
}
if (!refund || refund.status !== 'SUSPENDED') throw new Error(`OCR 金额不一致未挂人工: ${JSON.stringify(refund)}`)
if (!refund.partial_refund) throw new Error('轻微瑕疵案件未记录为部分退款')

await page.goto(`${baseURL}/refunds/${refund.case_id}`)
await page.getByText('部分退款', { exact: false }).first().waitFor()
await page.getByText('需要人工进一步确认').waitFor()
await page.screenshot({ path: path.resolve('test-results/refund-partial-suspended.png') })

if (browserErrors.length) throw new Error(`浏览器脚本错误: ${browserErrors.join('; ')}`)
console.log(JSON.stringify({ order_no: order.order_no, case_id: refund.case_id, recommended_yuan: recommendedYuan, status: refund.status }))
await browser.close()
