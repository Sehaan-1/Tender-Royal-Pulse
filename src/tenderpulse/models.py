from pydantic import BaseModel


class ExampleModel(BaseModel):
    name: str
    value: int
