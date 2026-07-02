from pydantic import AliasChoices, BaseModel, Field


class FolderCreate(BaseModel):
    name: str


class FolderUpdate(BaseModel):
    name: str


class FolderRead(BaseModel):
    id: int
    name: str
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class FolderNodeCreate(BaseModel):
    folder_id: int
    node_id: int


class FolderNodeRead(BaseModel):
    folder_id: int
    node_id: int

    model_config = {"from_attributes": True}


class FolderNodeAdd(BaseModel):
    node_id: int


class FolderScriptCreate(BaseModel):
    folder_id: int
    script_id: int
    template_trigger_id: int | None = Field(
        default=None,
        validation_alias=AliasChoices("template_trigger_id", "trigger_id"),
    )

    @property
    def trigger_id(self) -> int | None:
        return self.template_trigger_id


class FolderScriptRead(BaseModel):
    id: int
    folder_id: int
    script_id: int
    trigger_id: int | None

    model_config = {"from_attributes": True}


class FolderScriptAdd(BaseModel):
    script_id: int
    template_trigger_id: int | None = Field(
        default=None,
        validation_alias=AliasChoices("template_trigger_id", "trigger_id"),
    )

    @property
    def trigger_id(self) -> int | None:
        return self.template_trigger_id


class NodeScriptCreate(BaseModel):
    node_id: int
    script_id: int
    folder_id: int | None = None
    trigger_id: int | None = None
