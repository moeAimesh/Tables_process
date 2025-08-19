# services/trees.py
import math, re
import pandas as pd
from typing import Dict, List, Tuple, Any

# -------- Helpers (aus deinem alten Code nachempfunden) --------
def extract_number_and_label(label: str) -> Tuple[str|None, str]:
    label = str(label).strip()
    m = re.match(r"^(\d+(?:\.\d+)*)(.*)$", label)
    if m:
        return m.group(1), (m.group(2) or "").strip()
    return None, label

def _is_truthy(v) -> bool:
    if v is None: return False
    s = str(v).strip().lower()
    return s not in ("", "nan")

# -------- Baum ohne anytree, direkt als Dict --------
def build_tree_for_model(df: pd.DataFrame, model_col: str) -> Dict[str, Any]:
    """
    Erzeugt einen Baum wie dein tree_to_dict(): {name, children:[...]}
    - Nummer aus Label wird als Hierarchie genutzt (fallback: ID an last_number anhängen)
    - Wenn ein Modellwert existiert, wird ein Leaf-Kind mit name="- <wert>" hinzugefügt
    """
    root = {"name": "Root", "children": []}
    nodes: Dict[str, Dict[str, Any]] = {"": root}  # key = number path, "" = Root
    last_number: str | None = None

    def ensure_node(num: str, title: str):
        if num in nodes:  # Titel ggf. einmalig setzen
            return nodes[num]
        parts = num.split(".")
        parent_key = ".".join(parts[:-1])
        parent = nodes.get(parent_key, root)
        node = {"name": title, "children": []}
        parent["children"].append(node)
        nodes[num] = node
        return node

    for _, row in df.iterrows():
        label = row.get("Label", "")
        model_val = row.get(model_col, "")
        number, name = extract_number_and_label(label)

        if number:
            last_number = number
            full_title = f"{number} {name}".strip()
        else:
            if not last_number:
                continue
            raw_id = row.get("ID", "")
            id_str = re.sub(r"\.0$", "", str(raw_id))
            if id_str.lower() == "nan":
                continue
            number = f"{last_number}.{id_str}"
            full_title = str(label).strip()

        node = ensure_node(number, full_title)

        if _is_truthy(model_val):
            # wie früher: ein Leaf-Kind mit dem Wert als Text
            node["children"].append({"name": f"- {str(model_val).strip()}", "children": []})

    return root

def _prune_inplace(node: Dict[str, Any]) -> bool:
    """
    Entfernt unbrauchbare Knoten:
    - Behalte Blätter, deren name mit "-" beginnt (deine Werte)
    - Behalte Eltern nur, wenn nach dem Pruning noch Kinder existieren
    Rückgabe: True = Knoten behalten, False = entfernen
    """
    keep_children = []
    for ch in node.get("children", []):
        if _prune_inplace(ch):
            keep_children.append(ch)
    node["children"] = keep_children

    if not node["children"] and not str(node.get("name","")).startswith("-"):
        # Leerer, „normaler“ Knoten -> weg
        return False
    return True

def prune_tree(tree: Dict[str, Any]) -> Dict[str, Any]:
    # Root nie löschen, aber Kinder prunen
    _prune_inplace(tree)
    return tree

# -------- Paths + Normalisierung (für Stripe-Suche) --------
import unicodedata
def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c))

def normalize(s: str) -> str:
    s = _strip_accents(str(s))
    s = s.lower()
    s = s.replace(">", " ").replace("/", " ").replace("|", " ")
    s = s.replace("-", " ").replace("_", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def to_words(q: str) -> List[str]:
    return [w for w in normalize(q).split(" ") if w]

def collect_paths(tree: Dict[str, Any]) -> Tuple[List[List[str]], List[List[str]]]:
    """ paths = Originalnamen, npaths = normalisiert """
    paths: List[List[str]] = []
    def walk(node, acc):
        name = str(node.get("name","")).strip()
        parts = acc + [name] if name else acc
        paths.append(parts)
        for ch in (node.get("children") or []):
            walk(ch, parts)
    walk(tree, [])
    npaths = [[normalize(p) for p in parts] for parts in paths]
    return paths, npaths

# -------- Stripe- & Phrase-Suche (wie in deinem Flask-Code) --------
from itertools import combinations

def stripe_matches_for_model(paths, npaths, q_words: List[str]):
    n = len(q_words)
    if n < 2: return []
    seen = set(); hits = []

    for groups in range(2, n + 1):
        for split_tuple in combinations(range(1, n), groups - 1):
            idxs = (0,) + split_tuple + (n,)
            phrases = [" ".join(q_words[a:b]) for a,b in zip(idxs[:-1], idxs[1:])]

            for parts, nparts in zip(paths, npaths):
                if len(nparts) < groups: continue
                for i in range(0, len(nparts) - groups + 1):
                    ok = True
                    for g in range(groups):
                        if phrases[g] not in nparts[i + g]:
                            ok = False; break
                    if not ok: continue
                    anchor = tuple(parts[: i + groups])
                    if anchor in seen: continue
                    seen.add(anchor)
                    hits.append({"anchor_parts": list(anchor), "path_label": " > ".join(anchor)})
    # Sort
    hits.sort(key=lambda x: (len(x["anchor_parts"]), x["path_label"]))
    return hits

def phrase_matches_for_model(paths, npaths, phrase: str):
    seen = set(); out = []
    for parts, nparts in zip(paths, npaths):
        j = next((idx for idx, seg in enumerate(nparts) if phrase in seg), None)
        if j is None: continue
        anchor = tuple(parts[: j+1])
        if anchor in seen: continue
        seen.add(anchor)
        out.append({"anchor_parts": list(anchor), "path_label": " > ".join(anchor)})
    out.sort(key=lambda x: (len(x["anchor_parts"]), x["path_label"]))
    return out

def build_all_model_trees(df: pd.DataFrame) -> Tuple[Dict[str,Any], Dict[str,Any]]:
    """
    Erzeugt:
      trees[model] = pruned tree (dict)
      index[model] = {"paths": [...], "npaths": [...]}
    """
    model_cols = [c for c in df.columns if c not in ("ID","Label")]
    trees: Dict[str,Any] = {}
    index: Dict[str,Any] = {}
    for m in model_cols:
        t = build_tree_for_model(df, m)
        t = prune_tree(t)
        paths, npaths = collect_paths(t)
        trees[m] = t
        index[m] = {"paths": paths, "npaths": npaths}
    return trees, index
