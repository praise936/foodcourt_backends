from django.utils.crypto import get_random_string
from django.contrib.auth import get_user_model
from django.utils.timezone import now
from rest_framework import status, generics
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import CategorySerializer as CS
from .serializers import CategorySerializer
from .fcm import notify_order_update, notify_new_order

from .models import Restaurant, MenuItem, Order, OrderItem, Review, Notification, Category, ChatMessage
from .serializers import (
    UserSerializer, RegisterSerializer, RestaurantSerializer,
    RestaurantDetailSerializer, MenuItemSerializer, OrderSerializer,
    PlaceOrderSerializer, ReviewSerializer, NotificationSerializer,
)
from .serializers import ChatMessageSerializer
from .permissions import IsAdmin, IsManager, IsCustomer, IsAdminOrManager
from .fcm import send_push, send_multicast
from .fcm import _get_app

from firebase_admin import auth as firebase_auth

User = get_user_model()

# dashboard_stats
def get_tokens(user):
    refresh = RefreshToken.for_user(user)
    return {'refresh': str(refresh), 'access': str(refresh.access_token)}


# ── AUTH ──────────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    ser = RegisterSerializer(data=request.data)
    if ser.is_valid():
        user = ser.save()
        return Response({**get_tokens(user), 'user': UserSerializer(user).data},
                        status=status.HTTP_201_CREATED)
    return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def profile(request):
    if request.method == 'GET':
        return Response(UserSerializer(request.user).data)
    ser = UserSerializer(request.user, data=request.data, partial=True)
    if ser.is_valid():
        ser.save()
        return Response(ser.data)
    return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password(request):
    user = request.user
    if not user.check_password(request.data.get('current_password', '')):
        return Response({'detail': 'Current password is incorrect.'}, status=400)
    new_password = request.data.get('new_password', '')
    if len(new_password) < 8:
        return Response({'detail': 'New password must be at least 8 characters.'}, status=400)
    user.set_password(new_password)
    user.save()
    return Response({'detail': 'Password changed successfully.'})


@api_view(['POST'])
@permission_classes([AllowAny])
def password_reset_request(request):
    email = request.data.get('email', '')
    try:
        user = User.objects.get(email=email)
        token = get_random_string(64)
        # In production store token with expiry and send email
        # For now just return success
    except User.DoesNotExist:
        pass
    return Response({'detail': 'If this email exists, a reset link has been sent.'})


@api_view(['POST'])
@permission_classes([AllowAny])
def google_auth(request):
    """Sign in/up with Google using a Firebase ID token, then return backend JWT tokens."""
    id_token = request.data.get('id_token')
    if not id_token:
        return Response({'detail': 'id_token is required.'}, status=400)

    try:
        app = _get_app()
        decoded = firebase_auth.verify_id_token(id_token, app=app)
        email = (decoded.get('email') or '').strip().lower()
        if not email:
            return Response({'detail': 'Google token did not include an email.'}, status=400)

        name = decoded.get('name') or decoded.get('displayName')
        picture = decoded.get('picture')
        email_verified = decoded.get('email_verified', True)

        print(
            f"🔐 GOOGLE AUTH: email={email} verified={email_verified} uid={decoded.get('uid')} at={now().isoformat()}"
        )

        user = User.objects.filter(email=email).first()
        created = False
        if user is None:
            created = True
            display_name = name or email.split('@')[0]
            user = User.objects.create_user(
                email=email,
                password=None,
                display_name=display_name,
                avatar_url=picture,
            )
        else:
            # Fill missing profile fields, but don't overwrite user-managed data.
            dirty = False
            if (not user.display_name) and name:
                user.display_name = name
                dirty = True
            if (not user.avatar_url) and picture:
                user.avatar_url = picture
                dirty = True
            if dirty:
                user.save(update_fields=['display_name', 'avatar_url'])

        payload = {**get_tokens(user), 'user': UserSerializer(user).data, 'created': created}
        return Response(payload, status=200)

    except Exception as e:
        print(f"❌ GOOGLE AUTH error: {e}")
        return Response({'detail': 'Invalid Google credentials.'}, status=401)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def save_fcm_token(request):
    token = request.data.get('fcm_token')
    if token:
        request.user.fcm_token = token
        request.user.save(update_fields=['fcm_token'])
    return Response({'detail': 'FCM token saved.'})


@api_view(['POST'])
@permission_classes([AllowAny])
def setup_admin(request):
    # if User.objects.filter(role='platform_admin').exists():
    #     return Response({'detail': 'Admin already exists.'}, status=400)
    data = request.data.copy()
    data['role'] = 'platform_admin'
    ser = RegisterSerializer(data=data)
    if ser.is_valid():
        user = ser.save()
        user.role = 'platform_admin'
        user.is_staff = True
        user.is_superuser = True
        user.save()
        return Response({'detail': 'Admin account created.'}, status=201)
    return Response(ser.errors, status=400)


# ── RESTAURANTS ───────────────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
def restaurants(request):
    if request.method == 'GET':
        permission_classes_list = [AllowAny]
        user = request.user

        # Admin sees ALL restaurants
        if user.is_authenticated and user.role == 'platform_admin':
            qs = Restaurant.objects.all()
        else:
            # Public / customers see only active
            qs = Restaurant.objects.filter(status='active')
        search = request.query_params.get('search')
        cuisine = request.query_params.get('cuisine')
        is_open = request.query_params.get('is_open')
        if search:
            qs = qs.filter(name__icontains=search)
        if cuisine:
            qs = qs.filter(cuisine_type__icontains=cuisine)
        if is_open is not None:
            qs = qs.filter(is_open=is_open.lower() == 'true')
        return Response(RestaurantSerializer(qs, many=True).data)

    if request.method == 'POST':
        if not (request.user.is_authenticated and request.user.role == 'platform_admin'):
            return Response({'detail': 'Forbidden.'}, status=403)

        if not request.data.get('manager_id'):
            return Response({'detail': 'manager_id is required'}, status=400)

        ser = RestaurantSerializer(data=request.data)
        if ser.is_valid():
            ser.save()
            return Response(ser.data, status=201)

        return Response(ser.errors, status=400)


@api_view(['GET', 'PATCH', 'DELETE'])
def restaurant_detail(request, pk):
    try:
        r = Restaurant.objects.get(pk=pk)
    except Restaurant.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)

    if request.method == 'GET':
        return Response(RestaurantDetailSerializer(r).data)

    if request.method == 'PATCH':
        is_admin = request.user.role == 'platform_admin'
        is_linked_manager = (request.user.role == 'restaurant_manager'
                             and r.manager == request.user)
        if not (is_admin or is_linked_manager):
            return Response({'detail': 'Forbidden.'}, status=403)
        ser = RestaurantSerializer(r, data=request.data, partial=True)
        if ser.is_valid():
            ser.save()
            return Response(ser.data)
        return Response(ser.errors, status=400)

    if request.method == 'DELETE':
        if request.user.role != 'platform_admin':
            return Response({'detail': 'Forbidden.'}, status=403)
        r.delete()
        return Response(status=204)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def suspend_restaurant(request, pk):
    if request.user.role != 'platform_admin':
        return Response({'detail': 'Forbidden.'}, status=403)
    try:
        r = Restaurant.objects.get(pk=pk)
        r.status = 'active' if r.status == 'suspended' else 'suspended'
        r.save(update_fields=['status'])
        return Response({'status': r.status})
    except Restaurant.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)


# ── MENU ──────────────────────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
def menu_items(request, restaurant_pk):
    try:
        r = Restaurant.objects.get(pk=restaurant_pk)
    except Restaurant.DoesNotExist:
        return Response({'detail': 'Restaurant not found.'}, status=404)

    if request.method == 'GET':
        items = r.menu_items.all()
        return Response(MenuItemSerializer(items, many=True).data)

    if not (request.user.is_authenticated and request.user.role == 'restaurant_manager'
            and r.manager == request.user):
        return Response({'detail': 'Forbidden.'}, status=403)

    ser = MenuItemSerializer(data={**request.data, 'restaurant_id': str(r.id)})
    if ser.is_valid():
        item = ser.save(restaurant=r)
        # Notify all customers
        tokens = list(User.objects.filter(
            role='customer', fcm_token__isnull=False
        ).exclude(fcm_token='').values_list('fcm_token', flat=True))
        send_multicast(
            tokens,
            f'{r.name}',
            f'{item.name} is now available! 🍽',
            data={
                'type': 'menu',
                'restaurant_id': str(r.id),
                'menu_item_id': str(item.id),
            },
        )
        return Response(MenuItemSerializer(item).data, status=201)
    return Response(ser.errors, status=400)


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def menu_item_detail(request, pk):
    try:
        item = MenuItem.objects.get(pk=pk)
    except MenuItem.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)

    if not (request.user.role == 'restaurant_manager'
            and item.restaurant.manager == request.user):
        return Response({'detail': 'Forbidden.'}, status=403)

    if request.method == 'PATCH':
        ser = MenuItemSerializer(item, data=request.data, partial=True)
        if ser.is_valid():
            updated = ser.save()
            # Public notify all customers on menu updates
            tokens = list(User.objects.filter(
                role='customer', fcm_token__isnull=False
            ).exclude(fcm_token='').values_list('fcm_token', flat=True))
            send_multicast(
                tokens,
                f'{updated.restaurant.name}',
                f'{updated.name} was updated ✨',
                data={
                    'type': 'menu',
                    'restaurant_id': str(updated.restaurant_id),
                    'menu_item_id': str(updated.id),
                    'event': 'updated',
                },
            )
            return Response(ser.data)
        return Response(ser.errors, status=400)

    item.delete()
    return Response(status=204)


# ── CATEGORIES ────────────────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def categories(request, restaurant_pk):
    try:
        r = Restaurant.objects.get(pk=restaurant_pk)
    except Restaurant.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)

    if request.method == 'GET':
        return Response(CategorySerializer(r.categories.all(), many=True).data
                        if hasattr(r, 'categories') else [])

    
    ser = CS(data=request.data)
    if ser.is_valid():
        ser.save(restaurant=r)
        return Response(ser.data, status=201)
    return Response(ser.errors, status=400)


# ── ORDERS ────────────────────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def orders(request):
    if request.method == 'GET':
        user = request.user
        if user.role == 'customer':
            qs = Order.objects.filter(customer=user)
        elif user.role == 'restaurant_manager':
            try:
                r = Restaurant.objects.get(manager=user)
                qs = Order.objects.filter(restaurant=r)
            except Restaurant.DoesNotExist:
                qs = Order.objects.none()
        elif user.role == 'platform_admin':
            qs = Order.objects.all()
        else:
            qs = Order.objects.none()
        return Response(OrderSerializer(qs, many=True).data)

    # POST — place order (customer only)
    if request.user.role != 'customer':
        return Response({'detail': 'Only customers can place orders.'}, status=403)

    ser = PlaceOrderSerializer(data=request.data)
    if not ser.is_valid():
        return Response(ser.errors, status=400)

    try:
        restaurant = Restaurant.objects.get(pk=ser.validated_data['restaurant_id'])
    except Restaurant.DoesNotExist:
        return Response({'detail': 'Restaurant not found.'}, status=404)

    if not restaurant.is_open:
        return Response({'detail': 'This restaurant is currently closed.'}, status=400)

    total = 0
    order_items_data = []
    for item_data in ser.validated_data['items']:
        try:
            menu_item = MenuItem.objects.get(pk=item_data['menu_item_id'], restaurant=restaurant)
            qty = int(item_data.get('quantity', 1))
            total += float(menu_item.price) * qty
            order_items_data.append((menu_item, qty))
        except MenuItem.DoesNotExist:
            return Response({'detail': f'Menu item not found.'}, status=404)

    order = Order.objects.create(
        customer=request.user,
        customer_name=request.user.display_name,
        restaurant=restaurant,
        restaurant_name=restaurant.name,
        total_amount=total,
        notes=ser.validated_data.get('notes', ''),
    )

    for menu_item, qty in order_items_data:
        OrderItem.objects.create(
            order=order,
            menu_item=menu_item,
            name_snapshot=menu_item.name,
            price_snapshot=menu_item.price,
            image_url=menu_item.image_url,
            quantity=qty,
        )

    # Notify manager
    notify_new_order(order)

    # Save notification
    if restaurant.manager:
        Notification.objects.create(
            user=restaurant.manager,
            type='order_placed',
            title=f'New Order #{str(order.id)[:8].upper()}',
            body=f'From {request.user.display_name} • KSh {total:,.0f}',
        )

    return Response(OrderSerializer(order).data, status=201)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def order_detail(request, pk):
    try:
        order = Order.objects.get(pk=pk)
    except Order.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)

    user = request.user
    is_owner = order.customer == user
    is_manager = (user.role == 'restaurant_manager'
                  and order.restaurant.manager == user)
    if not (is_owner or is_manager or user.role == 'platform_admin'):
        return Response({'detail': 'Forbidden.'}, status=403)

    return Response(OrderSerializer(order).data)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def update_order_status(request, pk):
    try:
        order = Order.objects.get(pk=pk)
    except Order.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)

    if not (request.user.role == 'restaurant_manager'
            and order.restaurant.manager == request.user):
        return Response({'detail': 'Forbidden.'}, status=403)

    flow = ['pending', 'confirmed', 'preparing', 'ready', 'completed']
    new_status = request.data.get('status')
    if new_status not in [s for s in flow]:
        return Response({'detail': 'Invalid status.'}, status=400)

    order.status = new_status
    order.save(update_fields=['status', 'updated_at'])

    messages = {
        'confirmed': ('Order Confirmed ✅', 'Your order is confirmed — being prepared!'),
        'preparing': ('Being Prepared 👨‍🍳', f'Your order from {order.restaurant_name} is being prepared.'),
        'ready': ('Ready for Pickup! 🎉', f'Your order from {order.restaurant_name} is ready!'),
        'completed': ('Order Complete', 'Enjoy your meal! Don\'t forget to leave a review.'),
    }
    notify_order_update(order)
    if new_status in messages:
        title, body = messages[new_status]
        Notification.objects.create(
            user=order.customer,
            type=f'order_{new_status}',
            title=title,
            body=body,
        )

    return Response(OrderSerializer(order).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cancel_order(request, pk):
    try:
        order = Order.objects.get(pk=pk)
    except Order.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)

    is_customer = order.customer == request.user
    is_manager = (request.user.role == 'restaurant_manager'
                  and order.restaurant.manager == request.user)

    if not (is_customer or is_manager):
        return Response({'detail': 'Forbidden.'}, status=403)

    if order.status in ['completed', 'cancelled']:
        return Response({'detail': 'Cannot cancel this order.'}, status=400)

    order.status = 'cancelled'
    order.save(update_fields=['status', 'updated_at'])

    if is_manager:
        # Notify the customer with consistent payload data.
        notify_order_update(order)
        Notification.objects.create(
            user=order.customer,
            type='order_cancelled',
            title='Order Cancelled',
            body=f'Your order from {order.restaurant_name} was cancelled.',
        )

    return Response(OrderSerializer(order).data)


# ── REVIEWS ───────────────────────────────────────────────────────────────────
@api_view(['GET', 'POST'])
def reviews(request):
    if request.method == 'GET':
        restaurant_id = request.query_params.get('restaurant_id')
        qs = Review.objects.filter(restaurant_id=restaurant_id) if restaurant_id else Review.objects.none()
        return Response(ReviewSerializer(qs, many=True).data)

    if not (request.user.is_authenticated and request.user.role == 'customer'):
        return Response({'detail': 'Only customers can review.'}, status=403)

    restaurant_id = request.data.get('restaurant_id')
    if not restaurant_id:
        return Response({'detail': 'restaurant_id is required.'}, status=400)

    try:
        restaurant = Restaurant.objects.get(pk=restaurant_id)
    except Restaurant.DoesNotExist:
        return Response({'detail': 'Restaurant not found.'}, status=404)

    if Review.objects.filter(customer=request.user, restaurant=restaurant).exists():
        return Response({'detail': 'You have already reviewed this restaurant.'}, status=400)

    ser = ReviewSerializer(data=request.data)
    if ser.is_valid():
        review = ser.save(
            customer=request.user,
            customer_name=request.user.display_name,
            customer_avatar_url=request.user.avatar_url,
            restaurant=restaurant,
        )
        restaurant.update_rating()
        return Response(ReviewSerializer(review).data, status=201)
    return Response(ser.errors, status=400)


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def review_detail(request, pk):
    try:
        review = Review.objects.get(pk=pk)
    except Review.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)

    # Only the owning customer may edit/delete their review.
    if not (request.user.is_authenticated and request.user.role == 'customer' and review.customer == request.user):
        return Response({'detail': 'Forbidden.'}, status=403)

    if request.method == 'PATCH':
        ser = ReviewSerializer(review, data=request.data, partial=True)
        if ser.is_valid():
            ser.save()
            review.restaurant.update_rating()
            return Response(ReviewSerializer(review).data)
        return Response(ser.errors, status=400)

    # DELETE
    review.restaurant.update_rating()
    review.delete()
    return Response(status=204)


# ── CHAT ─────────────────────────────────────────────────────────────────────
@api_view(['GET', 'POST'])
def chat_messages(request):
    if request.method == 'GET':
        restaurant_id = request.query_params.get('restaurant_id')
        if not restaurant_id:
            return Response([], status=200)
        qs = ChatMessage.objects.filter(restaurant_id=restaurant_id).order_by('created_at')
        return Response(ChatMessageSerializer(qs, many=True).data)

    # POST
    if not (request.user.is_authenticated and request.user.role == 'customer'):
        return Response({'detail': 'Only customers can send messages.'}, status=403)

    restaurant_id = request.data.get('restaurant_id')
    message = (request.data.get('message') or '').strip()
    if not restaurant_id:
        return Response({'detail': 'restaurant_id is required.'}, status=400)
    if not message:
        return Response({'detail': 'message is required.'}, status=400)

    try:
        restaurant = Restaurant.objects.get(pk=restaurant_id)
    except Restaurant.DoesNotExist:
        return Response({'detail': 'Restaurant not found.'}, status=404)

    chat = ChatMessage.objects.create(
        restaurant=restaurant,
        customer=request.user,
        customer_name=request.user.display_name,
        message=message,
    )

    # Notify: restaurant manager + customers who previously interacted with this restaurant.
    # "Interacted" = placed an order OR left a review OR posted a chat message.
    interacted_customer_ids = set(
        Order.objects.filter(restaurant=restaurant).values_list('customer_id', flat=True)
    )
    interacted_customer_ids.update(
        Review.objects.filter(restaurant=restaurant).values_list('customer_id', flat=True)
    )
    interacted_customer_ids.update(
        ChatMessage.objects.filter(restaurant=restaurant).values_list('customer_id', flat=True)
    )
    interacted_customer_ids.discard(request.user.id)

    tokens = list(
        User.objects.filter(
            role='customer',
            id__in=list(interacted_customer_ids),
            fcm_token__isnull=False,
        )
        .exclude(fcm_token='')
        .values_list('fcm_token', flat=True)
    )

    title = f'{restaurant.name}'
    body = f'{request.user.display_name} commented on {restaurant.name}'
    send_multicast(
        tokens,
        title,
        body,
        data={
            'type': 'chat_message',
            'restaurant_id': str(restaurant.id),
            'chat_id': str(chat.id),
        },
    )

    manager = restaurant.manager
    if manager and manager.fcm_token:
        send_push(
            token=manager.fcm_token,
            title=f'{restaurant.name}',
            body=f'New comment about your restaurant',
            data={
                'type': 'chat_message',
                'restaurant_id': str(restaurant.id),
                'chat_id': str(chat.id),
                'for': 'manager',
            },
        )

    return Response(ChatMessageSerializer(chat).data, status=201)


# ── ADMIN ─────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_stats(request):
    if request.user.role != 'platform_admin':
        return Response({'detail': 'Forbidden.'}, status=403)
    return Response({
        'total_restaurants': Restaurant.objects.filter(status='active').count(),
        'total_users': User.objects.filter(role='customer').count(),
        'total_orders': Order.objects.count(),
        'total_managers': User.objects.filter(role='restaurant_manager').count(),
        'pending_orders': Order.objects.filter(status='pending').count(),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_all_orders(request):
    if request.user.role != 'platform_admin':
        return Response({'detail': 'Forbidden.'}, status=403)
    qs = Order.objects.all().order_by('-created_at')
    return Response(OrderSerializer(qs, many=True).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_users(request):
    if request.user.role != 'platform_admin':
        return Response({'detail': 'Forbidden.'}, status=403)
    qs = User.objects.all().order_by('-date_joined') if hasattr(User, 'date_joined') else User.objects.all()
    return Response(UserSerializer(qs, many=True).data)

@api_view(['POST'])
@permission_classes([IsAuthenticated])   # ← Must be logged in
def create_manager(request):
    # Only platform_admin can create restaurant managers
    if request.user.role != 'platform_admin':
        return Response(
            {'detail': 'Only platform administrators can create restaurant managers.'}, 
            status=status.HTTP_403_FORBIDDEN
        )

    # Rest of the logic
    data = request.data.copy()
    data['role'] = 'restaurant_manager'
    
    ser = RegisterSerializer(data=data)   # ← Important: use modified data
    if ser.is_valid():
        user = ser.save()
        
        # Force the role (in case serializer overrides it)
        user.role = 'restaurant_manager'
        user.save(update_fields=['role'])
        
        return Response({
            **get_tokens(user), 
            'user': UserSerializer(user).data
        }, status=status.HTTP_201_CREATED)
    
    return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
# @api_view(['POST'])
# @permission_classes([IsAuthenticated])
# def create_manager(request):
#     if request.user.role != 'platform_admin':
#         return Response({'detail': 'Forbidden.'}, status=403)
    # google_auth
#     email = request.data.get('email', '').strip()
#     display_name = request.data.get('display_name', '').strip()
    
#     if not email:
#         return Response({'detail': 'Email is required.'}, status=400)
    
#     if User.objects.filter(email=email).exists():
#         return Response({'detail': 'A user with this email already exists.'}, status=400)
    
#     temp_password = get_random_string(12)
    
#     try:
#         user = User.objects.create_user(
#             email=email,
#             password=temp_password,
#             display_name=display_name or email.split('@')[0],
#         )
#         user.role = 'restaurant_manager'
#         user.save(update_fields=['role'])
        
#         return Response({
#             'user': UserSerializer(user).data,
#             'temp_password': temp_password,
#         }, status=201)
#     except Exception as e:
#         return Response({'detail': str(e)}, status=400)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def unassigned_managers(request):
    if request.user.role != 'platform_admin':
        return Response({'detail': 'Forbidden.'}, status=403)
    managers = User.objects.filter(role='restaurant_manager', restaurants__isnull=True)
    return Response(UserSerializer(managers, many=True).data)


# ── DASHBOARD ─────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_stats(request):
    if request.user.role != 'restaurant_manager':
        return Response({'detail': 'Forbidden.'}, status=403)
    try:
        r = Restaurant.objects.get(manager=request.user)
    except Restaurant.DoesNotExist:
        return Response({'detail': 'No restaurant found.'}, status=404)

    from django.utils import timezone
    today = timezone.now().date()
    all_orders = Order.objects.filter(restaurant=r)

    return Response({
        'restaurant': RestaurantSerializer(r).data,
        'total_orders': all_orders.count(),
        'pending_orders': all_orders.filter(status='pending').count(),
        'today_orders': all_orders.filter(created_at__date=today).count(),
        'average_rating': r.average_rating,
        'total_reviews': r.total_reviews,
        'is_open': r.is_open,
    })


@api_view(['GET'])
@permission_classes([AllowAny])
def app_version(request):
    return Response({'version': '2.0.0', 'force_update': False})


# ── NOTIFICATIONS ─────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def notifications_list(request):
    notifs = Notification.objects.filter(user=request.user)
    return Response(NotificationSerializer(notifs, many=True).data)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def mark_notification_read(request, pk):
    try:
        n = Notification.objects.get(pk=pk, user=request.user)
        n.is_read = True
        n.save()
        return Response(NotificationSerializer(n).data)
    except Notification.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_all_read(request):
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return Response({'detail': 'All marked as read.'})