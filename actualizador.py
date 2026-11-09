"""Se ejecuta antes de abrir ForgeMesh: descarga solo los archivos que cambiaron.
Sin URL configurada (o sin internet) no hace nada y la app abre normal."""
import os, sys, json, hashlib, shutil, subprocess, time, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import ajustes


def _get(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "ForgeMesh-updater"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def main():
    cfg = ajustes.cargar()
    url = (cfg.get("update_url") or "").strip()
    if not url or not cfg.get("auto_update", True):
        return
    if not url.endswith("/"):
        url += "/"
    try:
        manifest = json.loads(_get(url + "manifest.json").decode("utf-8"))
    except Exception as e:
        print("[actualizador] sin conexión o sin manifiesto, sigo con la versión actual:", str(e)[:80])
        return
    nuevos = []
    for nombre, sha in manifest.get("archivos", {}).items():
        if ".." in nombre or nombre.startswith(("/", "\\")) or nombre in ("config.json",):
            continue
        ruta = os.path.join(BASE, nombre)
        actual = None
        if os.path.exists(ruta):
            with open(ruta, "rb") as f:
                actual = hashlib.sha256(f.read()).hexdigest()
        if actual != sha:
            nuevos.append((nombre, sha))
    if nuevos:
        print(f"[actualizador] actualizando {len(nuevos)} archivo(s)...")
        respaldo = os.path.join(BASE, "_respaldo", time.strftime("%Y%m%d_%H%M%S"))
        descargados = []
        for nombre, sha in nuevos:
            try:
                data = _get(url + nombre, timeout=30)
            except Exception as e:
                print("[actualizador] no pude bajar", nombre, "- cancelo la actualización:", str(e)[:60])
                return
            if hashlib.sha256(data).hexdigest() != sha:
                print("[actualizador] hash incorrecto en", nombre, "- cancelo la actualización")
                return
            descargados.append((nombre, data))
        for nombre, data in descargados:
            ruta = os.path.join(BASE, nombre)
            if os.path.exists(ruta):
                os.makedirs(os.path.dirname(os.path.join(respaldo, nombre)), exist_ok=True)
                shutil.copy2(ruta, os.path.join(respaldo, nombre))
            os.makedirs(os.path.dirname(ruta), exist_ok=True)
            with open(ruta + ".tmp", "wb") as f:
                f.write(data)
            os.replace(ruta + ".tmp", ruta)
        print("[actualizador] listo. Versión:", manifest.get("version", "?"))
    reqs = manifest.get("requirements", [])
    marca = os.path.join(BASE, "requisitos_instalados.json")
    previos = []
    try:
        previos = json.load(open(marca, encoding="utf-8"))
    except Exception:
        pass
    faltan = [r for r in reqs if r not in previos]
    if faltan:
        print("[actualizador] instalando dependencias nuevas:", ", ".join(faltan))
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", *faltan])
        if r.returncode == 0:
            json.dump(sorted(set(previos) | set(reqs)), open(marca, "w", encoding="utf-8"))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("[actualizador] error ignorado:", e)
