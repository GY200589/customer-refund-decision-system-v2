import {
  HomeOutlined,
  LogoutOutlined,
  OrderedListOutlined,
  RedoOutlined,
  RobotOutlined,
  ShopOutlined,
} from '@ant-design/icons'
import { Button, Layout as AntLayout, Menu, Modal, Space, Tooltip, Typography } from 'antd'
import { useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { clearAuth, getUser } from '../api'
import Assistant from '../pages/Assistant'

const { Header, Content } = AntLayout

const navigation = [
  { key: '/shop', icon: <HomeOutlined />, label: '购物大厅' },
  { key: '/orders', icon: <OrderedListOutlined />, label: '我的订单' },
  { key: '/refunds', icon: <RedoOutlined />, label: '退款进度' },
]

export default function CustomerLayout() {
  const location = useLocation()
  const navigate = useNavigate()
  const user = getUser()
  const [assistantOpen, setAssistantOpen] = useState(false)
  const selectedMenu = location.pathname.startsWith('/refunds') ? '/refunds' : location.pathname

  const logout = () => {
    clearAuth()
    navigate('/login', { replace: true })
  }

  return (
    <AntLayout className="customer-shell">
      <Header className="customer-header">
        <button className="brand-button" onClick={() => navigate('/shop')} aria-label="返回购物大厅">
          <span className="brand-mark"><ShopOutlined /></span>
          <span>
            <Typography.Text className="brand-name">MISTER 男装</Typography.Text>
            <Typography.Text className="brand-subtitle">售前售后一站式服务</Typography.Text>
          </span>
        </button>
        <Menu
          mode="horizontal"
          selectedKeys={[selectedMenu]}
          items={navigation}
          onClick={({ key }) => navigate(key)}
          className="customer-menu"
        />
        <Space className="customer-account" size="small">
          <span className="account-copy">{user?.display_name || user?.username}</span>
          <Button type="text" icon={<LogoutOutlined />} onClick={logout} title="退出登录" aria-label="退出登录" />
        </Space>
      </Header>
      <Content className="customer-content">
        <Outlet />
      </Content>
      {location.pathname !== '/assistant' && (
        <Tooltip title="智能客服" placement="left">
          <Button
            className="floating-assistant-button"
            type="primary"
            shape="circle"
            onClick={() => setAssistantOpen(true)}
            aria-label="打开智能客服"
          >
            <span className="floating-assistant-icon"><RobotOutlined /></span>
            <span className="floating-assistant-online" />
          </Button>
        </Tooltip>
      )}
      <Modal
        open={assistantOpen}
        onCancel={() => setAssistantOpen(false)}
        footer={null}
        closable={false}
        width={1040}
        destroyOnClose
        centered
        className="assistant-overlay-modal"
        maskClosable
      >
        <Assistant embedded onClose={() => setAssistantOpen(false)} />
      </Modal>
    </AntLayout>
  )
}
