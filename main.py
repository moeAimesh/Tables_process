from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import traceback

# Services
from services.loader import load_table
from services.store import STORE
from services.builder import list_models, build_treemap_for_model  # treemap optional
from services.tree import (
    build_all_model_trees,  # baut pro Modell den geprunten Baum + Suchindex
    to_words,
    stripe_matches_for_model,
    phrase_matches_for_model,
)

app = FastAPI(title="Treemap API (ID/Label + Modelle als Spalten)")

# CORS (für lokalen Test/andere Hosts)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# Statische Dateien (HTML/JS/CSS)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ---------- Schemas ----------
class UploadOut(BaseModel):
    dataset_id: str
    models: List[str]

class TreemapIn(BaseModel):
    dataset_id: str
    model: str
    path_parts: Optional[List[str]] = None

class SearchIn(BaseModel):
    dataset_id: str
    query: str
    limit: int = 100
    model: Optional[str] = None  # optionaler Modellfilter


# ---------- Helpers ----------
def _collapse_to_ancestors_only(hits: List[dict]) -> List[dict]:
    """
    Entfernt 'tiefere' Treffer, wenn bereits ein Vorfahr desselben Modells enthalten ist.
    Beispiel: Behalte
      Root > 3 ... > 3.3 Applicable document
    und entferne
      Root > 3 ... > 3.3 Applicable document > hella ... > low beam ...
    """
    # sortiere nach Pfadlänge (kürzeste zuerst)
    hits_sorted = sorted(hits, key=lambda x: (x["model"], len(x.get("anchor_parts", []))))
    kept: List[dict] = []
    for h in hits_sorted:
        parts = h.get("anchor_parts", [])
        is_descendant = False
        for k in kept:
            if k["model"] != h["model"]:
                continue
            kp = k.get("anchor_parts", [])
            if len(parts) >= len(kp) and parts[:len(kp)] == kp:
                is_descendant = True
                break
        if not is_descendant:
            kept.append(h)
    # schöne Sortierung
    kept = sorted(kept, key=lambda x: (x["model"], x["path_label"]))
    return kept


# ---------- Routes ----------
@app.get("/", response_class=HTMLResponse)
def home():
    try:
        with open("static/index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse("<h3>static/index.html nicht gefunden</h3>", status_code=500)


@app.post("/upload")
async def upload(file: UploadFile = File(...)) -> UploadOut:
    """
    - Liest CSV/XLSX
    - Baut pro Modell den geprunten Baum & Suchindex (Stripe)
    - Speichert alles In-Memory
    - Gibt dataset_id + Modellnamen zurück
    """
    try:
        data = await file.read()
        frames, meta = load_table(data, file.filename)
        # Bäume + Index auf Basis des Upload-DFs bauen (PRUNING inklusive)
        trees, index = build_all_model_trees(frames["main"])
        ds_id = STORE.create(frames=frames, meta=meta, trees=trees, index=index)
        models = list_models(frames["main"])
        return UploadOut(dataset_id=ds_id, models=models)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=f"Upload/Parsing-Fehler: {type(e).__name__}: {e}")


@app.get("/tree")
def tree(dataset_id: str, model: str):
    """
    Gibt den **geprunten** Baum eines Modells zurück (als JSON-Objekt).
    Frontend zeichnet daraus die Treemap.
    """
    if not STORE.has(dataset_id):
        raise HTTPException(404, "dataset_id not found")
    bundle = STORE.get(dataset_id)
    t = bundle.trees.get(model)
    if not t:
        raise HTTPException(404, f"Model '{model}' not found")
    return t


@app.post("/search")
def search(req: SearchIn):
    """
    Stripe-Suche (>=2 Tokens) mit Fallback auf Phrase-Suche.
    - Optionaler Modellfilter: req.model ("" oder None = alle)
    - Dedupliziert: nur der 'Hauptpfad' (Vorfahren behalten, tiefere Varianten entfernen)
    Rückgabe: Liste von Treffern wie:
      { "model": "<Modell>", "path_label": "Root > ...", "anchor_parts": ["Root","..."] }
    """
    if not STORE.has(req.dataset_id):
        raise HTTPException(404, "dataset_id not found")
    idx = STORE.get(req.dataset_id).index
    if not idx:
        return []

    q_words = to_words(req.query or "")
    phrase = " ".join(q_words)

    # Modellfilter vorbereiten
    def iter_models():
        if req.model and req.model in idx:
            yield req.model, idx[req.model]
        elif req.model:
            # unbekanntes Modell -> keine Treffer
            return
        else:
            for m, data in idx.items():
                yield m, data

    results: List[dict] = []

    # 1) Stripe (PATH)
    if len(q_words) >= 2:
        for m, data in iter_models():
            sm = stripe_matches_for_model(data["paths"], data["npaths"], q_words)
            for h in sm:
                results.append({"model": m, **h})
        if results:
            results = _collapse_to_ancestors_only(results)
            return results[: max(1, req.limit)]

    # 2) Fallback: exakte Phrase (TERM)
    for m, data in iter_models():
        pm = phrase_matches_for_model(data["paths"], data["npaths"], phrase)
        for h in pm:
            results.append({"model": m, **h})

    results = _collapse_to_ancestors_only(results)
    return results[: max(1, req.limit)]


# (Optional) Falls irgendwo noch /treemap genutzt wird:
@app.post("/treemap")
def treemap(req: TreemapIn):
    """
    Liefert Plotly-kompatible Arrays (labels, parents, values, ids).
    Nutzt weiterhin DF + Meta; unabhängig von /tree.
    """
    if not STORE.has(req.dataset_id):
        raise HTTPException(404, "dataset_id not found")
    bundle = STORE.get(req.dataset_id)
    df = bundle.frames["main"]
    try:
        arr = build_treemap_for_model(df, bundle.meta, req.model, req.path_parts)
        return arr
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=f"Treemap-Fehler: {type(e).__name__}: {e}")
