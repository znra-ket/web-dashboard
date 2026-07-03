from pydantic import BaseModel, Field

from app.models.pipeline import PipelineStepArgSourceType


class PipelineCreate(BaseModel):
    name: str


class PipelineUpdate(BaseModel):
    name: str


class PipelineRead(BaseModel):
    id: int
    name: str
    archived: bool
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class PipelineStepCreate(BaseModel):
    position: int = Field(ge=1)
    node_id: int
    script_id: int


class PipelineStepUpdate(BaseModel):
    position: int = Field(ge=1)
    node_id: int
    script_id: int


class PipelineStepRead(BaseModel):
    id: int
    pipeline_id: int
    position: int
    node_id: int
    script_id: int

    model_config = {"from_attributes": True}


class PipelineStepArgCreate(BaseModel):
    arg_index: int = Field(ge=0)
    source_type: PipelineStepArgSourceType
    literal_value: str | None = None
    source_step_id: int | None = None
    json_field: str | None = None


class PipelineStepArgUpdate(BaseModel):
    arg_index: int = Field(ge=0)
    source_type: PipelineStepArgSourceType
    literal_value: str | None = None
    source_step_id: int | None = None
    json_field: str | None = None


class PipelineStepArgRead(BaseModel):
    id: int
    step_id: int
    arg_index: int
    source_type: str
    literal_value: str | None
    source_step_id: int | None
    json_field: str | None

    model_config = {"from_attributes": True}
