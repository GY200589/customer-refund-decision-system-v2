import { LockOutlined, SafetyCertificateOutlined, UserOutlined } from '@ant-design/icons'
import { Button, Form, Input, Segmented, Space, Typography, message } from 'antd'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getUser, login, setAuth } from '../api'

const demoAccounts = [
  { label: '顾客演示', value: 'customer1' },
  { label: '客服工作台', value: 'agent1' },
  { label: '主管审批', value: 'supervisor1' },
  { label: '系统管理', value: 'admin1' },
]

export default function Login() {
  const navigate = useNavigate()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [demoUser, setDemoUser] = useState('customer1')

  useEffect(() => {
    const user = getUser()
    if (user) navigate(user.role === 'customer' ? '/shop' : '/', { replace: true })
  }, [navigate])

  const selectDemo = (username: string) => {
    setDemoUser(username)
    form.setFieldsValue({ username, password: 'password123' })
  }

  const submit = async (values: { username: string; password: string }) => {
    setLoading(true)
    try {
      const result = await login(values.username, values.password)
      setAuth(result.token, result.user)
      message.success(`欢迎，${result.user.display_name}`)
      navigate(result.user.role === 'customer' ? '/shop' : '/', { replace: true })
    } catch (error: any) {
      message.error(error.message || '登录失败，请检查用户名和密码')
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="login-page">
      <section className="login-intro">
        <div className="login-brand"><SafetyCertificateOutlined /> 客诉退赔决策系统</div>
        <Typography.Title>从购买到售后，<br />一套流程走到底</Typography.Title>
        <Typography.Paragraph>
          顾客可以模拟购买男装、提交退款和咨询智能客服；客服与主管继续使用原有案件工作台。
        </Typography.Paragraph>
        <div className="login-feature-row">
          <span>男装商城</span><span>退款联动</span><span>RAG 客服</span><span>语音输入</span>
        </div>
      </section>

      <section className="login-panel">
        <div>
          <Typography.Title level={2}>登录系统</Typography.Title>
          <Typography.Text type="secondary">角色权限由服务端账号决定</Typography.Text>
        </div>
        <Segmented
          block
          value={demoUser}
          options={demoAccounts}
          onChange={(value) => selectDemo(String(value))}
        />
        <Form
          form={form}
          layout="vertical"
          initialValues={{ username: 'customer1', password: 'password123' }}
          onFinish={submit}
          requiredMark={false}
        >
          <Form.Item label="用户名" name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} size="large" autoComplete="username" />
          </Form.Item>
          <Form.Item label="密码" name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} size="large" autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" size="large" loading={loading} block>
            登录
          </Button>
        </Form>
        <Space direction="vertical" size={2}>
          <Typography.Text type="secondary">演示账号密码统一为 password123</Typography.Text>
          <Typography.Text type="secondary">可点击上方身份快速切换账号</Typography.Text>
        </Space>
      </section>
    </main>
  )
}
