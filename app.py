"""
InvertTool - inversion de fase por lotes.
Deja pares (original + instrumental) en la carpeta input/ y entrega la
acapella en output/. La instrumental es SIEMPRE la que se invierte.

Emparejado: en cada par, el archivo cuyo nombre contiene 'instrumental' o
'inst' es la instrumental; el otro es el original. Si una carpeta input/<sub>/
tiene exactamente 2 archivos, tambien funciona.
"""
import json
import os
import sys
import glob

import invert_core as core

HERE = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
CONFIG = os.path.join(HERE, "config.json")
AUDIO_EXT = (".wav", ".flac", ".aif", ".aiff")
INST_HINTS = ("instrumental", "inst", "instru")


def load_config():
    default = {
        "input_folder": os.path.join(HERE, "input"),
        "output_folder": os.path.join(HERE, "output"),
        "gain_mode": "unity",         # unity (default) | peak | fixed | auto
        "fixed_db": -6.0,             # solo si gain_mode = fixed
        "input_db": -6.0,             # headroom en la entrada (anti-clip)
        "output_subtype": "PCM_24",   # PCM_16 | PCM_24 | FLOAT  (default 24)
        "samplerate": "lowest",       # lowest (default, nunca sube de rate) | original
    }
    if os.path.exists(CONFIG):
        try:
            default.update(json.load(open(CONFIG, encoding="utf-8")))
        except Exception:
            pass
    return default


def save_config(cfg):
    json.dump(cfg, open(CONFIG, "w", encoding="utf-8"), indent=2)


def is_inst(name):
    n = name.lower()
    return any(h in n for h in INST_HINTS)


def find_pairs(folder):
    """Devuelve lista de (original_path, instrumental_path, base_name)."""
    pairs = []
    # 1) subcarpetas con 2 archivos
    for sub in sorted(glob.glob(os.path.join(folder, "*"))):
        if os.path.isdir(sub):
            files = [f for f in sorted(glob.glob(os.path.join(sub, "*")))
                     if f.lower().endswith(AUDIO_EXT)]
            if len(files) == 2:
                inst = next((f for f in files if is_inst(os.path.basename(f))), files[1])
                orig = next((f for f in files if f != inst), files[0])
                pairs.append((orig, inst, os.path.basename(sub)))
    # 2) archivos sueltos en la raiz: emparejar inst <-> original por nombre
    flat = [f for f in sorted(glob.glob(os.path.join(folder, "*")))
            if os.path.isfile(f) and f.lower().endswith(AUDIO_EXT)]
    insts = [f for f in flat if is_inst(os.path.basename(f))]
    origs = [f for f in flat if not is_inst(os.path.basename(f))]
    used = set()
    for inst in insts:
        base = os.path.splitext(os.path.basename(inst))[0].lower()
        for h in INST_HINTS:
            base = base.replace(h, "")
        base = base.strip(" -_().")
        # original con nombre mas parecido
        best, score = None, -1
        for o in origs:
            if o in used:
                continue
            ob = os.path.splitext(os.path.basename(o))[0].lower()
            s = sum(1 for w in base.split() if w and w in ob)
            if base and base in ob:
                s += 5
            if s > score:
                best, score = o, s
        if best is None and len(origs) == 1:
            best = origs[0]
        if best:
            used.add(best)
            name = os.path.splitext(os.path.basename(best))[0]
            pairs.append((best, inst, name))
    return pairs


def process(cfg):
    inp, outp = cfg["input_folder"], cfg["output_folder"]
    os.makedirs(inp, exist_ok=True)
    os.makedirs(outp, exist_ok=True)
    pairs = find_pairs(inp)
    if not pairs:
        print(f"\nNo encontre pares en {inp}")
        print("  Pon original + instrumental (nombre con 'instrumental'/'inst'),")
        print("  o subcarpetas con 2 archivos cada una.\n")
        return
    print(f"\n{len(pairs)} par(es) encontrados.\n")
    for orig_p, inst_p, base in pairs:
        try:
            print(f"-> {base}")
            print(f"   original     : {os.path.basename(orig_p)}")
            print(f"   instrumental : {os.path.basename(inst_p)}")
            orig, sr = core.load(orig_p)
            inst, sr2 = core.load(inst_p)
            if sr != sr2:
                # objetivo: por defecto el del original (no se degrada el keeper)
                target = min(sr, sr2) if cfg.get("samplerate") == "lowest" else sr
                print(f"   sample rate   : original {sr} vs instru {sr2} "
                      f"-> resampleo a {target} Hz")
                if sr != target:
                    orig = core.resample(orig, sr, target); sr = target
                if sr2 != target:
                    inst = core.resample(inst, sr2, target)
            out, info = core.invert(orig, inst,
                                    gain_mode=cfg["gain_mode"],
                                    fixed_db=cfg["fixed_db"],
                                    input_db=cfg["input_db"])
            gtxt = ", ".join(f"{g:.3f}" for g in info["gains"])
            print(f"   offset       : {info['lag_samples']} muestras "
                  f"({info['lag_samples']/sr:+.3f}s)")
            print(f"   ganancia      : [{gtxt}]  modo={cfg['gain_mode']}")
            dst = os.path.join(outp, f"{base} - acapella.wav")
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
