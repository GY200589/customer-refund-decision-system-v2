import React from "react";
import { useNavigate } from "react-router-dom";
import { Button, Menu, Typography } from "antd";
import { useAuth } from "../hooks/useAuth";
import { useTranslation } from "react-i18next";

const { Title, Text } = Typography;

const menuItems = [
  { key: "shop", label: "首页" },
  { key: "orders", label: "我的订单" },
  { key: "refunds", label: "我的退款" },
  { key: "assistant", label: "智能客服" },
];

export const Layout = () => {
  const { t } = useTranslation();
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  if (!user || user.role !== "customer") {
    navigate("/login");
    return null;
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* 顶部导航 */}
      <div className="bg-white shadow-sm border-b">
        <div className="max-w-7xl mx-auto px-4">
          <div className="flex justify-between items-center h-16">
            <div className="flex items-center">
              <img src="/logo.png" alt="Logo" className="h-8" />
              <span className="ml-2 text-lg font-semibold">{t("男装商城")}</span>
            </div>
            <div className="flex items-center space-x-4">
              <Menu
                mode="horizontal"
                selectedKeys={[window.location.pathname.split("/")[2] || "shop"]}
                items={menuItems}
                onClick={({ key }) => navigate(`/${key}`)}
              />
              <Button type="link" onClick={logout}>
                {t("退出")}
              </Button>
            </div>
          </div>
        </div>
      </div>

      {/* 内容区域 */}
      <div className="max-w-7xl mx-auto px-4 py-6">
        <Outlet />
      </div>
    </div>
  );
};

export default Layout;