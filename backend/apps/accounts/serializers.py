from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name", "is_staff", "date_joined"]
        read_only_fields = ["id", "username", "is_staff", "date_joined"]


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    class Meta:
        model = User
        fields = ["id", "username", "email", "password"]
        extra_kwargs = {"email": {"required": True}}

    def validate_email(self, value: str) -> str:
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this e-mail already exists.")
        return value.lower()

    def validate(self, attrs):
        # Run Django's password validators with the user attributes so that
        # UserAttributeSimilarityValidator can reject "password == username".
        validate_password(
            attrs["password"], user=User(username=attrs["username"], email=attrs["email"])
        )
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)
