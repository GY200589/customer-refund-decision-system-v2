import { chromium } from 'playwright-core'
import { readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const projectRoot = path.resolve(scriptDir, '..', '..')
const catalogPath = path.join(projectRoot, '男装', '商品标签表.json')
const outputPath = path.join(projectRoot, '男装', '淘宝采集记录.json')
const executablePath = process.env.BROWSER_PATH || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const maxPages = Math.max(1, Math.min(Number(process.argv[2] || 2), 5))

const searchUrl = new URL('https://uland.taobao.com/sem/tbsearch')
searchUrl.search = new URLSearchParams({
  bc_fl_src: 'tbsite_T9W2LtnM',
  channelSrp: 'bingSomama',
  clk1: '8cf9e4b33ba539d4804f7241c1e1f8a5',
  keyword: '男装',
  localImgKey: '',
  msclkid: '8124b246a99914251df2d8de4c17ac92',
  page: '1',
  q: '男装',
  refpid: 'mm_2898300158_3078300397_115665800437',
  spm: 'tbpc.pc_sem_alimama/a.201867-main.d6_second.4e632a897AGJm6',
  tab: 'all',
}).toString()

const existingCatalog = JSON.parse(await readFile(catalogPath, 'utf8'))
const existingIds = new Set(existingCatalog.map((item) => String(item['商品ID'] || '')).filter(Boolean))
const discovered = new Map()

const browser = await chromium.launch({ executablePath, headless: true })
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  locale: 'zh-CN',
  userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36',
})
const page = await context.newPage()

try {
  for (let pageNumber = 1; pageNumber <= maxPages; pageNumber += 1) {
    searchUrl.searchParams.set('page', String(pageNumber))
    await page.goto(searchUrl.toString(), { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForSelector('[class*="CardV2--doubleCardWrapper"]', { timeout: 30000 })

    const rowsById = new Map()
    let previousY = -1
    let stableRounds = 0

    // 页面会回收滚出可视区的卡片，因此必须在滚动过程中逐屏采集。
    for (let round = 0; round < 45 && stableRounds < 4; round += 1) {
      const visibleRows = await page.locator('[class*="CardV2--doubleCardWrapper"]').evaluateAll((cards, sourcePage) => (
        cards.map((card) => {
          const id = card.id.replace('item_id_', '').trim()
          const title = card.querySelector('[class*="Title--title"]')?.textContent?.trim() || ''
          const priceInt = card.querySelector('[class*="Price--priceInt"]')?.textContent?.trim() || ''
          const priceFloat = card.querySelector('[class*="Price--priceFloat"]')?.textContent?.trim() || ''
          const image = card.querySelector('img[class*="MainPic--mainPic"]')?.getAttribute('src') || ''
          return {
            商品ID: id,
            原始标题: title,
            价格: Number(`${priceInt}${priceFloat || ''}`),
            主图地址: image.startsWith('//') ? `https:${image}` : image.replace(/^http:/, 'https:'),
            来源商品链接: `https://item.taobao.com/item.htm?id=${id}`,
            来源页码: sourcePage,
          }
        }).filter((item) => /^\d+$/.test(item.商品ID) && item.原始标题 && item.主图地址 && Number.isFinite(item.价格))
      ), pageNumber)
      for (const row of visibleRows) rowsById.set(row.商品ID, row)

      const position = await page.evaluate(() => {
        window.scrollBy(0, Math.max(600, Math.floor(window.innerHeight * 0.8)))
        return { y: window.scrollY, height: document.documentElement.scrollHeight }
      })
      stableRounds = position.y === previousY ? stableRounds + 1 : 0
      previousY = position.y
      await page.waitForTimeout(450)
    }

    const rows = [...rowsById.values()]

    for (const row of rows) {
      if (!existingIds.has(row.商品ID) && !discovered.has(row.商品ID)) discovered.set(row.商品ID, row)
    }
    console.log(`第 ${pageNumber} 页：识别 ${rows.length} 件，累计新增候选 ${discovered.size} 件`)
  }

  const result = {
    采集时间: new Date().toISOString(),
    采集页面数: maxPages,
    已有商品数: existingIds.size,
    新增候选数: discovered.size,
    商品: [...discovered.values()],
  }
  await writeFile(outputPath, `${JSON.stringify(result, null, 2)}\n`, 'utf8')
  console.log(`候选清单已保存：${outputPath}`)
} finally {
  await browser.close()
}
