"""Plantillas AAA con números calibrados según el tamaño real de las piezas.
Cada plantilla devuelve (lineas_anim, texto_clips)."""
import re

AX = {"x": 0, "y": 1, "z": 2}


def _frente(f):
    m = re.match(r"^([+-])([xz])$", (f or "+z").strip().lower())
    sg, ax = (m.group(1), m.group(2)) if m else ("+", "z")
    return ax, (1 if sg == "+" else -1)


def _pieza(info, nombre):
    return next(p for p in info["piezas"] if p["nombre"] == nombre)


def _g(v):
    return ("%.3f" % v).rstrip("0").rstrip(".")


def _eje_giro(ax):
    """eje de rotación para 'cabecear' (pitch) y signo para que ángulo + = el frente baja"""
    return ("x", 1) if ax == "z" else ("z", -1)


def monstruo(info, roles, frente="+z"):
    ax, sg = _frente(frente)
    cuerpo = roles["cuerpo"][0]
    mand = (roles.get("mandibula") or [None])[0]
    luces = roles.get("luces") or []
    farolas = roles.get("farolas") or []
    pc = _pieza(info, cuerpo)
    L = 2 * pc["mitad"][AX[ax]]
    H = 2 * pc["mitad"][1]
    eje_p, s = _eje_giro(ax)
    s *= sg
    back = ("-" if sg > 0 else "+") + ax
    anim = [f"{cuerpo}: flotar altura={_g(H*0.012)} vel=1.1",
            f"{cuerpo}: balanceo eje={eje_p} ang=0.8 vel=0.6 pivote=-y"]
    for n in luces:
        anim.append(f"{n}: pulso vel=1.4 min=0.7 max=2.4 color=255,140,30 rango=18")
    for n in farolas:
        anim.append(f"{n}: balanceo eje={'z' if ax == 'x' else 'x'} ang=5 vel=1.2 pivote=+y")
    c = []
    fl = f" flash={luces[0]}" if luces else ""
    sh = lambda a: _g(a)
    # RUGIDO
    c.append("clip rugido dur=2.6 mezcla=0.12")
    if mand:
        c.append(f"{mand} rot eje={eje_p} pivote={back}+y | 0:0 0.22:{_g(-4*s)}@cubic 0.58:{_g(34*s)}@back 1.9:{_g(37*s)}@sine 2.6:0@cubic")
    c.append(f"{cuerpo} pos eje={ax} | 0:0 0.22:{_g(-0.03*L*sg)}@cubic 0.58:{_g(0.05*L*sg)}@back 2.6:0@cubic")
    c.append(f"{cuerpo} rot eje={eje_p} pivote=-y | 0:0 0.22:{_g(-2.2*s)}@cubic 0.58:{_g(2.8*s)}@back 2.6:0@cubic")
    c.append(f"fx 0.58 shake=0.9 fov=5 hitstop=0.05{fl} flashfuerza=4")
    c.append(f"fx 0.9 shake=0.35")
    # MORDISCO
    c.append("clip mordisco dur=0.95 mezcla=0.06")
    if mand:
        c.append(f"{mand} rot eje={eje_p} pivote={back}+y | 0:0 0.13:{_g(-3*s)}@cubic 0.36:{_g(31*s)}@cubic 0.46:0@cubicin 0.6:{_g(1.8*s)}@back 0.95:0@cubic")
    c.append(f"{cuerpo} pos eje={ax} | 0:0 0.13:{_g(-0.02*L*sg)}@cubic 0.4:{_g(0.07*L*sg)}@cubicout 0.95:0@cubic")
    c.append(f"fx 0.46 shake=0.6 hitstop=0.04{fl} flashfuerza=3")
    # EMBESTIDA
    c.append("clip embestida dur=1.9 mezcla=0.15")
    c.append(f"{cuerpo} pos eje={ax} | 0:0 0.5:{_g(-0.07*L*sg)}@cubic 0.85:{_g(0.38*L*sg)}@cubic 1.9:0@cubic")
    c.append(f"{cuerpo} rot eje={eje_p} pivote=-y | 0:0 0.5:{_g(-3*s)}@cubic 0.85:{_g(4*s)}@cubic 1.9:0@cubic")
    if mand:
        c.append(f"{mand} rot eje={eje_p} pivote={back}+y | 0:0 0.5:{_g(8*s)}@cubic 0.85:{_g(38*s)}@back 1.9:0@cubic")
    c.append("fx 0.85 shake=1.2 fov=7 hitstop=0.06")
    # GOLPE RECIBIDO
    c.append("clip golpe dur=0.6 mezcla=0.04")
    c.append(f"{cuerpo} pos eje={ax} | 0:0 0.07:{_g(-0.035*L*sg)}@cubicout 0.6:0@cubic")
    c.append(f"{cuerpo} rot eje={eje_p} pivote=-y | 0:0 0.07:{_g(-3.5*s)}@cubicout 0.6:0@back")
    c.append(f"fx 0 shake=0.4 hitstop=0.04{fl} flashfuerza=2.5")
    # APARECER
    c.append("clip aparecer dur=1.7 mezcla=0.05")
    c.append(f"{cuerpo} pos eje=y | 0:{_g(-0.45*H)} 1.05:{_g(0.03*H)}@back 1.7:0@cubic")
    c.append("fx 1.05 shake=0.8 fov=4")
    # MUERTE
    c.append("clip muerte dur=2.4 mezcla=0.1")
    c.append(f"{cuerpo} pos eje=y | 0:0 0.3:{_g(0.01*H)}@cubic 1.9:{_g(-0.12*H)}@cubicin 2.4:{_g(-0.11*H)}@bounce")
    c.append(f"{cuerpo} rot eje={'z' if ax == 'x' else 'x'} pivote=-y | 0:0 0.3:{_g(-2*s)}@cubic 1.9:{_g(14*s)}@cubicin 2.4:{_g(13*s)}@bounce")
    if mand:
        c.append(f"{mand} rot eje={eje_p} pivote={back}+y | 0:0 1.2:{_g(30*s)}@sine 2.4:{_g(36*s)}@cubic")
    c.append("fx 1.9 shake=0.9 fov=3 hitstop=0.05")
    return anim, "\n".join(c)


def tren(info, roles, frente="+z"):
    ax, sg = _frente(frente)
    cuerpo = roles["cuerpo"][0]
    ruedas = roles.get("ruedas") or []
    humo = roles.get("humo") or []
    luces = roles.get("luces") or []
    pc = _pieza(info, cuerpo)
    L = 2 * pc["mitad"][AX[ax]]
    H = 2 * pc["mitad"][1]
    eje_p, s = _eje_giro(ax)
    s *= sg
    roll = ax  # inclinación lateral gira sobre el eje del frente
    anim = [f"{cuerpo}: vibrar fuerza={_g(H*0.003)} vel=20",
            f"{cuerpo}: balanceo eje={roll} ang=0.7 vel=0.8 pivote=-y"]
    for n in ruedas:
        p = _pieza(info, n)
        # eje de la rueda = el eje de menor tamaño (perpendicular al frente)
        eje_r = "x" if ax == "z" else "z"
        radio = max(p["mitad"][1], p["mitad"][AX[ax]])
        signo = sg if ax == "z" else -sg
        anim.append(f"{n}: girar eje={eje_r} vel={_g(signo/max(radio,0.01))}")
    for n in luces:
        anim.append(f"{n}: pulso vel=2 min=1 max=2.2 color=255,235,180 rango=30")
    c = []
    emit_h = (" emit=" + ",".join(humo) + " cantidad=40") if humo else ""
    c.append("clip arranque dur=3.2 mezcla=0.2")
    c.append(f"{cuerpo} pos eje={ax} | 0:0 0.6:{_g(-0.012*L*sg)}@cubic 2.2:{_g(0.004*L*sg)}@cubic 3.2:0@cubic")
    c.append(f"{cuerpo} rot eje={eje_p} pivote=-y | 0:0 0.7:{_g(-1.6*s)}@cubic 2.0:{_g(0.4*s)}@back 3.2:0@cubic")
    c.append(f"fx 0.3 shake=0.35")
    c.append(f"fx 0.7 shake=0.5{emit_h}")
    c.append("clip frenada dur=3.5 mezcla=0.2")
    c.append(f"{cuerpo} rot eje={eje_p} pivote=-y | 0:0 0.5:{_g(2.2*s)}@cubic 1.3:{_g(-0.8*s)}@back 3.5:0@cubic")
    c.append(f"{cuerpo} pos eje={ax} | 0:0 0.5:{_g(0.015*L*sg)}@cubic 3.5:0@cubic")
    c.append("fx 0.1 shake=0.4")
    if ruedas:
        c.append("fx 0.6 shake=0.2 emit=" + ",".join(ruedas) + " cantidad=15")
    c.append("clip silbato dur=1.6 mezcla=0.1")
    c.append(f"{cuerpo} pos eje=y | 0:0 0.1:{_g(0.004*H)}@cubicout 0.5:0@cubic")
    c.append(f"fx 0 shake=0.2{emit_h.replace('cantidad=40','cantidad=70')}")
    return anim, "\n".join(c)


PLANTILLAS = {"monstruo": monstruo, "tren": tren}


def aplicar(nombre, info, roles, frente="+z"):
    f = PLANTILLAS.get(nombre.lower())
    if not f:
        raise ValueError(f"Plantilla desconocida: {nombre} (disponibles: {', '.join(PLANTILLAS)})")
    if not roles.get("cuerpo"):
        raise ValueError("La plantilla necesita al menos cuerpo=parte_XX")
    return f(info, roles, frente)
