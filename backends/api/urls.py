from django.urls import path
from . import views

urlpatterns = [
    # Auth
    path('auth/register/', views.register),
    path('auth/google/', views.google_auth),
    path('auth/profile/', views.profile),
    path('auth/password-change/', views.change_password),
    path('auth/password-reset/', views.password_reset_request),
    path('auth/fcm-token/', views.save_fcm_token),
    path('auth/setup/admin/', views.setup_admin),

    # JWT
    path('auth/token/', __import__('api.serializers_jwt', fromlist=['EmailTokenObtainPairView']).EmailTokenObtainPairView.as_view()),
    # path('auth/token/', __import__('rest_framework_simplejwt.views', fromlist=['TokenObtainPairView']).TokenObtainPairView.as_view()),
    path('auth/token/refresh/', __import__('rest_framework_simplejwt.views', fromlist=['TokenRefreshView']).TokenRefreshView.as_view()),
    path('auth/logout/', __import__('rest_framework_simplejwt.views', fromlist=['TokenBlacklistView']).TokenBlacklistView.as_view()),

    # Restaurants
    path('restaurants/', views.restaurants),
    path('restaurants/<uuid:pk>/', views.restaurant_detail),
    path('restaurants/<uuid:pk>/suspend/', views.suspend_restaurant),
    path('restaurants/<uuid:restaurant_pk>/menu/', views.menu_items),
    path('restaurants/<uuid:restaurant_pk>/categories/', views.categories),

    # Menu items
    path('menu-items/<uuid:pk>/', views.menu_item_detail),

    # Orders
    path('orders/', views.orders),
    path('orders/<uuid:pk>/', views.order_detail),
    path('orders/<uuid:pk>/status/', views.update_order_status),
    path('orders/<uuid:pk>/cancel/', views.cancel_order),

    # Reviews
    path('reviews/', views.reviews),
    path('reviews/<uuid:pk>/', views.review_detail),

    # Chat
    path('chat/messages/', views.chat_messages),

    # Admin
    path('admin/stats/', views.admin_stats),
    path('admin/all-orders/', views.admin_all_orders),
    path('admin/users/', views.admin_users),
    path('admin/create-manager/', views.create_manager),
    path('admin/unassigned-managers/', views.unassigned_managers),

    # Dashboard
    path('dashboard/stats/', views.dashboard_stats),
    path('version/', views.app_version),

    # Notifications
    path('notifications/', views.notifications_list),
    path('notifications/<uuid:pk>/read/', views.mark_notification_read),
    path('notifications/mark-all-read/', views.mark_all_read),
]