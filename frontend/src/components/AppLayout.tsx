import { Layout, Menu, Space, Typography, Button } from 'antd'
import { useLocation, useNavigate } from 'react-router-dom'
import type { ReactNode } from 'react'
import { clearAuth, getUser } from '../api'

const { Header, Content } = Layout

export default function AppLayout({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  const location = useLocation()
  const user = getUser()

  const items = [
    { key: '/', label: '案件列表' },
    ...(['supervisor', 'admin'].includes(user?.role || '') ? [{ key: '/review', label: '审批中心' }] : []),
    ...(user?.role === 'admin' ? [{ key: '/admin', label: '系统管理' }] : []),
  ]

  const logout = () => {
    clearAuth()
    navigate('/login', { replace: true })
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Space size="large">
          <Typography.Text strong style={{ color: '#fff', fontSize: 16 }}>
            客诉舆情退赔决策系统
          </Typography.Text>
          <Menu
            theme="dark"
            mode="horizontal"
            selectedKeys={[location.pathname]}
            items={items}
            onClick={(e) => navigate(e.key)}
            style={{ minWidth: 220 }}
          />
        </Space>
        <Space>
          <Typography.Text style={{ color: 'rgba(255,255,255,0.85)' }}>
            {user?.display_name}（{user?.role}）
          </Typography.Text>
          <Button size="small" onClick={logout}>
            退出
          </Button>
        </Space>
      </Header>
      <Content style={{ padding: 24 }}>{children}</Content>
    </Layout>
  )
}
