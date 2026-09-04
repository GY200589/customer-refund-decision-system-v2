// 404 页面：未登录或无权限时的通用提示。
//
// - 显示错误信息：您无权访问此页面，请登录或检查权限；
// - 返回首页按钮：点击后跳转到登录页。
import { useNavigate } from "react-router-dom";
import { Button, Result } from "antd";
import { useTranslation } from "react-i18next";

export const NotFound = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();

  return (
    <Result
      status="404"
      title={t("404")}
      subTitle={t("您无权访问此页面，请登录或检查权限")}
      extra={
        <Button type="primary" onClick={() => navigate("/login")}>
          {t("返回首页")}
        </Button>
      }
    />
  );
};

export default NotFound;