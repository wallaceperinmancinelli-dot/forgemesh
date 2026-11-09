"""Separar un modelo en piezas y generar el script Luau de animación (todo local, sin IA)."""
import os, re, json, unicodedata
import numpy as np
import trimesh

AXES = {"x": 0, "y": 1, "z": 2}
DEFAULTS = {
    "girar":    dict(eje="y", vel=3.0, pivote="centro"),
    "bisagra":  dict(eje="x", ang=35.0, periodo=3.0, pivote="centro"),
    "vibrar":   dict(fuerza=0.05, vel=30.0),
    "flotar":   dict(altura=0.4, vel=1.5),
    "balanceo": dict(eje="z", ang=8.0, vel=1.3, pivote="+y"),
    "pulso":    dict(vel=1.5, min=0.5, max=2.0, color="255,150,40", rango=14.0),
}
AYUDA = """**Capas base** (una por línea, se pueden repetir en la misma pieza): `parte_03: girar eje=x vel=4`
- `girar` eje, vel (rad/s) · `bisagra` eje, ang, periodo, pivote · `vibrar` fuerza, vel · `flotar` altura, vel · `balanceo` eje, ang, vel, pivote · `pulso` vel, min, max, color=R,G,B, rango
- `pivote` = centro o combinación de bordes: `+y`, `-z`, `-z+y` (borde de la pieza donde está la bisagra)

**Clips** (acciones puntuales con keyframes y efectos):
```
clip rugido dur=2.6 mezcla=0.12 loop=no
parte_03 rot eje=x pivote=-z+y | 0:0 0.2:-4@cubic 0.55:34@back 1.9:36 2.6:0@cubic
parte_01 pos eje=z | 0:0 0.2:-0.4@cubic 0.55:0.7@back 2.6:0@cubic
fx 0.55 shake=0.9 fov=5 hitstop=0.05 flash=parte_05 sound=rbxassetid://123 emit=parte_05 cantidad=25
```
Keys `tiempo:valor@easing` (grados en `rot`, studs en `pos`). Easings: linear, cubic, cubicout, cubicin, back, backin, elastic, bounce, sine, expo, hold."""


def _norm(s):
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn").strip()


def _face_labels(mesh):
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    key = np.round(mesh.vertices / 1e-4).astype(np.int64)
    _, inv = np.unique(key, axis=0, return_inverse=True)
    inv = np.asarray(inv).reshape(-1)
    f = inv[mesh.faces]
    e = np.vstack([f[:, [0, 1]], f[:, [1, 2]]])
    n = int(inv.max()) + 1
    g = coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(n, n))
    _, lab = connected_components(g, directed=False)
    return lab[f[:, 0]]


def _sub(mesh, mask):
    m = mesh.copy()
    m.update_faces(mask)
    m.remove_unreferenced_vertices()
    return m


def _write_obj(mesh, path, name):
    uv = getattr(mesh.visual, "uv", None)
    nrm = mesh.vertex_normals
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"o {name}\n")
        for v in mesh.vertices:
            f.write(f"v {v[0]:.5f} {v[1]:.5f} {v[2]:.5f}\n")
        if uv is not None:
            for t in uv:
                f.write(f"vt {t[0]:.5f} {t[1]:.5f}\n")
        for n in nrm:
            f.write(f"vn {n[0]:.4f} {n[1]:.4f} {n[2]:.4f}\n")
        for a, b, c in mesh.faces + 1:
            if uv is not None:
                f.write(f"f {a}/{a}/{a} {b}/{b}/{b} {c}/{c}/{c}\n")
            else:
                f.write(f"f {a}//{a} {b}//{b} {c}//{c}\n")


def separar(path, outdir, nombre="modelo", min_frac=0.004, cortes="", log=print):
    mesh = trimesh.load(path, force="mesh", process=False)
    os.makedirs(outdir, exist_ok=True)
    b = mesh.bounds
    log(f"Modelo: X {b[0][0]:.1f}..{b[1][0]:.1f} · Y {b[0][1]:.1f}..{b[1][1]:.1f} · Z {b[0][2]:.1f}..{b[1][2]:.1f}")
    lab = _face_labels(mesh)
    ids, counts = np.unique(lab, return_counts=True)
    total = len(mesh.faces)
    big = [i for i, c in zip(ids, counts) if c >= total * min_frac]
    if not big:
        big = [ids[np.argmax(counts)]]
    cent = {i: mesh.triangles_center[lab == i].mean(axis=0) for i in ids}
    groups = {i: lab == i for i in big}
    for i in ids:  # islas chicas -> pieza grande más cercana
        if i not in groups:
            j = min(big, key=lambda k: np.linalg.norm(cent[k] - cent[i]))
            groups[j] = groups[j] | (lab == i)
    parts = [(f"parte_{k+1:02d}", m) for k, m in enumerate(groups.values())]
    parts = [(n, _sub(mesh, m)) for n, m in parts]
    log(f"Piezas separadas automáticamente: {len(parts)}")

    # cortes manuales: "y=3.2" (todas las piezas) o "parte_01:y=3.2" (solo esa)
    for raw in re.split(r"[,\n;]+", cortes or ""):
        raw = raw.strip()
        if not raw:
            continue
        mt = re.match(r"^(?:(parte_\d+)\s*:\s*)?([xyz])\s*=\s*(-?[\d.]+)$", raw.lower())
        if not mt:
            log(f"Corte ignorado (formato no válido): {raw}")
            continue
        target, ax, val = mt.group(1), AXES[mt.group(2)], float(mt.group(3))
        new = []
        for n, m in parts:
            if target and n != target:
                new.append((n, m)); continue
            c = m.triangles_center[:, ax]
            hi = c > val
            if hi.all() or (~hi).all():
                new.append((n, m)); continue
            new.append((n + "_a", _sub(m, ~hi)))
            new.append((n + "_b", _sub(m, hi)))
            log(f"Corte {mt.group(2)}={val} aplicado a {n}")
        parts = new

    parts.sort(key=lambda p: -float(np.prod(np.maximum(p[1].extents, 1e-6))))
    root_c = parts[0][1].bounds.mean(axis=0)
    info = {"modelo": nombre, "carpeta": outdir, "piezas": []}
    for k, (_, m) in enumerate(parts):
        name = f"parte_{k+1:02d}"
        c = m.bounds.mean(axis=0)
        m.apply_translation(-c)
        _write_obj(m, os.path.join(outdir, name + ".obj"), name)
        info["piezas"].append({"nombre": name, "offset": (c - root_c).tolist(),
                               "mitad": (m.extents / 2).tolist(), "tris": int(len(m.faces))})
        log(f"  {name}: {len(m.faces):,} tris · tamaño {m.extents.round(1).tolist()}")
    # texturas una sola vez (se comparten entre todas las piezas)
    mat = getattr(mesh.visual, "material", None)
    if mat is not None:
        bc = getattr(mat, "baseColorTexture", None) or getattr(mat, "image", None)
        if bc is not None:
            bc.convert("RGB").save(os.path.join(outdir, "color.png"))
        mr = getattr(mat, "metallicRoughnessTexture", None)
        if mr is not None:
            r, g, bl = mr.convert("RGB").split()
            bl.save(os.path.join(outdir, "metalness.png"))
            g.save(os.path.join(outdir, "roughness.png"))
    with open(os.path.join(outdir, "partes.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, indent=1)
    return info



def _real(n, info):
    n = (n or "").strip()
    nombres = {p["nombre"] for p in info["piezas"]}
    if n in nombres:
        return n
    return (info.get("alias") or {}).get(_norm(n))


def plantilla_animacion(info):
    return "\n".join(f"{p['nombre']}: ninguna" for p in info["piezas"])


def _vec(a):
    return "Vector3.new(%.4f, %.4f, %.4f)" % tuple(a)


def _pivot(piv, mitad):
    v = [0.0, 0.0, 0.0]
    for sg, ax in re.findall(r"([+-])([xyz])", piv or ""):
        v[AXES[ax]] += (1 if sg == "+" else -1) * mitad[AXES[ax]]
    return v


def _f(d, k, default):
    try:
        return float(d.get(k, default))
    except (TypeError, ValueError):
        return float(default)


def _eje(e):
    return {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}.get(str(e).strip(), (0, 1, 0))


def parse_anim(text, info):
    por = {p["nombre"]: p for p in info["piezas"]}
    cfg, errores = {}, []
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or ":" not in ln:
            continue
        nom, resto = ln.split(":", 1)
        real = _real(nom, info)
        if real is None:
            errores.append(f"Pieza desconocida: {nom.strip()}"); continue
        toks = _norm(resto).split()
        if not toks or toks[0] in ("ninguna", "ninguno", "-"):
            continue
        tipo = toks[0]
        if tipo not in DEFAULTS:
            errores.append(f"{real}: animación '{tipo}' no existe"); continue
        d = dict(DEFAULTS[tipo])
        for t in toks[1:]:
            if "=" in t:
                k, v = t.split("=", 1)
                d[k] = v
        cfg.setdefault(real, []).append((tipo, d))
    return cfg, errores


_KEY = re.compile(r"^(-?[\d.]+):(-?[\d.]+)(?:@([a-z]+))?$")


def parse_clips(text, info):
    """Devuelve ({nombre: {...}}, errores)."""
    clips, errores, cur = {}, [], None
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        m = re.match(r"^clip\s+(\w+)\s*(.*)$", ln, flags=re.I)
        if m:
            kv = dict(x.split("=", 1) for x in _norm(m.group(2)).split() if "=" in x)
            cur = {"dur": _f(kv, "dur", 0), "loop": kv.get("loop", "no") in ("si", "yes", "true", "1"),
                   "mezcla": _f(kv, "mezcla", 0.12), "tracks": [], "fx": []}
            clips[m.group(1).lower()] = cur
            continue
        if cur is None:
            errores.append(f"Línea fuera de un clip: {ln[:40]}"); continue
        m = re.match(r"^fx\s+([\d.]+)\s*(.*)$", ln, flags=re.I)
        if m:
            kv = dict(x.split("=", 1) for x in m.group(2).split() if "=" in x)
            fx = {"t": float(m.group(1))}
            for k in ("shake", "fov", "hitstop", "cantidad", "rango", "vol", "flashfuerza"):
                if k in kv:
                    fx[k] = _f(kv, k, 0)
            if "flash" in kv:
                r = _real(kv["flash"], info); fx["flash"] = r
            if "sound" in kv:
                fx["sound"] = kv["sound"]
            if "emit" in kv:
                fx["emit"] = [r for r in (_real(x, info) for x in kv["emit"].split(",")) if r]
            cur["fx"].append(fx)
            continue
        m = re.match(r"^(\S+)\s+(rot|pos)\s*(.*?)\s*\|\s*(.+)$", ln, flags=re.I)
        if not m:
            errores.append(f"Línea de clip no válida: {ln[:50]}"); continue
        real = _real(m.group(1), info)
        if real is None:
            errores.append(f"Pieza desconocida en clip: {m.group(1)}"); continue
        kv = dict(x.split("=", 1) for x in _norm(m.group(3)).split() if "=" in x)
        keys = []
        for tok in m.group(4).split():
            mk = _KEY.match(tok.lower())
            if not mk:
                errores.append(f"Key no válida: {tok}"); continue
            keys.append([float(mk.group(1)), float(mk.group(2)), mk.group(3) or "cubic"])
        if len(keys) < 2:
            errores.append(f"{real}: necesita al menos 2 keys"); continue
        keys.sort(key=lambda k: k[0])
        pieza = next(p for p in info["piezas"] if p["nombre"] == real)
        cur["tracks"].append({"parte": real, "tipo": m.group(2).lower(), "eje": _eje(kv.get("eje", "x")),
                              "pivot": _pivot(kv.get("pivote", "centro"), pieza["mitad"]), "keys": keys})
    for nombre, c in clips.items():
        if not c["dur"]:
            c["dur"] = max([k[0] for tr in c["tracks"] for k in tr["keys"]] + [f["t"] for f in c["fx"]] + [0.5])
    return clips, errores


def _lstr(s):
    return json.dumps(str(s), ensure_ascii=False)


def _clips_lua(clips):
    out = []
    for nombre, c in clips.items():
        tr = []
        for t in c["tracks"]:
            keys = ", ".join("{ %.4f, %.4f, %s }" % (k[0], k[1], _lstr(k[2])) for k in t["keys"])
            tr.append("\t\t\t{ parte = %s, tipo = %s, eje = %s, pivot = %s, keys = { %s } }," % (
                _lstr(t["parte"]), _lstr(t["tipo"]), _vec(t["eje"]), _vec(t["pivot"]), keys))
        fxs = []
        for f in c["fx"]:
            parts_ = ["t = %.4f" % f["t"]]
            for k in ("shake", "fov", "hitstop", "cantidad", "rango", "vol", "flashfuerza"):
                if k in f:
                    parts_.append("%s = %.4f" % (k, f[k]))
            if f.get("flash"):
                parts_.append("flash = " + _lstr(f["flash"]))
            if f.get("sound"):
                parts_.append("sound = " + _lstr(f["sound"]))
            if f.get("emit"):
                parts_.append("emit = { " + ", ".join(_lstr(x) for x in f["emit"]) + " }")
            fxs.append("\t\t\t{ " + ", ".join(parts_) + " },")
        out.append("\t%s = {\n\t\tdur = %.4f, loop = %s, mezcla = %.4f,\n\t\ttracks = {\n%s\n\t\t},\n\t\tfx = {\n%s\n\t\t},\n\t}," % (
            nombre, c["dur"], "true" if c["loop"] else "false", c["mezcla"], "\n".join(tr), "\n".join(fxs)))
    return "\n".join(out)


def generar_luau(info, anim_text, clips_text="", color_id="", metal_id="", rough_id=""):
    cfg, errores = parse_anim(anim_text, info)
    clips, e2 = parse_clips(clips_text, info)
    errores += e2
    filas = []
    for p in info["piezas"]:
        capas = []
        for tipo, d in cfg.get(p["nombre"], []):
            try:
                col = [float(x) for x in str(d.get("color", "255,150,40")).split(",")][:3]
            except ValueError:
                col = [255, 150, 40]
            capas.append(
                '{ anim = "%s", pivot = %s, eje = %s, vel = %.4f, ang = %.4f, periodo = %.4f, fuerza = %.4f, '
                'altura = %.4f, min = %.4f, max = %.4f, color = Color3.fromRGB(%d, %d, %d), rango = %.4f }' % (
                    tipo, _vec(_pivot(d.get("pivote", "centro"), p["mitad"])), _vec(_eje(d.get("eje", "y"))),
                    _f(d, "vel", 1), _f(d, "ang", 30), max(_f(d, "periodo", 3), 0.2), _f(d, "fuerza", 0.05),
                    _f(d, "altura", 0.4), _f(d, "min", 0.5), _f(d, "max", 2), col[0], col[1], col[2],
                    _f(d, "rango", 14)))
        filas.append('\t{ name = "%s", offset = %s, capas = { %s } },' % (
            p["nombre"], _vec(p["offset"]), ", ".join(capas)))
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "motor_luau.lua"), encoding="utf-8") as f:
        tpl = f.read()
    code = tpl.replace("__MODELO__", info["modelo"]).replace("__FILAS__", "\n".join(filas)) \
        .replace("__CLIPS__", _clips_lua(clips)).replace("__COLOR__", color_id).replace("__METAL__", metal_id) \
        .replace("__ROUGH__", rough_id)
    return code, errores


def luau_plataforma():
    return PLATAFORMA


PLATAFORMA = r'''--!nocheck
-- ForgeMesh: plataforma móvil (para que los jugadores viajen de pie sobre el tren).
-- LocalScript en StarterPlayer > StarterPlayerScripts.
-- Marca con el Tag "ForgePlataforma" (Tag Editor de Studio) los pisos por donde camina el jugador.
local Players = game:GetService("Players")
local RunService = game:GetService("RunService")
local CollectionService = game:GetService("CollectionService")

local TAG = "ForgePlataforma"
local ALCANCE = 6 -- studs hacia abajo para detectar el piso
local previo = setmetatable({}, { __mode = "k" })

local params = RaycastParams.new()
params.FilterType = Enum.RaycastFilterType.Exclude

RunService.Heartbeat:Connect(function()
	local char = Players.LocalPlayer.Character
	local hrp = char and char:FindFirstChild("HumanoidRootPart")
	if hrp then
		params.FilterDescendantsInstances = { char }
		local hit = workspace:Raycast(hrp.Position, Vector3.new(0, -ALCANCE, 0), params)
		local piso = hit and hit.Instance
		if piso and CollectionService:HasTag(piso, TAG) and previo[piso] then
			local delta = piso.CFrame * previo[piso]:Inverse()
			hrp.CFrame = delta * hrp.CFrame
		end
	end
	for _, p in ipairs(CollectionService:GetTagged(TAG)) do
		previo[p] = p.CFrame
	end
end)
'''
