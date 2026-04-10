"""
通知服务 - 邮件/短信/推送

====================================================
通知渠道配置说明
====================================================
1. 邮件通知: 在 .env 配置 SMTP 相关参数
2. 短信通知: 在 .env 配置阿里云SMS相关参数
3. 推送通知: 预留接口，可接入微信推送/钉钉等
====================================================
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from loguru import logger
from config.settings import settings


class NotificationService:
    """通知服务"""

    async def send_price_alert(self, alert_data: dict):
        """
        发送价格提醒

        alert_data: {
            "alert": PriceAlert对象,
            "product": Product对象,
            "current_price": float,
            "target_price": float,
        }
        """
        alert = alert_data["alert"]
        product = alert_data["product"]
        price = alert_data["current_price"]
        target = alert_data["target_price"]

        message = (
            f"商品降价提醒！\n\n"
            f"商品: {product.title}\n"
            f"平台: {'淘宝' if product.platform == 'taobao' else '得物'}\n"
            f"当前价格: ¥{price}\n"
            f"目标价格: ¥{target}\n"
            f"链接: {product.url or '暂无'}\n"
        )

        if alert.notify_email:
            await self.send_email(
                to=None,  # 需从用户表获取
                subject=f"降价提醒 - {product.title}",
                body=message,
                user_id=alert.user_id,
            )

        if alert.notify_sms:
            await self.send_sms(
                phone=None,  # 需从用户表获取
                message=message,
                user_id=alert.user_id,
            )

        if alert.notify_push:
            await self.send_push(
                user_id=alert.user_id,
                title="商品降价提醒",
                body=message,
            )

    async def send_email(self, to: Optional[str], subject: str, body: str, user_id: int = 0):
        """
        发送邮件通知

        ============================================
        请在 .env 中配置SMTP参数:
          SMTP_HOST=smtp.qq.com
          SMTP_PORT=465
          SMTP_USER=你的邮箱
          SMTP_PASSWORD=授权码
          SMTP_FROM=发件地址
        ============================================
        """
        if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
            logger.warning("[邮件] 未配置SMTP，跳过发送")
            return False

        try:
            msg = MIMEMultipart()
            msg["From"] = settings.SMTP_FROM or settings.SMTP_USER
            msg["To"] = to or settings.SMTP_USER  # 未指定收件人则发给自己
            msg["Subject"] = subject

            # HTML邮件内容
            html = f"""
            <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #e74c3c;">💰 {subject}</h2>
                <div style="background: #f8f9fa; padding: 20px; border-radius: 8px;">
                    <pre style="white-space: pre-wrap;">{body}</pre>
                </div>
                <p style="color: #999; font-size: 12px; margin-top: 20px;">
                    —— 来自跨平台智能比价系统
                </p>
            </div>
            """
            msg.attach(MIMEText(html, "html", "utf-8"))

            with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT) as server:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)

            logger.info(f"[邮件] 发送成功: {to}")
            return True
        except Exception as e:
            logger.error(f"[邮件] 发送失败: {e}")
            return False

    async def send_sms(self, phone: Optional[str], message: str, user_id: int = 0):
        """
        发送短信通知

        ============================================
        API接口预留位置 - 阿里云短信
        ============================================
        请在 .env 中配置:
          SMS_ACCESS_KEY=你的AccessKey
          SMS_ACCESS_SECRET=你的AccessSecret
          SMS_SIGN_NAME=签名
          SMS_TEMPLATE_CODE=模板编号

        实现示例 (阿里云SDK):
            from alibabacloud_dysmsapi20170525.client import Client
            from alibabacloud_tea_openapi.models import Config

            config = Config(
                access_key_id=settings.SMS_ACCESS_KEY,
                access_key_secret=settings.SMS_ACCESS_SECRET,
            )
            client = Client(config)
            # ... 调用发送接口
        ============================================
        """
        if not settings.SMS_ACCESS_KEY:
            logger.warning("[短信] 未配置短信API，跳过发送")
            return False

        # >>> 在此实现短信发送逻辑 <<<
        logger.info(f"[短信] 发送至 {phone}: {message[:50]}...")
        return True

    async def send_push(self, user_id: int, title: str, body: str):
        """
        发送推送通知

        ============================================
        API接口预留位置 - 推送服务
        ============================================
        可接入以下推送渠道:

        1. 微信推送 (Server酱/PushPlus):
            import httpx
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://sctapi.ftqq.com/你的KEY.send",
                    data={"title": title, "desp": body},
                )

        2. 钉钉机器人:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://oapi.dingtalk.com/robot/send?access_token=xxx",
                    json={"msgtype": "text", "text": {"content": body}},
                )

        3. Bark (iOS推送):
            import httpx
            async with httpx.AsyncClient() as client:
                await client.get(f"https://api.day.app/你的KEY/{title}/{body}")
        ============================================
        """
        logger.info(f"[推送] 用户{user_id}: {title}")
        return True
