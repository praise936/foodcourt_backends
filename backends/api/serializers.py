from rest_framework import serializers
from .models import User, Restaurant, Category, MenuItem, Order, OrderItem, Review, Notification, ChatMessage


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'email', 'display_name', 'role', 'phone', 'avatar_url', 'fcm_token', 'created_at']
        read_only_fields = ['id', 'role', 'created_at']


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ['email', 'password', 'display_name', 'phone']

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError('An account with this email already exists.')
        return value

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'display_order']


class MenuItemSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)

    class Meta:
        model = MenuItem
        fields = ['id', 'restaurant_id', 'category_id', 'category_name', 'name',
                  'description', 'price', 'image_url', 'availability',
                  'is_featured', 'prep_time_minutes', 'created_at']
        read_only_fields = ['id', 'created_at']


class RestaurantSerializer(serializers.ModelSerializer):
    manager_id = serializers.UUIDField(write_only=True)

    class Meta:
        model = Restaurant
        fields = [
            'id', 'manager_id', 'name', 'description', 'address', 'phone',
            'email', 'cover_url', 'logo_url', 'cuisine_type', 'opening_hours',
            'status', 'is_open', 'average_rating', 'total_reviews', 'created_at'
        ]
        read_only_fields = ['id', 'average_rating', 'total_reviews', 'created_at']

    def create(self, validated_data):
        manager_id = validated_data.pop('manager_id')
        
        try:
            manager = User.objects.get(id=manager_id, role='restaurant_manager')
        except User.DoesNotExist:
            raise serializers.ValidationError({
                'manager_id': 'No restaurant manager found with this ID. '
                            'Make sure the manager account was created correctly.'
            })
        
        return Restaurant.objects.create(manager=manager, **validated_data)

class RestaurantDetailSerializer(RestaurantSerializer):
    categories = CategorySerializer(many=True, read_only=True)
    menu_items = MenuItemSerializer(many=True, read_only=True)

    class Meta(RestaurantSerializer.Meta):
        fields = RestaurantSerializer.Meta.fields + ['categories', 'menu_items']


class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = ['id', 'order_id', 'menu_item_id', 'name_snapshot',
                  'price_snapshot', 'image_url', 'quantity']


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = ['id', 'customer_id', 'customer_name', 'restaurant_id',
                  'restaurant_name', 'status', 'items', 'total_amount',
                  'notes', 'created_at', 'updated_at']
        read_only_fields = ['id', 'customer_id', 'customer_name', 'restaurant_name',
                            'status', 'created_at', 'updated_at']


class PlaceOrderSerializer(serializers.Serializer):
    restaurant_id = serializers.UUIDField()
    notes = serializers.CharField(required=False, allow_blank=True)
    items = serializers.ListField(child=serializers.DictField())

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError('Order must have at least one item.')
        return value


class ReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ['id', 'customer_id', 'customer_name', 'customer_avatar_url',
                  'restaurant_id', 'rating', 'comment', 'created_at']
        read_only_fields = ['id', 'customer_id', 'customer_name',
                            'customer_avatar_url', 'created_at']

    def validate_rating(self, value):
        if not 1 <= value <= 5:
            raise serializers.ValidationError('Rating must be between 1 and 5.')
        return value


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['id', 'type', 'title', 'body', 'is_read', 'created_at']


class ChatMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = ['id', 'restaurant_id', 'customer_id', 'customer_name', 'message', 'created_at']
        read_only_fields = ['id', 'customer_id', 'customer_name', 'created_at']