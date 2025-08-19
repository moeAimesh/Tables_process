let dataset_id = null;

const $ = (s) => document.querySelector(s);
const statusEl = $('#status');
const modelSel = $('#model');
const resultsDD = $('#resultsDropdown');

function norm(s){ return (s||"").toString().trim().toLowerCase().replace(/\s+/g,' '); }

$('#btnUpload').onclick = async () => {
  const f = $('#file').files[0];
  if (!f) return alert('Bitte Datei wählen');
  const fd = new FormData();
  fd.append('file', f);
  statusEl.textContent = '⏳ Upload...';
  const res = await fetch('/upload', { method: 'POST', body: fd });
  if (!res.ok) { statusEl.textContent = '❌ Upload-Fehler'; alert(await res.text()); return; }
  const data = await res.json();
  dataset_id = data.dataset_id;

  // Modell-Dropdown: zuerst "nothing"
  modelSel.innerHTML = '';
  const opt0 = document.createElement('option');
  opt0.value = ''; opt0.textContent = '— nothing —';
  modelSel.appendChild(opt0);
  data.models.forEach(m => {
    const opt = document.createElement('option');
    opt.value = m; opt.textContent = m;
    modelSel.appendChild(opt);
  });
  statusEl.textContent = `✅ Hochgeladen. Modelle: ${data.models.join(', ')}`;
};

function filterByPath(tree, parts) {
  if (!parts || parts.length < 2) return tree;
  const n = s => (s||"").toString().trim().toLowerCase().replace(/\s+/g,' ');
  let node = tree;
  for (let i=1; i<parts.length; i++){
    const target = n(parts[i]);
    if (!node.children) return tree;
    let next = node.children.find(c => n(c.name) === target);
    if (!next) next = node.children.find(c => n(c.name).startsWith(target));
    if (!next) return tree;
    node = next;
  }
  return JSON.parse(JSON.stringify(node));
}

function drawSingleTreemap(tree, title, targetEl, highlightTerm='') {
  const labels=[], parents=[], ids=[], values=[], texts=[], lineW=[], lineC=[], colors=[];
  const q = (highlightTerm||'').toLowerCase();

  function build(node, parentId) {
    const name = (node.name||'').toString();
    const lname = name.toLowerCase();
    const isHit = q && lname.includes(q);
    const myId = parentId ? (parentId + ' / ' + name) : name;

    let size = 0;
    if (node.children && node.children.length) {
      let sum = 0;
      node.children.forEach(ch => { sum += build(ch, myId); });
      size = Math.max(sum, 1);
    } else {
      size = 1;
    }

    let display = name;
    if (isHit) {
      const idx = lname.indexOf(q);
      display = name.slice(0, idx) + '<b>' + name.slice(idx, idx+q.length) + '</b>' + name.slice(idx+q.length);
    }

    labels.push(name);
    texts.push(display);
    ids.push(myId);
    parents.push(parentId || '');
    values.push(size);
    lineW.push(isHit ? 3 : 1);
    lineC.push(isHit ? 'crimson' : 'rgba(0,0,0,0.3)');
    colors.push(isHit ? 'rgba(220,20,60,0.1)' : null);

    return size;
  }

  build(tree, '');

  Plotly.newPlot(targetEl, [{
    type: 'treemap',
    labels, parents, ids, values, text: texts,
    textinfo: 'label',
    hoverinfo: 'label+value+percent parent',
    marker: { line: { width: lineW, color: lineC }, colors },
    branchvalues: 'total',
    maxdepth: -1,
    pathbar: { visible: true }
  }], { title, height: 700, margin: { t:50, l:25, r:25, b:25 } });
}

$('#btnDraw').onclick = async () => {
  const model = modelSel.value;
  if (!dataset_id || !model) return alert('Bitte zuerst Dataset und ein Modell wählen (nicht "nothing").');
  const res = await fetch(`/tree?dataset_id=${encodeURIComponent(dataset_id)}&model=${encodeURIComponent(model)}`);
  if (!res.ok) { alert(await res.text()); return; }
  const tree = await res.json();

  // Titel = aktuell ausgewähltes Modell
  const target = document.getElementById('plot');
  drawSingleTreemap(tree, model, target, '');
};

$('#btnSearch').onclick = async () => {
  const q = $('#search').value.trim();
  if (!dataset_id || !q) return;
  const selectedModel = modelSel.value || null; // '' => null => alle Modelle

  const res = await fetch('/search', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ dataset_id, query: q, limit: 200, model: selectedModel })
  });
  if (!res.ok) { alert(await res.text()); return; }
  const hits = await res.json();

  // Dropdown befüllen
  resultsDD.innerHTML = '<option value="">-- Treffer auswählen --</option>';
  if (!hits.length) {
    const opt = document.createElement('option');
    opt.value = ''; opt.textContent = 'Keine Treffer';
    resultsDD.appendChild(opt);
    return;
  }

  hits.forEach(h => {
    const opt = document.createElement('option');
    opt.value = JSON.stringify(h);
    opt.textContent = `(${h.model}) ${h.path_label}`;
    resultsDD.appendChild(opt);
  });

  // Optional: direkt ersten Treffer zeichnen
  if (resultsDD.options.length > 1) {
    resultsDD.selectedIndex = 1;
    resultsDD.dispatchEvent(new Event('change'));
  }
};

resultsDD.onchange = async (e) => {
  const val = e.target.value;
  if (!val) return;
  const h = JSON.parse(val);

  // Baum für das Treffer-Modell laden
  const res2 = await fetch(`/tree?dataset_id=${encodeURIComponent(dataset_id)}&model=${encodeURIComponent(h.model)}`);
  if (!res2.ok) { alert(await res2.text()); return; }
  const tree = await res2.json();

  // Subtree holen
  const sub = filterByPath(tree, h.anchor_parts) || tree;

  // Pfad-Skelett bauen (Eltern ohne Geschwister, am Treffer alle Kinder)
  const skeleton = { name: h.anchor_parts[0], children: [] };
  let cursor = skeleton;
  for (let i=1; i<h.anchor_parts.length; i++){
    const n = { name: h.anchor_parts[i], children: [] };
    cursor.children = [n];
    cursor = n;
  }
  cursor.children = JSON.parse(JSON.stringify(sub.children || []));

  // Titel-Logik:
  // 1) Wenn im Model-Dropdown etwas gewählt ist -> diesen Namen
  // 2) sonst Modell aus Treffer verwenden
  // 3) Fallback: aus dem Dropdown-Text ( "(Model) ..." ) parsen
  let modelTitle = modelSel.value;
  if (!modelTitle) modelTitle = h.model;
  if (!modelTitle) {
    const optText = resultsDD.options[resultsDD.selectedIndex]?.textContent || '';
    const m = optText.match(/^\(([^)]+)\)/);
    if (m) modelTitle = m[1];
  }

  const target = document.getElementById('plot');
  const q = $('#search').value.trim();
  drawSingleTreemap(skeleton, modelTitle || 'Treemap', target, q);
};
