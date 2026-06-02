from app.schemas.common import ApiModel


class LoginRequest(ApiModel):
    email: str
    password: str


class TokenResponse(ApiModel):
    access_token: str
    token_type: str = "bearer"


class CurrentUserRead(ApiModel):
    id: int
    name: str
    email: str
    permissions: list[str]
    authorized_units: list[str]
