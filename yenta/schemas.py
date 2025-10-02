from typing import Dict, Type
from pydantic import BaseModel

# Registry of validation schemas
SCHEMA_REGISTRY: Dict[str, Type[BaseModel]] = {}


class ExpectedTask(BaseModel):
    title: str
    priority: str
    estimated_time: int
    tags: list[str]


# Register schema
SCHEMA_REGISTRY["ExpectedTask"] = ExpectedTask
