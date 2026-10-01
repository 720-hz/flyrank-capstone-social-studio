from pydantic import BaseModel, Field


class IngestPostRequest(BaseModel):
    title: str
    source_kind: str = Field(pattern="^(markdown|url)$")
    source_text: str | None = None
    source_url: str | None = None


class GenerateVariantsRequest(BaseModel):
    platforms: list[str] | None = None  # None => app.config.DEFAULT_VARIANT_PLATFORMS


class EditVariantRequest(BaseModel):
    body_text: str
    hashtags: list[str] | None = None


class RejectVariantRequest(BaseModel):
    reason: str


class ApproveVariantRequest(BaseModel):
    edited_body_text: str | None = None


class CreateSlotRequest(BaseModel):
    label: str
    scheduled_at: str  # ISO 8601


class CreateAssignmentRequest(BaseModel):
    variant_id: int
    slot_id: int


class RunBatchRequest(BaseModel):
    limit: int = 50
