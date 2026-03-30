import uuid
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError('Email is required')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault('role', 'platform_admin')
        extra.setdefault('is_staff', True)
        extra.setdefault('is_superuser', True)
        return self.create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    ROLES = [
        ('platform_admin', 'Platform Admin'),
        ('restaurant_manager', 'Restaurant Manager'),
        ('customer', 'Customer'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=100)
    role = models.CharField(max_length=30, choices=ROLES, default='customer')
    phone = models.CharField(max_length=20, blank=True, null=True)
    avatar_url = models.TextField(blank=True, null=True)
    fcm_token = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['display_name']
    objects = UserManager()

    def __str__(self):
        return f'{self.email} ({self.role})'


class Restaurant(models.Model):
    STATUS = [('active', 'Active'), ('suspended', 'Suspended'), ('pending', 'Pending')]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    manager = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='restaurants')
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    address = models.CharField(max_length=300)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True, null=True)
    cover_url = models.TextField(blank=True, null=True)
    logo_url = models.TextField(blank=True, null=True)
    cuisine_type = models.CharField(max_length=100, blank=True, null=True)
    opening_hours = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default='active')
    is_open = models.BooleanField(default=True)
    average_rating = models.FloatField(default=0.0)
    total_reviews = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    def update_rating(self):
        reviews = self.reviews.all()
        self.total_reviews = reviews.count()
        self.average_rating = reviews.aggregate(
            models.Avg('rating')
        )['rating__avg'] or 0.0
        self.save(update_fields=['average_rating', 'total_reviews'])


class Category(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='categories')
    name = models.CharField(max_length=100)
    display_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['display_order', 'name']

    def __str__(self):
        return f'{self.restaurant.name} — {self.name}'


class MenuItem(models.Model):
    AVAILABILITY = [('available', 'Available'), ('later', 'Later'), ('unavailable', 'Unavailable')]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='menu_items')
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='items')
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    image_url = models.TextField(blank=True, null=True)
    availability = models.CharField(max_length=20, choices=AVAILABILITY, default='available')
    is_featured = models.BooleanField(default=False)
    prep_time_minutes = models.IntegerField(default=15)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.restaurant.name} — {self.name}'


class Order(models.Model):
    STATUS = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('preparing', 'Preparing'),
        ('ready', 'Ready'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='orders')
    customer_name = models.CharField(max_length=100)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='orders')
    restaurant_name = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=STATUS, default='pending')
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Order #{str(self.id)[:8]} — {self.restaurant_name}'


class OrderItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    menu_item = models.ForeignKey(MenuItem, on_delete=models.SET_NULL, null=True)
    name_snapshot = models.CharField(max_length=200)
    price_snapshot = models.DecimalField(max_digits=10, decimal_places=2)
    image_url = models.TextField(blank=True, null=True)
    quantity = models.IntegerField(default=1)

    def __str__(self):
        return f'{self.quantity}x {self.name_snapshot}'


class Review(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reviews')
    customer_name = models.CharField(max_length=100)
    customer_avatar_url = models.TextField(blank=True, null=True)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='reviews')
    rating = models.IntegerField(default=5)
    comment = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['customer', 'restaurant']]
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.customer_name} → {self.restaurant.name} ({self.rating}★)'


class Notification(models.Model):
    TYPES = [
        ('order_placed', 'Order Placed'),
        ('order_confirmed', 'Order Confirmed'),
        ('order_preparing', 'Order Preparing'),
        ('order_ready', 'Order Ready'),
        ('order_cancelled', 'Order Cancelled'),
        ('new_menu_item', 'New Menu Item'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    type = models.CharField(max_length=30, choices=TYPES)
    title = models.CharField(max_length=200)
    body = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']