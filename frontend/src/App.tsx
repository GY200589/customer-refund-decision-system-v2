import { Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { getUser } from './api'
import CustomerLayout from './components/Layout'
import Admin from './pages/Admin'
import Assistant from './pages/Assistant'
import CaseDetail from './pages/CaseDetail'
import Dashboard from './pages/Dashboard'
import Login from './pages/Login'
import Orders from './pages/Orders'
import Refunds from './pages/Refunds'
import RefundDetail from './pages/RefundDetail'
import ReviewCenter from './pages/ReviewCenter'
import Shop from './pages/Shop'

function RequireStaff() {
  const user = getUser()
  if (!user) return <Navigate to="/login" replace />
  if (user.role === 'customer') return <Navigate to="/shop" replace />
  return <Outlet />
}

function RequireCustomer() {
  const user = getUser()
  if (!user) return <Navigate to="/login" replace />
  if (user.role !== 'customer') return <Navigate to="/" replace />
  return <CustomerLayout />
}

function RequireReviewer({ children }: { children: JSX.Element }) {
  const user = getUser()
  if (!user) return <Navigate to="/login" replace />
  if (!['supervisor', 'admin'].includes(user.role)) return <Navigate to="/" replace />
  return children
}

function RequireAdmin({ children }: { children: JSX.Element }) {
  const user = getUser()
  if (!user) return <Navigate to="/login" replace />
  if (user.role !== 'admin') return <Navigate to="/" replace />
  return children
}

function RoleHome() {
  const user = getUser()
  if (!user) return <Navigate to="/login" replace />
  return <Navigate to={user.role === 'customer' ? '/shop' : '/'} replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />

      <Route element={<RequireCustomer />}>
        <Route path="/shop" element={<Shop />} />
        <Route path="/orders" element={<Orders />} />
        <Route path="/refunds" element={<Refunds />} />
        <Route path="/refunds/:caseId" element={<RefundDetail />} />
        <Route path="/assistant" element={<Assistant />} />
      </Route>

      <Route element={<RequireStaff />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/cases/:caseId" element={<CaseDetail />} />
        <Route path="/review" element={<RequireReviewer><ReviewCenter /></RequireReviewer>} />
        <Route path="/admin" element={<RequireAdmin><Admin /></RequireAdmin>} />
      </Route>

      <Route path="*" element={<RoleHome />} />
    </Routes>
  )
}
