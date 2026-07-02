"""
Delivery Tools - Send notifications via various channels

Implements:
- send_email
- send_sms
- send_alert
"""

import os
from datetime import datetime
from typing import Dict, Any, Optional
from loguru import logger
from dotenv import load_dotenv
load_dotenv()


async def send_email(
    to: str,
    subject: str,
    body: str,
    html: bool = False,
    config: Any = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Send email notification.

    Uses SendGrid in production.
    """
    logger.info(f"Sending email to {to}: {subject}")

    result = {
        'to': to,
        'subject': subject,
        'status': 'pending',
        'sent_at': datetime.utcnow().isoformat()
    }

    # Check for SendGrid API key
    sendgrid_key = os.getenv('SENDGRID_API_KEY')

    if sendgrid_key:
        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail, Email, To, Content

            message = Mail(
                from_email=Email(os.getenv('SENDGRID_FROM', 'alpha-trader@example.com')),
                to_emails=To(to),
                subject=subject,
                plain_text_content=body if not html else None,
                html_content=body if html else None
            )

            sg = SendGridAPIClient(sendgrid_key)
            response = sg.send(message)

            result['status'] = 'sent' if response.status_code == 202 else 'failed'
            result['status_code'] = response.status_code

        except Exception as e:
            logger.error(f"SendGrid error: {e}")
            result['status'] = 'failed'
            result['error'] = str(e)
    else:
        # Simulation mode
        result['status'] = 'simulated'
        logger.warning("Email simulated (SendGrid not configured)")

    return result


async def send_sms(
    to: str,
    message: str,
    config: Any = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Send SMS notification via Twilio.
    """
    logger.info(f"Sending SMS to {to}")

    result = {
        'to': to,
        'message_length': len(message),
        'status': 'pending',
        'sent_at': datetime.utcnow().isoformat()
    }

    # Check for Twilio credentials
    account_sid = os.getenv('TWILIO_ACCOUNT_SID')
    auth_token = os.getenv('TWILIO_AUTH_TOKEN')
    from_number = os.getenv('TWILIO_FROM_NUMBER')

    if account_sid and auth_token and from_number:
        try:
            from twilio.rest import Client

            client = Client(account_sid, auth_token)

            sms = client.messages.create(
                body=message,
                from_=from_number,
                to=to
            )

            result['status'] = 'sent'
            result['message_sid'] = sms.sid

        except Exception as e:
            logger.error(f"Twilio error: {e}")
            result['status'] = 'failed'
            result['error'] = str(e)
    else:
        # Simulation mode
        result['status'] = 'simulated'
        logger.warning("SMS simulated (Twilio not configured)")

    return result


async def send_telegram(
    message: str,
    config: Any = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Send notification via Telegram Bot API.
    """
    logger.info("Sending Telegram message")

    token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')

    result = {
        'status': 'pending',
        'sent_at': datetime.utcnow().isoformat()
    }

    if token and chat_id:
        try:
            import aiohttp
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {
                'chat_id': chat_id,
                'text': message,
                'parse_mode': 'Markdown'
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        result['status'] = 'sent'
                    else:
                        error_text = await resp.text()
                        logger.error(f"Telegram error: {error_text}")
                        result['status'] = 'failed'
                        result['error'] = error_text
        except Exception as e:
            logger.error(f"Telegram exception: {e}")
            result['status'] = 'failed'
            result['error'] = str(e)
    else:
        result['status'] = 'simulated'
        logger.warning("Telegram simulated (Token/ChatID not configured)")

    return result




async def send_hermes(
    message: str,
    **kwargs
) -> Dict[str, Any]:
    """
    Send notification via Hermes/Photon iMessage sidecar.
    Requires PHOTON_SIDECAR_URL, PHOTON_SIDECAR_TOKEN, PHOTON_HOME_CHANNEL env vars.
    """
    import aiohttp

    sidecar_url = os.getenv("PHOTON_SIDECAR_URL", "http://127.0.0.1:8789")
    token = os.getenv("PHOTON_SIDECAR_TOKEN")
    channel = os.getenv("PHOTON_HOME_CHANNEL")

    result = {
        "status": "pending",
        "sent_at": datetime.utcnow().isoformat(),
    }

    if not token or not channel:
        result["status"] = "simulated"
        logger.warning("Hermes simulated (PHOTON_SIDECAR_TOKEN or PHOTON_HOME_CHANNEL not set)")
        return result

    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "spaceId": channel,
                "text": message,
                "format": "text",
            }
            async with session.post(
                f"{sidecar_url}/send",
                json=payload,
                headers={"X-Hermes-Sidecar-Token": token},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    result["status"] = "sent"
                    result["message_id"] = data.get("messageId")
                else:
                    text = await resp.text()
                    logger.error(f"Hermes send failed: {text}")
                    result["status"] = "failed"
                    result["error"] = text
    except Exception as e:
        logger.error(f"Hermes exception: {e}")
        result["status"] = "failed"
        result["error"] = str(e)

    return result

async def send_alert(
    message: str,
    severity: str = "warning",
    config: Any = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Send alert via all configured channels.

    Severity levels: info, warning, critical
    """
    logger.info(f"Sending {severity} alert: {message[:50]}...")

    result = {
        'severity': severity,
        'channels': [],
        'sent_at': datetime.utcnow().isoformat()
    }

    notifications = config.notifications if config else None

    # Prefix based on severity
    prefixes = {
        'info': 'INFO',
        'warning': 'ALERT',
        'critical': 'CRITICAL'
    }
    prefix = prefixes.get(severity, 'ALERT')
    formatted_message = f"[{prefix}] {message}"

    # Send via email if enabled
    if notifications and notifications.email_enabled and notifications.email_to:
        email_result = await send_email(
            to=notifications.email_to,
            subject=f"Alpha Trader {prefix}",
            body=formatted_message,
            config=config
        )
        result['channels'].append({
            'type': 'email',
            'status': email_result['status']
        })

    # Send via SMS if enabled (only for warning and critical)
    if notifications and notifications.sms_enabled and notifications.sms_to:
        if severity in ['warning', 'critical']:
            sms_result = await send_sms(
                to=notifications.sms_to,
                message=formatted_message[:160],  # SMS character limit
                config=config
            )
            result['channels'].append({
                'type': 'sms',
                'status': sms_result['status']
            })

    # Log to console regardless
    if severity == 'critical':
        logger.critical(formatted_message)
    elif severity == 'warning':
        logger.warning(formatted_message)
    else:
        logger.info(formatted_message)

    result['channels'].append({
        'type': 'log',
        'status': 'sent'
    })

    return result


async def send_trade_alert(message: str, notify_telegram: bool = True) -> Dict[str, Any]:
    """
    Send a trade alert via Hermes (primary) and optionally Telegram.
    Use this for entry, exit, stop-loss, and major milestone notifications.
    """
    results = []
    hermes_result = await send_hermes(message)
    results.append({"channel": "hermes", "status": hermes_result.get("status")})

    if notify_telegram:
        telegram_result = await send_telegram(message)
        results.append({"channel": "telegram", "status": telegram_result.get("status")})

    return {
        "status": "sent" if any(r["status"] == "sent" for r in results) else "failed",
        "channels": results,
        "sent_at": datetime.utcnow().isoformat(),
    }
