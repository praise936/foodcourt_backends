import json
import os
import firebase_admin
from firebase_admin import credentials, messaging

# Initialize Firebase Admin SDK once
_firebase_app = None

def _get_app():
    global _firebase_app
    if _firebase_app is None:
        service_account = os.environ.get('FIREBASE_SERVICE_ACCOUNT', '{}')
        if isinstance(service_account, str):
            service_account = json.loads(service_account)
        cred = credentials.Certificate(service_account)
        _firebase_app = firebase_admin.initialize_app(cred)
    return _firebase_app


def send_push(token: str, title: str, body: str, data: dict = None):
    """Send push notification to a single device."""
    if not token:
        print('⚠️ FCM: No token provided, skipping send_push')
        return None
    try:
        _get_app()
        token_preview = f"{token[:10]}...{token[-6:]}" if isinstance(token, str) and len(token) > 20 else str(token)
        print(f"ℹ️ FCM: send_push token={token_preview} title={title} data={data or {}}")
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in (data or {}).items()},
            token=token,
            android=messaging.AndroidConfig(
                priority='high',
                notification=messaging.AndroidNotification(
                    channel_id='foodcourt_orders',
                    sound='default',
                ),
            ),
            webpush=messaging.WebpushConfig(
                notification=messaging.WebpushNotification(
                    title=title,
                    body=body,
                    icon='/icons/Icon-192.png',
                ),
            ),
        )
        response = messaging.send(message)
        print(f'✅ FCM sent: {response}')
        return response
    except Exception as e:
        print(f'❌ FCM error: {e}')
        return None


def send_multicast(tokens: list, title: str, body: str, data: dict = None):
    """Send push notification to multiple devices."""
    tokens = [t for t in tokens if t]  # filter empty tokens
    if not tokens:
        print('⚠️ FCM: No tokens, skipping multicast')
        return None
    try:
        _get_app()
        print(f"ℹ️ FCM: send_multicast tokens={len(tokens)} title={title} data={data or {}}")
        message = messaging.MulticastMessage(
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in (data or {}).items()},
            tokens=tokens,
            android=messaging.AndroidConfig(
                priority='high',
                notification=messaging.AndroidNotification(
                    channel_id='foodcourt_orders',
                    sound='default',
                ),
            ),
            webpush=messaging.WebpushConfig(
                notification=messaging.WebpushNotification(
                    title=title,
                    body=body,
                    icon='/icons/Icon-192.png',
                ),
            ),
        )
        response = messaging.send_each_for_multicast(message)
        print(f'✅ FCM multicast: {response.success_count} sent, {response.failure_count} failed')
        return response
    except Exception as e:
        print(f'❌ FCM multicast error: {e}')
        return None


def notify_order_update(order):
    """Notify customer when their order status changes."""
    customer = order.customer
    if not customer.fcm_token:
        return

    status_messages = {
        'confirmed': ('Order Confirmed! 🎉', f'Your order from {order.restaurant.name} has been confirmed.'),
        'preparing': ('Being Prepared 👨‍🍳', f'{order.restaurant.name} is preparing your order.'),
        'ready': ('Order Ready! 🍽️', f'Your order from {order.restaurant.name} is ready for pickup.'),
        'completed': ('Order Complete ✅', 'Enjoy your meal! Don\'t forget to leave a review.'),
        'cancelled': ('Order Cancelled ❌', f'Your order from {order.restaurant.name} was cancelled.'),
    }

    if order.status in status_messages:
        title, body = status_messages[order.status]
        send_push(
            token=customer.fcm_token,
            title=title,
            body=body,
            data={
                'type': 'order_update',
                'order_id': str(order.id),
                'status': order.status,
                'restaurant_id': str(order.restaurant_id),
            },
        )


def notify_new_order(order):
    """Notify restaurant manager when new order arrives."""
    manager = order.restaurant.manager
    if not manager or not manager.fcm_token:
        return

    send_push(
        token=manager.fcm_token,
        title='New Order! 🛒',
        body=f'Order #{str(order.id)[:8]} received — KSh {order.total_amount}',
        data={
            'type': 'new_order',
            'order_id': str(order.id),
            'restaurant_id': str(order.restaurant_id),
        },
    )