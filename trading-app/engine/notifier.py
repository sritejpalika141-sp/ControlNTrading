import asyncio
import httpx
import logging
logger = logging.getLogger("notifier")

# Suppress httpx INFO logs that leak full URLs (including Telegram bot tokens)
logging.getLogger("httpx").setLevel(logging.WARNING)

async def send_webhook_alert(webhook_url, message, title="Sritej Trading Alert"):
    """
    Sends a generic webhook alert (compatible with Discord and generic webhooks).
    """
    if not webhook_url:
        return
        
    if "api.telegram.org" in webhook_url:
        is_telegram = True
        webhook_url = webhook_url.split("&text=")[0].split("?text=")[0]
    else:
        is_telegram = False

    if is_telegram:
        payload = {
            "text": f"<b>{title}</b>\n{message}",
            "parse_mode": "HTML"
        }
    else:
        payload = {
            "content": f"**{title}**\n{message}",
            "username": "ControlN Trading Bot"
        }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(webhook_url, json=payload)
            if response.status_code not in (200, 204):
                logger.error(f"Webhook failed with status {response.status_code}: {response.text}")
            else:
                logger.info(f"Webhook sent: {title}")
    except Exception as e:
        logger.error(f"Failed to send webhook: {e}")

def trigger_webhook_background(webhook_url, message, title="Sritej Trading Alert"):
    """
    Fire-and-forget webhook alert to be used in sync contexts.
    """
    if not webhook_url:
        return
    
    import threading
    import requests
    
    def _send():
        nonlocal webhook_url
        if "api.telegram.org" in webhook_url:
            is_telegram = True
            webhook_url = webhook_url.split("&text=")[0].split("?text=")[0]
        else:
            is_telegram = False

        if is_telegram:
            payload = {
                "text": f"<b>{title}</b>\n{message}",
                "parse_mode": "HTML"
            }
        else:
            payload = {
                "content": f"**{title}**\n{message}",
                "username": "ControlN Trading Bot"
            }
        try:
            resp = requests.post(webhook_url, json=payload, timeout=10.0)
            if resp.status_code not in (200, 204):
                logger.error(f"Webhook failed with status {resp.status_code}: {resp.text}")
            else:
                logger.info(f"Webhook sent: {title}")
        except Exception as e:
            logger.error(f"Failed to send webhook: {e}")

    threading.Thread(target=_send, daemon=True).start()

