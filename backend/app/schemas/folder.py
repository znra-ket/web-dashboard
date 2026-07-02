from pydantic import AliasChoices, BaseModel, Field


class FolderCreate(BaseModel):
    name: str


class FolderNodeCreate(BaseModel):
    folder_id: int
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


class NodeScriptCreate(BaseModel):
    node_id: int
    script_id: int
    folder_id: int | None = None
    trigger_id: int | None = None
