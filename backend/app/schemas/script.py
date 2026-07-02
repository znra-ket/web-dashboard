from pydantic import BaseModel


class ScriptCreate(BaseModel):
    name: str
    content: str


class ScriptUpdateContent(BaseModel):
    content: str
