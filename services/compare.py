# services/compare.py
from .builder import build_treemap_for_model
import pandas as pd

def compare_two_models(
    df: pd.DataFrame,
    meta: dict,
    model_a: str,
    model_b: str,
    section: str | None = None
):
    parts = [section] if section else None
    a = build_treemap_for_model(df, meta, model_a, parts)
    b = build_treemap_for_model(df, meta, model_b, parts)
    return {"a": a, "b": b}
