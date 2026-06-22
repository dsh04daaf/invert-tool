"""
InvertTool - inversion de fase por lotes.
Deja pares en input/ y entrega el resultado de la inversion en output/.

Dos modos, detectados por el nombre de los archivos:
  - ACAPELLA : un archivo dice 'instrumental'/'inst'. Se invierte la
               instrumental y se resta del original -> acapella.
               Salida: "<original> Aca Invert.wav"
  - INVERT   : un archivo dice 'extended'/'ext'. Se invierte el extended y se
               resta del radio edit (el otro, aunque no diga 'radio').
               Salida: "<radio edit> Invert.wav"

Emparejado: subcarpetas con 2 archivos cada una (recomendado), o archivos
sueltos en la raiz emparejados por nombre.
"""
import json
import math
import os
import re
import sys
import glob

import soundfile as sf

import invert_core as core

HERE = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
CONFIG = os.path.join(HERE, "config.json")
AUDIO_EXT = (".wav", ".flac", ".aif", ".aiff")
INST_HINTS = ("instrumental", "instru", "instr", "inst")
EXT_HINTS = ("extended", "extendedmix", "ext")
# tokens que se quitan al normalizar nombres para emparejar archivos sueltos
STRIP_HINTS = INST_HINTS + EXT_HINTS + ("radio edit", "radio", "short", "edit",
                                        "original mix", "original", "mix")


def load_config():
    default = {
        "input_folder": os.path.join(HERE, "input"),
        "output_folder": os.path.join(HERE, "output"),
        "gain_mode": "unity",         # unity (default) | peak | fixed | auto
        "fixed_db": -6.0,             # solo si gain_mode = fixed
        "input_db": -6.0,             # headroom en la entrada (anti-clip)
        "output_subtype": "PCM_24",   # PCM_16 | PCM_24 | FLOAT  (default 24)
        "samplerate": "lowest",       # lowest (default, nunca sube de rate) | original
        "auto_blockmatch": True,      # auto: si la instru esta a otro nivel/master, usa block-match
        "blockmatch_gain_db": 6.0,    # umbral: solo si |ganancia optima| > esto (conservador)
    }
    if os.path.exists(CONFIG):
        try:
            default.update(json.load(open(CONFIG, encoding="utf-8")))
        except Exception:
            pass
    return default


def save_config(cfg):
    json.dump(cfg, open(CONFIG, "w", encoding="utf-8"), indent=2)


def base_noext(p):
    return os.path.splitext(os.path.basename(p))[0]


def has_hint(name, hints):
    """True si algun hint aparece como token (no como subcadena de otra palabra,
    para que 'ext' no pegue en 'next' ni 'inst' dentro de 'instrumental')."""
    n = name.lower()
    return any(re.search(r"(?<![a-z0-9])" + re.escape(h) + r"(?![a-z0-9])", n)
               for h in hints)


def norm_key(name):
    """Clave para emparejar archivos sueltos: quita qualifiers y puntuacion."""
    n = name.lower()
    for h in sorted(STRIP_HINTS, key=len, reverse=True):
        n = re.sub(r"(?<![a-z0-9])" + re.escape(h) + r"(?![a-z0-9])", "", n)
    return re.sub(r"[^a-z0-9]", "", n)


def classify(a, b):
    """Decide que archivo se invierte. Devuelve (keeper, inverted, suffix, name_src)
    o None. keeper = el que NO se invierte (se queda su duracion completa).
    name_src = archivo cuyo nombre se usa para la salida."""
    na, nb = base_noext(a), base_noext(b)
    ea, eb = has_hint(na, EXT_HINTS), has_hint(nb, EXT_HINTS)
    if ea != eb:                          # uno es extended -> modo INVERT
        ext = a if ea else b              # extended = KEEPER (duracion completa)
        radio = b if ea else a            # radio edit = se invierte
        # "extended sin el radio": se resta el radio del extended y quedan las
        # partes exclusivas del extended. Nombre = el del radio (nombre limpio).
        return ext, radio, "Invert", radio
    ia, ib = has_hint(na, INST_HINTS), has_hint(nb, INST_HINTS)
    if ia != ib:                          # uno es instrumental -> modo ACAPELLA
        inverted = a if ia else b
        keeper = b if ia else a           # el otro = original (keeper y nombre)
        return keeper, inverted, "Aca Invert", keeper
    # sin etiquetas: usar duracion (mas largo = extended = keeper)
    try:
        fa, fb = sf.info(a).frames, sf.info(b).frames
        sr = sf.info(a).samplerate or 44100
        if abs(fa - fb) > 0.5 * sr:
            ext = a if fa > fb else b     # el mas largo = keeper
            radio = b if fa > fb else a
            return ext, radio, "Invert", radio
    except Exception:
        pass
    return None                           # no se puede decidir con certeza


def find_pairs(folder):
    """Devuelve lista de (fileA, fileB, group_label)."""
    pairs = []
    # 1) subcarpetas con exactamente 2 archivos
    for sub in sorted(glob.glob(os.path.join(folder, "*"))):
        if os.path.isdir(sub):
            files = [f for f in sorted(glob.glob(os.path.join(sub, "*")))
                     if f.lower().endswith(AUDIO_EXT)]
            if len(files) == 2:
                pairs.append((files[0], files[1], os.path.basename(sub)))
    # 2) archivos sueltos en la raiz: agrupar por nombre normalizado
    flat = [f for f in sorted(glob.glob(os.path.join(folder, "*")))
            if os.path.isfile(f) and f.lower().endswith(AUDIO_EXT)]
    groups = {}
    for f in flat:
        groups.setdefault(norm_key(base_noext(f)), []).append(f)
    for key, files in groups.items():
        if len(files) == 2:
            pairs.append((files[0], files[1], key))
    return pairs


def process(cfg):
    inp, outp = cfg["input_folder"], cfg["output_folder"]
    os.makedirs(inp, exist_ok=True)
    os.makedirs(outp, exist_ok=True)
    pairs = find_pairs(inp)
    if not pairs:
        print(f"\nNo encontre pares en {inp}")
        print("  Pon subcarpetas con 2 archivos cada una, o 2 archivos sueltos.")
        print("  Etiqueta uno con 'instrumental'/'inst' (acapella) o 'extended'/'ext'.\n")
        return
    print(f"\n{len(pairs)} par(es) encontrados.\n")
    for fa, fb, group in pairs:
        try:
            res = classify(fa, fb)
            if not res:
                print(f"-> {group}\n   [omitido] no pude saber cual invertir "
                      f"(sin 'instrumental'/'extended' y misma duracion)\n")
                continue
            keeper, inverted, suffix, name_src = res
            mode = "ACAPELLA" if suffix == "Aca Invert" else "INVERT"
            print(f"-> {group}  [{mode}]")
            print(f"   keeper (queda): {os.path.basename(keeper)}")
            print(f"   se invierte   : {os.path.basename(inverted)}")
            orig, sr = core.load(keeper)
            inst, sr2 = core.load(inverted)
            if sr != sr2:
                target = min(sr, sr2) if cfg.get("samplerate") == "lowest" else sr
                print(f"   sample rate   : {sr} vs {sr2} -> resampleo a {target} Hz")
                if sr != target:
                    orig = core.resample(orig, sr, target); sr = target
                if sr2 != target:
                    inst = core.resample(inst, sr2, target)
            # auto block-match: si la instru esta a otro nivel/master (ganancia
            # optima lejos de 1) se usa block-match. Umbral conservador: una
            # instru solo un poco mas baja NO lo dispara.
            used_mode = cfg["gain_mode"]
            if cfg.get("auto_blockmatch", True) and cfg["gain_mode"] == "unity":
                g = core.optimal_gain(orig, inst)
                gdb = 20 * math.log10(abs(g)) if g else 0.0
                if abs(gdb) > cfg.get("blockmatch_gain_db", 6.0):
                    print(f"   [auto] instru a {gdb:+.1f} dB del original "
                          f"-> block-match (instru sin master)")
                    out, info = core.invert_blockmatch(orig, inst, input_db=cfg["input_db"])
                    used_mode = "block-match"
                else:
                    out, info = core.invert(orig, inst, gain_mode="unity",
                                            input_db=cfg["input_db"])
            else:
                out, info = core.invert(orig, inst, gain_mode=cfg["gain_mode"],
                                        fixed_db=cfg["fixed_db"], input_db=cfg["input_db"])
            gtxt = ", ".join((g if isinstance(g, str) else f"{g:.3f}")
                             for g in info["gains"])
            print(f"   offset        : {info['lag_samples']} muestras "
                  f"({info['lag_samples']/sr:+.3f}s)")
            print(f"   ganancia      : [{gtxt}]  modo={used_mode}")
            dst = os.path.join(outp, f"{base_noext(name_src)} {suffix}.wav")
            extra_db = core.write(dst, out, sr, subtype=cfg["output_subtype"])
            if extra_db < 0:
                print(f"   [i] red de seguridad: {extra_db:.1f} dB extra para evitar clip")
            print(f"   OK -> {os.path.basename(dst)}\n")
        except Exception as e:
            print(f"   [ERROR] {e}\n")
    print("Listo.\n")


def configure(cfg):
    print("\n--- Configuracion (Enter para dejar igual) ---")
    for k, prompt in [("input_folder", "Carpeta input"),
                      ("output_folder", "Carpeta output")]:
        v = input(f"{prompt} [{cfg[k]}]: ").strip()
        if v:
            cfg[k] = v
    print("  Modos: unity (alinear+invertir) | peak (cuadra techo de master)")
    print("         fixed (dB manual)        | auto (energia, no recomendado)")
    g = input(f"Ganancia unity/peak/fixed/auto [{cfg['gain_mode']}]: ").strip().lower()
    if g in ("auto", "unity", "fixed", "peak"):
        cfg["gain_mode"] = g
    if cfg["gain_mode"] == "fixed":
        v = input(f"dB fijo [{cfg['fixed_db']}]: ").strip()
        if v:
            try: cfg["fixed_db"] = float(v)
            except ValueError: pass
    st = input(f"Formato salida PCM_16/PCM_24/FLOAT [{cfg['output_subtype']}]: ").strip().upper()
    if st in ("PCM_16", "PCM_24", "FLOAT"):
        cfg["output_subtype"] = st
    save_config(cfg)
    print("Guardado.\n")


def main():
    cfg = load_config()
    save_config(cfg)
    while True:
        print("=" * 48)
        print(" InvertTool - inversion de fase por lotes")
        print("=" * 48)
        print(f" input : {cfg['input_folder']}")
        print(f" output: {cfg['output_folder']}")
        print(f" gain  : {cfg['gain_mode']}"
              + (f" ({cfg['fixed_db']} dB)" if cfg['gain_mode'] == 'fixed' else ""))
        print("-" * 48)
        print(" 1) Procesar carpeta input")
        print(" 2) Configurar")
        print(" 3) Salir")
        choice = input("> ").strip()
        if choice == "1":
            process(cfg)
        elif choice == "2":
            configure(cfg)
        elif choice == "3":
            break
        else:
            print("Opcion invalida.\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
