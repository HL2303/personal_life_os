from typing import Annotated

from pydantic import BaseModel, Field, field_validator


class Credentials(BaseModel):
    username: Annotated[str, Field(min_length=3, max_length=64)]
    password: Annotated[str, Field(min_length=12, max_length=128)]

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        value = value.strip().casefold()
        if not value:
            raise ValueError("Username cannot be blank.")
        return value


class AuthStatus(BaseModel):
    setup_required: bool


class AuthSessionRead(BaseModel):
    username: str
    csrf_token: str
