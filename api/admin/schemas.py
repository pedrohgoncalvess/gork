from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Login(Input):
    # Password whitespace is significant.
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=512)


class PairingCode(Input):
    phone_number: str = Field(pattern=r"^\+?[1-9]\d{6,14}$")


class UserInput(Input):
    name: str = Field(min_length=1, max_length=255)
    phone_number: str | None = Field(default=None, pattern=r"^\+?[1-9]\d{6,14}$")
    lid: str | None = Field(default=None, pattern=r"^\d{1,25}(?:@lid)?$")

    @model_validator(mode="after")
    def needs_identity(self):
        if not self.phone_number and not self.lid:
            raise ValueError("Informe um telefone ou LID.")
        return self


class GroupInput(Input):
    name: str = Field(min_length=1, max_length=255)
    group_jid: str = Field(pattern=r"^\d+(?:-\d+)?(?:@g\.us)?$", max_length=100)


class WhitelistInput(Input):
    allowed: bool
    is_admin: bool = False


class GroupSettings(Input):
    auto_message: bool


class BlacklistInput(Input):
    user_id: int = Field(gt=0)
    features: list[str] = Field(default_factory=list, max_length=50)


class AgentInput(Input):
    model_id: int | None = Field(default=None, gt=0)
    prompt: str | None = Field(default=None, min_length=1, max_length=100000)

    @model_validator(mode="after")
    def has_change(self):
        if self.model_id is None and self.prompt is None:
            raise ValueError("Informe um modelo ou instruções.")
        return self


class ModelInput(Input):
    name: str = Field(min_length=1, max_length=255)
    openrouter_id: str = Field(min_length=3, max_length=255, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]+$")


class OverrideInput(Input):
    agent_id: int = Field(gt=0)
    model_id: int = Field(gt=0)
    user_id: int | None = Field(default=None, gt=0)
    group_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def one_scope(self):
        if (self.user_id is None) == (self.group_id is None):
            raise ValueError("Escolha um usuário ou um grupo.")
        return self


class CommandInput(Input):
    command: str = Field(min_length=1, max_length=50)
    user_id: int | None = Field(default=None, gt=0)
    group_id: int | None = Field(default=None, gt=0)
    message: str = Field(default="Este comando está temporariamente desativado.", min_length=1, max_length=1000)
    disabled_until: datetime | None = None

    @model_validator(mode="after")
    def future_expiry(self):
        if self.disabled_until is not None:
            if self.disabled_until.tzinfo is None or self.disabled_until <= datetime.now(timezone.utc):
                raise ValueError("Use uma data futura com fuso horário.")
        return self
