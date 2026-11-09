"""Validated request models shared by API routers."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Action = Literal["allow", "warn", "block"]
MODALITIES = {"text", "image", "video"}
CATEGORIES = {"violence", "threat_language", "self_harm_indicators"}


class RegisterInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address.")
        return value


class LoginInput(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class GoogleCredentialInput(BaseModel):
    credential: str = Field(min_length=20, max_length=8192)
    csrf_token: str = Field(min_length=32, max_length=128)


class RuleInput(BaseModel):
    kind: Literal["website", "category"]
    target: str = Field(min_length=1, max_length=253)
    action: Action
    enabled: bool = True

    @field_validator("target")
    @classmethod
    def normalize_target(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_kind_target(self):
        if self.kind == "category" and self.target.lower() not in CATEGORIES:
            raise ValueError("Choose one of the available content categories.")
        if self.kind == "website":
            target = self.target.lower().removeprefix("*.").lstrip(".")
            if "://" in target or "/" in target or " " in target or not target:
                raise ValueError("Enter a domain such as example.com, without a URL path.")
            if len(target) > 253 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", target):
                raise ValueError("Enter a valid website domain.")
        return self


class SettingsInput(BaseModel):
    protection_enabled: bool
    modalities: dict[str, bool]
    category_actions: dict[str, Action]
    thresholds: dict[str, dict[str, float]]

    @model_validator(mode="after")
    def validate_settings(self):
        if set(self.modalities) != MODALITIES:
            raise ValueError("Settings must include text, image and video modalities.")
        if set(self.category_actions) != CATEGORIES:
            raise ValueError("Settings must include all candidate category actions.")
        if set(self.thresholds) != CATEGORIES:
            raise ValueError("Settings must include thresholds for all candidate categories.")
        for category, values in self.thresholds.items():
            if set(values) != {"review", "block"}:
                raise ValueError(f"{category} thresholds require review and block values.")
            if not all(0.0 <= score <= 1.0 for score in values.values()):
                raise ValueError("Thresholds must be between 0 and 1.")
            if values["review"] > values["block"]:
                raise ValueError("Review threshold cannot exceed the block threshold.")
        return self


class ThresholdValuesPatch(BaseModel):
    review: float | None = Field(default=None, ge=0.0, le=1.0)
    block: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def require_at_least_one_value(self):
        provided = self.model_fields_set
        if not provided or any(getattr(self, key) is None for key in provided):
            raise ValueError("Provide a valid review or block threshold.")
        return self


class SettingsPatchInput(BaseModel):
    protection_enabled: bool | None = None
    modalities: dict[str, bool] | None = None
    category_actions: dict[str, Action] | None = None
    thresholds: dict[str, ThresholdValuesPatch] | None = None

    @model_validator(mode="after")
    def validate_patch(self):
        if not self.model_fields_set or any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("Provide at least one protection setting to update.")
        if self.modalities is not None and (not self.modalities or not set(self.modalities) <= MODALITIES):
            raise ValueError("Only text, image and video modality settings can be updated.")
        if self.category_actions is not None and (
            not self.category_actions or not set(self.category_actions) <= CATEGORIES
        ):
            raise ValueError("Only available candidate category actions can be updated.")
        if self.thresholds is not None and (
            not self.thresholds or not set(self.thresholds) <= CATEGORIES
        ):
            raise ValueError("Only available candidate category thresholds can be updated.")
        return self


class TextInput(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)
    source_url: str | None = Field(default=None, max_length=2048)

