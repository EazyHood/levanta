"""Self-contained HTML viewer: 2-D plan, interactive 3-D model, measurements table.

Everything is embedded (SVG inline, GLB as base64) so the file can be sent as-is.
The interactive 3-D view loads three.js from a CDN the first time; without internet the
axonometric drawing is shown instead.
"""

from __future__ import annotations

import base64
import datetime as _dt
import html
import json
from pathlib import Path

from levanta.i18n import fmt_area, fmt_len, t
from levanta.plan.types import FloorPlan

THREE_VERSION = "0.160.0"

_CSS = """
:root{--ink:#1d1d1f;--muted:#6b6b6f;--line:#e6e3dd;--bg:#faf8f4;--card:#ffffff;--accent:#8a5a2b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:Inter,'Segoe UI',Helvetica,Arial,sans-serif;line-height:1.45}
header{padding:28px 32px 12px}h1{margin:0 0 4px;font-size:24px;letter-spacing:-.01em}.sum{color:var(--muted);font-size:14px}
main{display:grid;grid-template-columns:1fr;gap:20px;padding:0 32px 40px;max-width:1400px}
@media(min-width:1100px){main{grid-template-columns:1fr 1fr}.wide{grid-column:1/-1}}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 20px;box-shadow:0 1px 2px rgba(0,0,0,.03)}
.card h2{margin:0 0 10px;font-size:15px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.plan svg{width:100%;height:auto;display:block}
#v3d{width:100%;aspect-ratio:4/3;border-radius:10px;background:#f2efe9;position:relative;overflow:hidden}
#v3d canvas{width:100%!important;height:100%!important;display:block}
.hint{font-size:12px;color:var(--muted);margin-top:8px}
.iso svg{width:100%;height:auto;display:block}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line)}th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.05em}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.btns{display:flex;gap:10px;flex-wrap:wrap;margin-top:10px}.btn{display:inline-block;padding:8px 12px;border:1px solid var(--line);border-radius:8px;background:#fff;color:var(--ink);text-decoration:none;font-size:13px}
.btn:hover{border-color:var(--accent)}footer{padding:10px 32px 30px;color:var(--muted);font-size:12px}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;background:#eef3ea;color:#2f5d2a}.badge.open{background:#fbeee6;color:#8a4b1d}
"""

_JS = """
const glbB64 = "__GLB__";
const target = document.getElementById('v3d');
function fallback(msg){ target.innerHTML = '<div style="padding:16px;font-size:13px;color:#6b6b6f">'+msg+'</div>'; document.getElementById('iso').style.display='block'; }
if (!glbB64) { fallback(__NO3D__); } else {
try {
  const s = document.createElement('script'); s.type = 'importmap';
  s.textContent = JSON.stringify({imports:{"three":"https://cdn.jsdelivr.net/npm/three@__V__/build/three.module.js","three/addons/":"https://cdn.jsdelivr.net/npm/three@__V__/examples/jsm/"}});
  document.head.appendChild(s);
  const m = document.createElement('script'); m.type = 'module';
  m.textContent = `
    import * as THREE from 'three';
    import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
    import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
    const el = document.getElementById('v3d');
    const renderer = new THREE.WebGLRenderer({antialias:true, alpha:true});
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(el.clientWidth, el.clientHeight);
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, el.clientWidth/el.clientHeight, 0.05, 500);
    const controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = true;
    scene.add(new THREE.HemisphereLight(0xffffff, 0xb0a890, 2.2));
    const sun = new THREE.DirectionalLight(0xffffff, 2.6); sun.position.set(4, 8, 6); scene.add(sun);
    const fill = new THREE.DirectionalLight(0xffffff, 1.2); fill.position.set(-6, 4, -3); scene.add(fill);
    const bin = Uint8Array.from(atob("${glbB64}"), c => c.charCodeAt(0)).buffer;
    new GLTFLoader().parse(bin, '', (gltf) => {
      const root = gltf.scene; root.rotation.x = -Math.PI/2;  // z-up model -> y-up viewer
      root.traverse((o) => { if (o.isMesh && o.material) { o.material.metalness = 0.0; o.material.roughness = 0.85; o.material.side = THREE.DoubleSide; } });
      scene.add(root);
      const box = new THREE.Box3().setFromObject(root); const size = box.getSize(new THREE.Vector3()); const c = box.getCenter(new THREE.Vector3());
      const r = Math.max(size.x, size.y, size.z);
      camera.position.set(c.x + r*0.9, c.y + r*0.8, c.z + r*1.1); controls.target.copy(c); controls.update();
      const grid = new THREE.GridHelper(Math.ceil(r*2), Math.ceil(r*2), 0xcccccc, 0xe6e3dd); grid.position.set(c.x, box.min.y - 0.01, c.z); scene.add(grid);
    }, (e) => fallback('GLB: ' + e));
    function loop(){ controls.update(); renderer.render(scene, camera); requestAnimationFrame(loop); } loop();
    window.addEventListener('resize', () => { renderer.setSize(el.clientWidth, el.clientHeight); camera.aspect = el.clientWidth/el.clientHeight; camera.updateProjectionMatrix(); });
  `;
  m.onerror = () => fallback(__NO3D__);
  document.head.appendChild(m);
  setTimeout(() => { if (!target.querySelector('canvas')) fallback(__NO3D__); }, 6000);
} catch (e) { fallback(__NO3D__); }
}
"""


def write_html(
    path: str | Path,
    plan: FloorPlan,
    svg_2d: str,
    svg_iso: str,
    glb_bytes: bytes | None,
    lang: str = "en",
    units: str = "m",
    title: str | None = None,
) -> Path:
    path = Path(path)
    ttl = title or t(lang, "floor_plan")
    rooms_rows = "\n".join(
        f"<tr><td>{html.escape(r.name)}</td><td class=num>{fmt_area(r.area, units)}</td>"
        f"<td class=num>{fmt_len(r.shapely.bounds[2] - r.shapely.bounds[0], units)} × {fmt_len(r.shapely.bounds[3] - r.shapely.bounds[1], units)}</td>"
        f"<td><span class='badge{'' if r.closed else ' open'}'>{t(lang, 'closed') if r.closed else t(lang, 'open')}</span></td></tr>"
        for r in plan.rooms
    )
    open_rows = "\n".join(
        f"<tr><td>{t(lang, o.kind)}</td><td class=num>{fmt_len(o.width, units)}</td><td class=num>{fmt_len(o.z0, units)}</td><td class=num>{fmt_len(o.z1, units)}</td></tr>"
        for o in plan.openings
    )
    two_sided = sum(1 for w in plan.walls if w.sides_seen == 2)
    glb_b64 = base64.b64encode(glb_bytes).decode("ascii") if glb_bytes else ""
    svg_data = "data:image/svg+xml;charset=utf-8," + _url(svg_2d)
    glb_data = "data:model/gltf-binary;base64," + glb_b64 if glb_b64 else ""
    js = _JS.replace("__GLB__", glb_b64).replace("__V__", THREE_VERSION).replace("__NO3D__", json.dumps(t(lang, "no_3d")))
    doc = f"""<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(ttl)} · levanta</title><style>{_CSS}</style></head>
<body>
<header><h1>{html.escape(ttl)}</h1>
<div class="sum">{len(plan.rooms)} {t(lang, 'rooms')} · {t(lang, 'total_area').lower()} {fmt_area(plan.total_area, units)} · {t(lang, 'ceiling')} {fmt_len(plan.ceiling_height, units)} ({t(lang, 'measured') if plan.ceiling_measured else t(lang, 'default')}) · {len(plan.walls)} {t(lang, 'walls')} · {_dt.date.today().isoformat()}</div></header>
<main>
<section class="card plan"><h2>{t(lang, 'plan_2d')}</h2>{svg_2d}
<div class="btns"><a class="btn" download="plan.svg" href="{svg_data}">{t(lang, 'download_svg')}</a>{f'<a class="btn" download="model.glb" href="{glb_data}">{t(lang, "download_glb")}</a>' if glb_data else ''}</div></section>
<section class="card"><h2>{t(lang, 'view_3d')}</h2><div id="v3d"></div><div class="hint">{t(lang, 'drag_hint')}</div>
<div id="iso" class="iso" style="display:none;margin-top:12px">{svg_iso}</div></section>
<section class="card wide"><h2>{t(lang, 'measurements')}</h2>
<table><thead><tr><th>{t(lang, 'name')}</th><th>{t(lang, 'area')}</th><th>{t(lang, 'size')}</th><th>{t(lang, 'status')}</th></tr></thead><tbody>{rooms_rows}</tbody></table>
<h2 style="margin-top:18px">{t(lang, 'openings')}</h2>
<table><thead><tr><th>{t(lang, 'kind')}</th><th>{t(lang, 'width')}</th><th>{t(lang, 'bottom')}</th><th>{t(lang, 'top')}</th></tr></thead><tbody>{open_rows or '<tr><td colspan=4>—</td></tr>'}</tbody></table>
<p class="hint">{two_sided}/{len(plan.walls)} {t(lang, 'walls_measured')}.</p></section>
</main>
<footer>{t(lang, 'generated_by')} · MIT · github.com/EazyHood/levanta</footer>
<script>{js}</script>
</body></html>"""
    path.write_text(doc, encoding="utf-8")
    return path


def _url(s: str) -> str:
    from urllib.parse import quote

    return quote(s, safe="")
