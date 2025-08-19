# services/builder.py
from typing import List, Dict, Any
import math
import pandas as pd

def list_models(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in ("ID", "Label")]

def _collect_subtree_ids(root_id: str, children_map: dict) -> list[str]:
    out = []
    stack = [root_id]
    while stack:
        cur = stack.pop()
        out.append(cur)
        for ch in children_map.get(cur, []):
            stack.append(ch)
    return out

def _find_root_ids(parent_map: dict) -> list[str]:
    return [i for i, p in parent_map.items() if p == ""]

def build_treemap_for_model(
    df: pd.DataFrame,
    meta: dict,
    model: str,
    path_parts: List[str] | None = None
) -> Dict[str, List[Any]]:
    if model not in df.columns:
        raise ValueError(f"Modell '{model}' nicht gefunden.")

    parent_map: dict = meta["parent_map"]
    label_map: dict = meta["label_map"]
    children_map: dict = meta["children_map"]

    # --- Pfadanker finden (optional) ---
    def _dfs_label(cur_id: str, parts: List[str]) -> str | None:
        if not parts:
            return cur_id
        want0, rest = parts[0], parts[1:]
        for ch in children_map.get(cur_id, []):
            if label_map.get(ch, "") == want0:
                r = _dfs_label(ch, rest)
                if r:
                    return r
        return None

    anchor_id = None
    if path_parts:
        # künstliche Root = "" -> Top-Level IDs
        for top in children_map.get("", []):
            if label_map.get(top, "") == path_parts[0]:
                anchor_id = _dfs_label(top, path_parts[1:])
                if anchor_id:
                    break

    # --- IDs im Scope bestimmen ---
    if anchor_id:
        ids = _collect_subtree_ids(anchor_id, children_map)
    else:
        ids = list(df["ID"].astype(str).values)

    id_set = set(ids)

    # --- Basiswerte je ID aus der Modellspalte ---
    s = df.set_index("ID")[model]

    def base_value(val) -> float:
        # numeric -> float; NaN -> 0; strings: non-empty -> 1 (Präsenz), sonst 0
        try:
            v = float(val)
            if math.isnan(v):
                return 0.0
            return v
        except Exception:
            if val is None:
                return 0.0
            txt = str(val).strip()
            if txt == "" or txt.lower() == "nan":
                return 0.0
            return 1.0

    base = {i: base_value(s.get(i)) for i in ids}

    # --- Children-Map auf Scope filtern + Tiefe ---
    children_scoped = {i: [c for c in children_map.get(i, []) if c in id_set] for i in ids}

    def depth(i: str) -> int:
        return 1 + (i.count(".") if isinstance(i, str) else 0)

    # --- Bottom-Up Roll-Up: Eltern = Summe der Kinder (falls vorhanden), sonst Basiswert ---
    totals: Dict[str, float] = {}
    for i in sorted(ids, key=depth, reverse=True):  # tiefste zuerst
        kids = children_scoped.get(i, [])
        if kids:
            ssum = sum(totals.get(k, 0.0) for k in kids)
            if ssum == 0.0:
                # Wenn Kinder 0 sind, nimm wenigstens den Basiswert (falls vorhanden)
                totals[i] = base.get(i, 0.0)
            else:
                totals[i] = ssum
        else:
            totals[i] = base.get(i, 0.0)

    # --- Root & Top-Level bestimmen ---
    root = f"{model}__root"
    top_ids = [i for i in ids if parent_map.get(i, "") not in id_set]
    root_value = sum(totals.get(i, 0.0) for i in top_ids)

    # Fallback: wenn alles 0, nutze "count" (alle Blätter = 1)
    if root_value == 0.0:
        leaves = [i for i in ids if not children_scoped.get(i)]
        for i in leaves:
            totals[i] = 1.0
        for i in sorted(ids, key=depth, reverse=True):
            kids = children_scoped.get(i, [])
            if kids:
                totals[i] = sum(totals.get(k, 0.0) for k in kids)
        root_value = sum(totals.get(i, 0.0) for i in top_ids)

    # --- Arrays für Plotly ---
    labels, parents, values, ids_arr = [], [], [], []
    labels.append(model); parents.append(""); values.append(root_value); ids_arr.append(root)

    for _id in ids:
        lab = label_map.get(_id, _id)
        par = parent_map.get(_id, "")
        par_plot = par if par in id_set else root  # fehlende Eltern an Root hängen
        labels.append(lab)
        parents.append(par_plot)
        values.append(float(totals.get(_id, 0.0)))
        ids_arr.append(_id)

    return {"labels": labels, "parents": parents, "values": values, "ids": ids_arr}
