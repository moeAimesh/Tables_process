from pydantic import BaseModel
from typing import List, Optional

class UploadResponse(BaseModel):
    dataset_id: str
    models: List[str]

class TreemapRequest(BaseModel):
    dataset_id: str
    model: str
    path_parts: List[str] | None = None

class TreemapResponse(BaseModel):
    labels: List[str]
    parents: List[str]
    values: List[float]
    ids: List[str]

class SearchRequest(BaseModel):
    dataset_id: str
    query: str
    limit: int = 20
    model: Optional[str] = None  # optionaler Modellfilter

class SearchHit(BaseModel):
    model: str
    path: str
    path_parts: List[str]

class CompareRequest(BaseModel):
    dataset_id: str
    model_a: str
    model_b: str
    section: str | None = None
