"""Price watches and the Telegram chat they are delivered to."""

from __future__ import annotations

import secrets
from datetime import timedelta

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

LINK_TOKEN_TTL = timedelta(minutes=30)


class TelegramLink(models.Model):
    """A site account connected to a Telegram chat with the bot.

    Linking never asks for a password in Telegram: the site issues a one-time
    token, the user opens ``t.me/<bot>?start=<token>``, and the bot binds the
    chat that sent it to the account that requested it.
    """

    class Language(models.TextChoices):
        UK = "uk", "Українська"
        EN = "en", "English"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="telegram"
    )
    chat_id = models.BigIntegerField(unique=True, null=True, blank=True)
    username = models.CharField(max_length=64, blank=True)
    language = models.CharField(max_length=2, choices=Language.choices, default=Language.UK)
    enabled = models.BooleanField(default=True, help_text="Send price alerts.")
    quiet_hours = models.BooleanField(
        default=True, help_text="Hold alerts between 22:00 and 08:00 (Kyiv time)."
    )
    link_token = models.CharField(max_length=64, unique=True, null=True, blank=True)
    token_created_at = models.DateTimeField(null=True, blank=True)
    linked_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.user} → {self.username or self.chat_id or 'not linked'}"

    @property
    def linked(self) -> bool:
        return self.chat_id is not None

    def issue_token(self) -> str:
        self.link_token = secrets.token_urlsafe(24)  # 32 chars of [A-Za-z0-9_-]
        self.token_created_at = timezone.now()
        self.save(update_fields=["link_token", "token_created_at"])
        return self.link_token

    def token_valid(self) -> bool:
        return bool(
            self.link_token
            and self.token_created_at
            and timezone.now() - self.token_created_at <= LINK_TOKEN_TTL
        )


class Watch(models.Model):
    """A request to be told when the price of a part or a build changes."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="watches"
    )
    component = models.ForeignKey(
        "catalog.Component", on_delete=models.CASCADE, null=True, blank=True, related_name="watches"
    )
    build = models.ForeignKey(
        "builds.Build", on_delete=models.CASCADE, null=True, blank=True, related_name="watches"
    )
    target_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="USD. Alert once the price reaches it (optional).",
    )  # fmt: skip
    threshold_percent = models.PositiveSmallIntegerField(
        default=5,
        validators=[MinValueValidator(1), MaxValueValidator(50)],
        help_text="Alert when the price moves this much, either way.",
    )
    baseline_price = models.DecimalField(
        max_digits=12, decimal_places=2,
        help_text="USD. Price when the watch was created or last alerted; changes count from it.",
    )  # fmt: skip
    last_notified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(component__isnull=False) & Q(build__isnull=True))
                | (Q(component__isnull=True) & Q(build__isnull=False)),
                name="watch_exactly_one_target",
            ),
            models.UniqueConstraint(
                fields=["user", "component"],
                condition=Q(component__isnull=False),
                name="watch_unique_component",
            ),
            models.UniqueConstraint(
                fields=["user", "build"],
                condition=Q(build__isnull=False),
                name="watch_unique_build",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} watches {self.component or self.build}"
