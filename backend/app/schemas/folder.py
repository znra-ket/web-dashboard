from pydantic import BaseModel


class FolderCreate(BaseModel):
    name: str


class FolderNodeCreate(BaseModel):
    folder_id: int
    node_id: int


class FolderScriptCreate(BaseModel):
    folder_id: int
    script_id: int
    trigger_id: int | None = None


class NodeScriptCreate(BaseModel):
    node_id: int
    script_id: int
    folder_id: int | None = None
    trigger_id: int | None = None
