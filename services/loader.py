# services/loader.py
import io
import pandas as pd

REQUIRED_COLS = ["ID", "Label"]

def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    cols = [str(c).strip() for c in df.columns]
    # Toleranz für Groß-/Kleinschreibung
    map_norm = {}
    for c in cols:
        c_low = c.lower()
        if c_low in ("id", "nummer", "no"):
            map_norm[c] = "ID"
        elif c_low in ("label", "name", "titel", "title"):
            map_norm[c] = "Label"
        else:
            map_norm[c] = c  # Modellspalten bleiben
    df = df.rename(columns=map_norm)
    return df

def load_table(file_bytes: bytes, filename: str) -> tuple[dict, dict]:
    name = (filename or "").lower()
    if name.endswith(".csv"):
        # Trennzeichen heuristisch (Komma/Semikolon)
        try:
            df = pd.read_csv(io.BytesIO(file_bytes))
        except Exception:
            df = pd.read_csv(io.BytesIO(file_bytes), sep=";")
    else:
        df = pd.read_excel(io.BytesIO(file_bytes))  # braucht openpyxl

    df = _normalize_columns(df)

    # Pflichtspalten prüfen
    for c in REQUIRED_COLS:
        if c not in df.columns:
            raise ValueError(f"Spalte '{c}' fehlt im Upload.")

    # Model-Spalten = alles ab Index 2
    model_cols = [c for c in df.columns if c not in ("ID", "Label")]
    if not model_cols:
        raise ValueError("Keine Modellspalten gefunden (erwartet ab 3. Spalte).")

    # Strings sauber
    df["ID"] = df["ID"].astype(str).str.strip()
    df["Label"] = df["Label"].astype(str).str.strip()

    # Meta vorbereiten (Parent-Map aus ID ableiten: '1.2.3' -> '1.2')
    parent_map = {}
    for _id in df["ID"]:
        if "." in _id:
            parent_map[_id] = _id.rsplit(".", 1)[0]
        else:
            parent_map[_id] = ""  # Top-Level

    # Label-Map & Full-Path (für Suche)
    label_map = dict(zip(df["ID"], df["Label"]))
    # children map (IDs)
    children_map = {}
    for _id, parent in parent_map.items():
        children_map.setdefault(parent, []).append(_id)

    meta = {
        "model_cols": model_cols,
        "parent_map": parent_map,
        "label_map": label_map,
        "children_map": children_map
    }

    return {"main": df}, meta
