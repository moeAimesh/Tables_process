# services/search.py
from typing import List, Dict, Any
import re
import pandas as pd

def _full_path_for_id(_id: str, parent_map: dict, label_map: dict) -> list[str]:
    parts = []
    cur = _id
    seen = set()
    while cur is not None and cur in label_map and cur not in seen:
        seen.add(cur)
        parts.append(label_map.get(cur, cur))
        cur = parent_map.get(cur, None)
        if cur == "":
            break
    parts.reverse()
    return parts

def search_paths(
    df: pd.DataFrame,
    meta: dict,
    query: str,
    limit: int = 20
) -> List[Dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []
    rx = re.compile(re.escape(q), flags=re.I)

    parent_map: dict = meta["parent_map"]
    label_map: dict = meta["label_map"]
    model_cols: list[str] = meta["model_cols"]

    # Suche nur in Label-Spalte
    hits = df[df["Label"].fillna("").str.contains(rx)].copy()

    out = []
    for _id, row in hits.head(limit).set_index("ID").iterrows():
        parts = _full_path_for_id(_id, parent_map, label_map)
        # Für JEDES Modell zurückgeben (so kannst du im Frontend filtern)
        for m in model_cols:
            out.append({
                "model": m,
                "path": " / ".join(parts) if parts else "(root)",
                "path_parts": parts
            })
    return out
