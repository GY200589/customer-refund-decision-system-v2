import {
  ArrowRightOutlined,
  CheckOutlined,
  DeleteOutlined,
  FireOutlined,
  GiftOutlined,
  SearchOutlined,
  ShoppingCartOutlined,
  SafetyCertificateOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import {
  Badge,
  Button,
  Card,
  Carousel,
  Drawer,
  Empty,
  Input,
  List,
  Modal,
  Segmented,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  createCustomerOrder,
  listCustomerProducts,
  type CustomerProduct,
} from '../api'

const categories = [
  { value: '', label: '全部' },
  { value: 'tshirt', label: 'T恤', main: 'top' },
  { value: 'shirt', label: '衬衫', main: 'top' },
  { value: 'hoodie', label: '卫衣', main: 'top' },
  { value: 'jacket', label: '夹克', main: 'top' },
  { value: 'padded', label: '羽绒棉服', main: 'top' },
  { value: 'jeans', label: '牛仔裤', main: 'bottom' },
  { value: 'casual_pants', label: '休闲长裤', main: 'bottom' },
  { value: 'suit_pants', label: '西裤', main: 'bottom' },
  { value: 'cargo_pants', label: '工装裤', main: 'bottom' },
  { value: 'joggers', label: '运动裤', main: 'bottom' },
  { value: 'shorts', label: '短裤', main: 'bottom' },
]

const heroSlides = [
  {
    eyebrow: '2026 AUTUMN EDIT',
    title: '城市机能外套季',
    description: '轻量夹克与重磅卫衣新款上架，通勤和周末都能利落出门。',
    action: '去看夹克',
    category: 'jacket',
    image: '/products/SKU_964323165122.webp',
    tone: 'graphite',
    note: '三防面料 / 宽松廓形',
  },
  {
    eyebrow: 'CLEAN COMMUTE',
    title: '把清爽穿进通勤',
    description: '天丝亚麻、冰丝抗皱与干净剪裁，轻松应对早晚温差。',
    action: '精选衬衫',
    category: 'shirt',
    image: '/products/SKU_1064115284316.webp',
    tone: 'mint',
    note: '透气轻薄 / 低饱和配色',
  },
  {
    eyebrow: 'DENIM MOVEMENT',
    title: '直筒与弯刀裤型',
    description: '从黑色微喇到冰蓝水洗，用不同轮廓完成日常搭配。',
    action: '探索牛仔',
    category: 'jeans',
    image: '/products/SKU_897352973681.webp',
    tone: 'cobalt',
    note: '水洗丹宁 / 轻松百搭',
  },
]

interface CartLine {
  product: CustomerProduct
  size: string
  quantity: number
}

export default function Shop() {
  const [searchParams, setSearchParams] = useSearchParams()
  const linkedProductId = Number(searchParams.get('product'))
  const [products, setProducts] = useState<CustomerProduct[]>([])
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('')
  const [selected, setSelected] = useState<CustomerProduct | null>(null)
  const [selectedSize, setSelectedSize] = useState('')
  const [cart, setCart] = useState<CartLine[]>([])
  const [cartOpen, setCartOpen] = useState(false)
  const [checkingOut, setCheckingOut] = useState(false)

  useEffect(() => {
    let active = true
    setLoading(true)
    const selectedCategory = categories.find((item) => item.value === category)
    listCustomerProducts({
      mainCategory: selectedCategory?.main,
      subCategory: category || undefined,
      query: query.trim() || undefined,
      pageSize: 96,
    })
      .then((result) => active && setProducts(result.items))
      .catch((error) => active && message.error(error.message))
      .finally(() => active && setLoading(false))
    return () => { active = false }
  }, [category, query])

  useEffect(() => {
    if (!linkedProductId || !products.length) return
    const product = products.find((item) => item.id === linkedProductId)
    if (product) {
      setSelected(product)
      setSelectedSize(product.sizes[0] || '')
    }
  }, [products, linkedProductId])

  const cartCount = cart.reduce((sum, line) => sum + line.quantity, 0)
  const cartTotal = useMemo(
    () => cart.reduce((sum, line) => sum + line.product.price_cent * line.quantity, 0),
    [cart],
  )

  const openProduct = (product: CustomerProduct) => {
    setSelected(product)
    setSelectedSize(product.sizes[0] || '')
  }

  const closeProduct = () => {
    setSelected(null)
    if (!searchParams.has('product')) return
    const next = new URLSearchParams(searchParams)
    next.delete('product')
    setSearchParams(next, { replace: true })
  }

  const browseCategory = (value: string) => {
    setCategory(value)
    window.requestAnimationFrame(() => document.getElementById('product-catalog')?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  }

  const addToCart = () => {
    if (!selected || !selectedSize) {
      message.warning('请先选择尺码')
      return
    }
    setCart((current) => {
      const index = current.findIndex((line) => line.product.id === selected.id && line.size === selectedSize)
      if (index < 0) return [...current, { product: selected, size: selectedSize, quantity: 1 }]
      return current.map((line, i) => i === index ? { ...line, quantity: Math.min(10, line.quantity + 1) } : line)
    })
    closeProduct()
    message.success('已加入购物袋')
  }

  const updateQuantity = (index: number, delta: number) => {
    setCart((current) => current
      .map((line, i) => i === index ? { ...line, quantity: line.quantity + delta } : line)
      .filter((line) => line.quantity > 0))
  }

  const checkout = async () => {
    if (!cart.length) return
    setCheckingOut(true)
    try {
      const order = await createCustomerOrder(cart.map((line) => ({
        product_id: line.product.id,
        size: line.size,
        color: line.product.color,
        quantity: line.quantity,
      })))
      setCart([])
      setCartOpen(false)
      Modal.success({
        title: '下单成功',
        content: `订单 ${order.order_no} 已生成，金额 ¥${order.total_yuan}。可到“我的订单”申请退款。`,
      })
    } catch (error: any) {
      message.error(error.message || '下单失败')
    } finally {
      setCheckingOut(false)
    }
  }

  return (
    <div className="shop-page">
      <Carousel className="shop-carousel" autoplay autoplaySpeed={5200} pauseOnHover draggable>
        {heroSlides.map((slide) => (
          <section className={`shop-hero shop-hero-${slide.tone}`} key={slide.title}>
            <div className="shop-hero-copy">
              <span className="shop-hero-eyebrow">{slide.eyebrow}</span>
              <Typography.Title level={1}>{slide.title}</Typography.Title>
              <Typography.Paragraph>{slide.description}</Typography.Paragraph>
              <Button type="primary" size="large" onClick={() => browseCategory(slide.category)}>
                {slide.action} <ArrowRightOutlined />
              </Button>
              <span className="shop-hero-note">{slide.note}</span>
            </div>
            <img className="shop-hero-image" src={slide.image} alt={slide.title} />
          </section>
        ))}
      </Carousel>

      <div className="shop-benefits" aria-label="购物服务">
        <span><ThunderboltOutlined /> 48小时内发货</span>
        <span><FireOutlined /> 50款男装精选</span>
        <span><CheckOutlined /> 尺码售后无忧</span>
      </div>

      <section className="shop-promo-panel" aria-label="店铺优惠">
        <div className="shop-promo-lead">
          <span className="shop-promo-kicker"><GiftOutlined /> MISTER 礼遇</span>
          <Typography.Title level={3}>现在下单，穿搭一步到位</Typography.Title>
          <Typography.Text type="secondary">精选男装限时优惠，结算时自动计算活动价格。</Typography.Text>
        </div>
        <div className="shop-promo-items">
          <div className="shop-promo-item shop-promo-orange">
            <strong>新人首单立减 ¥20</strong>
            <span>登录后下单即可使用</span>
          </div>
          <div className="shop-promo-item shop-promo-red">
            <strong>满 ¥199 免运费</strong>
            <span>多买一件，搭配更划算</span>
          </div>
          <div className="shop-promo-item shop-promo-green">
            <strong><SafetyCertificateOutlined /> 7天无理由</strong>
            <span>尺码不合适也能放心换</span>
          </div>
        </div>
      </section>

      <div className="catalog-heading section-split" id="product-catalog">
        <div>
          <Typography.Text className="catalog-kicker"><FireOutlined /> MEN'S PICKS</Typography.Text>
          <Typography.Title level={2}>男装精选</Typography.Title>
        </div>
      </div>

      <Card className="toolbar-card" size="small">
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Input
            allowClear
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            prefix={<SearchOutlined />}
            placeholder="搜索 T恤、牛仔裤、夹克……"
            size="large"
          />
          <div className="category-row">
            <Segmented
              value={category}
              options={categories.map(({ value, label }) => ({ value, label }))}
              onChange={(value) => setCategory(String(value))}
            />
          </div>
        </Space>
      </Card>

      <div className="section-split">
        <Typography.Title level={4} style={{ margin: 0 }}>
          {categories.find((item) => item.value === category)?.label || '全部商品'}
        </Typography.Title>
        <Typography.Text type="secondary">共 {products.length} 件 · 分类以人工标签为准</Typography.Text>
      </div>

      {loading ? (
        <div className="empty-state"><Spin size="large" /></div>
      ) : products.length ? (
        <div className="product-grid">
          {products.map((product, index) => (
            <Card
              key={product.id}
              hoverable
              className="product-card"
              cover={
                <div className="product-image-wrap">
                  <img className="product-image" src={product.image_url || '/product-placeholder.png'} alt={product.name} />
                </div>
              }
              onClick={() => openProduct(product)}
            >
              <div className="product-meta">
                <span className={`product-badge ${index % 4 === 0 ? 'hot' : ''}`}>
                  {index % 4 === 0 ? '人气' : '新选'}
                </span>
                <Typography.Text className="product-name" title={product.name}>{product.name}</Typography.Text>
                <div className="product-tags">
                  <Tag>{product.sub_category_label}</Tag><Tag>{product.color}</Tag>
                </div>
                <div className="section-split" style={{ margin: 0 }}>
                  <span className="product-price">¥{product.price_yuan}</span>
                  <Button type="text" icon={<ShoppingCartOutlined />} aria-label={`选购${product.name}`} title="选择尺码" />
                </div>
              </div>
            </Card>
          ))}
        </div>
      ) : (
        <div className="empty-state"><Empty description="没有找到符合条件的商品" /></div>
      )}

      <Badge count={cartCount} overflowCount={99} showZero className="floating-cart-badge">
        <Button
          className="floating-cart-button"
          type="primary"
          icon={<ShoppingCartOutlined />}
          onClick={() => setCartOpen(true)}
          aria-label={`打开购物袋，${cartCount} 件商品`}
        >
          购物袋
        </Button>
      </Badge>

      <Modal
        open={Boolean(selected)}
        title={selected?.name}
        onCancel={closeProduct}
        onOk={addToCart}
        okText="加入购物袋"
        cancelText="继续浏览"
        width={760}
      >
        {selected && (
          <div className="modal-product">
            <img src={selected.image_url || '/product-placeholder.png'} alt={selected.name} />
            <Space direction="vertical" size="middle" style={{ width: '100%' }}>
              <div>
                <Tag color="green">{selected.main_category_label}</Tag>
                <Tag>{selected.sub_category_label}</Tag>
                {selected.is_demo && <Tag color="gold">演示商品</Tag>}
              </div>
              <Typography.Title level={2} style={{ margin: 0 }}>¥{selected.price_yuan}</Typography.Title>
              <Typography.Paragraph>{selected.description}</Typography.Paragraph>
              <Typography.Text><strong>颜色：</strong>{selected.color}</Typography.Text>
              <Typography.Text><strong>面料/版型：</strong>{selected.fabric || '以商品实物为准'}</Typography.Text>
              <Typography.Text><strong>穿着建议：</strong>{selected.fit_notes || '按日常尺码选购'}</Typography.Text>
              <div>
                <Typography.Text strong>选择尺码</Typography.Text>
                <div className="size-options" style={{ marginTop: 10 }}>
                  {selected.sizes.map((size) => (
                    <Button
                      key={size}
                      className="size-button"
                      type={selectedSize === size ? 'primary' : 'default'}
                      icon={selectedSize === size ? <CheckOutlined /> : undefined}
                      onClick={() => setSelectedSize(size)}
                    >
                      {size}
                    </Button>
                  ))}
                </div>
              </div>
            </Space>
          </div>
        )}
      </Modal>

      <Drawer
        title={`购物袋（${cartCount} 件）`}
        open={cartOpen}
        width={460}
        onClose={() => setCartOpen(false)}
        footer={
          <Space direction="vertical" style={{ width: '100%' }}>
            <div className="section-split" style={{ margin: 0 }}>
              <Typography.Text>合计</Typography.Text>
              <span className="product-price">¥{(cartTotal / 100).toFixed(2)}</span>
            </div>
            <Button type="primary" size="large" block disabled={!cart.length} loading={checkingOut} onClick={checkout}>
              模拟结算
            </Button>
          </Space>
        }
      >
        {cart.length ? (
          <List
            dataSource={cart}
            renderItem={(line, index) => (
              <List.Item>
                <div className="cart-line">
                  <img src={line.product.image_url || '/product-placeholder.png'} alt={line.product.name} />
                  <div>
                    <Typography.Text strong>{line.product.name}</Typography.Text><br />
                    <Typography.Text type="secondary">{line.size} / {line.product.color}</Typography.Text><br />
                    <Typography.Text>¥{line.product.price_yuan}</Typography.Text>
                  </div>
                  <Space.Compact>
                    <Button onClick={() => updateQuantity(index, -1)} icon={line.quantity === 1 ? <DeleteOutlined /> : undefined}>
                      {line.quantity === 1 ? null : '-'}
                    </Button>
                    <Button disabled>{line.quantity}</Button>
                    <Button onClick={() => updateQuantity(index, 1)} disabled={line.quantity >= 10}>+</Button>
                  </Space.Compact>
                </div>
              </List.Item>
            )}
          />
        ) : <Empty description="购物袋还是空的" />}
      </Drawer>
    </div>
  )
}
