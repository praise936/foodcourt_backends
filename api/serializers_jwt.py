from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from django.contrib.auth import get_user_model

from django.contrib.auth import get_user_model, authenticate

User = get_user_model()

class EmailTokenObtainPairSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs.get('email', '').strip().lower()
        password = attrs.get('password', '')

        user = authenticate(
            request=self.context.get('request'),
            email=email,
            password=password
        )

        if user is None:
            raise serializers.ValidationError(
                {'detail': 'No active account found with the given credentials'}
            )

        if not user.is_active:
            raise serializers.ValidationError(
                {'detail': 'This account is disabled.'}
            )

        refresh = RefreshToken.for_user(user)

        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        }


class EmailTokenObtainPairView(TokenObtainPairView):
    serializer_class = EmailTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        from rest_framework.response import Response
        from rest_framework import status as drf_status
        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except Exception:
            return Response(
                {'detail': 'No active account found with the given credentials'},
                status=drf_status.HTTP_401_UNAUTHORIZED,
            )
        return Response(serializer.validated_data, status=drf_status.HTTP_200_OK)