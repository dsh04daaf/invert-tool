"""
Motor de inversion de fase.
Alinea automaticamente la instrumental dentro del original (correlacion cruzada),
la invierte y la resta -> acapella (voz). Sin limpieza posterior.

    resultado = original - g * instrumental

g = ganancia. Por defecto 'auto' (minimos cuadrados = la que mas cancela).
"""
from math import gcd

import numpy as np
import soundfile as sf
from scipy import signal


def load(path):
    x, sr = sf.read(path, always_2d=True, dtype="float64")
    return x, sr


def resample(x, src_sr, dst_sr):
    """Resamplea de alta calidad (polyphase) para no meter errores de fase
    que arruinen la cancelacion. 44.1<->48 = ratio 147/160."""
    if int(src_sr) == int(dst_sr):
        return x
    g = gcd(int(src_sr), int(dst_sr))
    up, down = int(dst_sr) // g, int(src_sr) // g
    return signal.resample_poly(x, up, down, axis=0)


def find_offset(orig_mono, inst_mono, decim=8):
    """Offset (en muestras) de la instrumental respecto al original.
    Puede ser negativo si la instrumental empieza antes. Busqueda coarse
    (decimada) + refinamiento fino a resolucion completa."""
    D = decim
    od = signal.decimate(orig_mono, D, ftype="fir")
    idd = signal.decimate(inst_mono, D, ftype="fir")
    cc = signal.correlate(od, idd, "full", "fft")
    lags = signal.correlation_lags(len(od), len(idd), "full")
    lag0 = int(lags[np.argmax(np.abs(cc))]) * D

    W = 4 * D
    lo = max(0, lag0 - W)
    seg = orig_mono[lo: lo + len(inst_mono) + 2 * W]
    if len(seg) < 16:
        return lag0
    cc2 = signal.correlate(seg, inst_mono, "full", "fft")
    l2 = signal.correlation_lags(len(seg), len(inst_mono), "full")
    return lo + int(l2[np.argmax(np.abs(cc2))])


def align(orig, inst):
    """Alinea y devuelve (lag, o_start, i_start, L) de la region de solape."""
    lag = find_offset(orig.mean(1), inst.mean(1))
    o_start = max(0, lag)
    i_start = max(0, -lag)
    L = min(orig.shape[0] - o_start, inst.shape[0] - i_start)
    if L <= 0:
        raise ValueError("No hay solape entre los dos archivos tras alinear.")
    return lag, o_start, i_start, L


def optimal_gain(orig, inst):
    """Ganancia global optima (minimos cuadrados, mono) que necesita la instru
    para igualar al original. ~1.0 = mismo nivel/master; lejos de 1 = la instru
    esta a otro estado (p. ej. sin master, mucho mas baja)."""
    _, o0, i0, L = align(orig, inst)
    O = orig[o0:o0 + L].mean(1)
    I = inst[i0:i0 + L].mean(1)
    den = float(np.dot(I, I))
    return float(np.dot(O, I) / den) if den > 0 else 1.0


def invert_blockmatch(orig, inst, input_db=-6.0, block=8192, margin=24):
    """Inversion por bloques: cada bloque con su ganancia y micro-desfase
    propios. Matchea nivel/EQ del master y sigue la deriva. Para instrumentales
    a otro estado de procesamiento (sin master). out = original - instru_match."""
    k = 10.0 ** (input_db / 20.0)
    orig = orig * k
    inst = inst * k
    lag, o0, i0, L = align(orig, inst)
    O = orig[o0:o0 + L]
    I = inst[i0:i0 + L]
    hop = block // 2
    win = signal.windows.hann(block, sym=False)
    region = np.zeros((L, 2))
    wsum = np.zeros(L)
    Om = O.mean(1)
    Im = I.mean(1)
    for s in range(0, L - block, hop):
        om = Om[s:s + block]
        best = (1e18, 0)
        for d in range(-margin, margin + 1):
            a = s + d
            if a < 0 or a + block > L:
                continue
            im = Im[a:a + block]
            g = np.dot(om, im) / (np.dot(im, im) + 1e-12)
            e = float(np.sum((om - g * im) ** 2))
            if e < best[0]:
                best = (e, d)
        d = best[1]
        a = s + d
        if a < 0 or a + block > L:
            region[s:s + block] += O[s:s + block] * win[:, None]
            wsum[s:s + block] += win
            continue
        i_blk = I[a:a + block]
        res = np.empty((block, 2))
        for ch in range(2):
            ic = i_blk[:, ch]
            oc = O[s:s + block, ch]
            g = np.dot(oc, ic) / (np.dot(ic, ic) + 1e-12)
            res[:, ch] = oc - g * ic
        region[s:s + block] += res * win[:, None]
        wsum[s:s + block] += win
    cov = wsum > 1e-6
    wsum[~cov] = 1.0
    region /= wsum[:, None]
    out_region = O.copy()
    out_region[cov] = region[cov]
    out = orig.copy()
    out[o0:o0 + L] = out_region
    info = {"lag_samples": lag, "gains": ["adaptativo"],
            "peak": float(np.max(np.abs(out))) if out.size else 0.0}
    return out, info


def invert(orig, inst, gain_mode="unity", fixed_db=0.0, input_db=-6.0):
    """Devuelve (resultado, info).
    input_db : se bajan AMBAS entradas este dB desde el principio (-6 por
               defecto) para tener headroom y no clippear nunca, como en Audacity.
    gain_mode:
      'unity' : g = 1.0 (alinear + invertir, sin tocar nivel). DEFAULT.
      'peak'  : cuadra el TECHO de master (pico dBFS): g = pico_orig / pico_inst.
                Para cuando los bounces salieron a techos un pelin distintos.
      'fixed' : g = 10**(fixed_db/20). Ajuste manual en dB.
      'auto'  : minimos cuadrados (energia). NO recomendado: baja la instrumental
                de mas porque la mezcla con voz tiene mas energia que la instru.
    """
    # ganancia de techo de master (pico) ANTES de bajar entradas
    peak_gain = 1.0
    pidet = float(np.max(np.abs(inst)))
    if pidet > 0:
        peak_gain = float(np.max(np.abs(orig)) / pidet)

    # -6 dB a la entrada (ambos tracks), para empezar con headroom
    k = 10.0 ** (input_db / 20.0)
    orig = orig * k
    inst = inst * k

    mo = orig.mean(1)
    mi = inst.mean(1)
    lag = find_offset(mo, mi)

    o_start = max(0, lag)
    i_start = max(0, -lag)
    L = min(orig.shape[0] - o_start, inst.shape[0] - i_start)
    if L <= 0:
        raise ValueError("No hay solape entre los dos archivos tras alinear.")

    O = orig[o_start:o_start + L]
    I = inst[i_start:i_start + L]

    out = orig.copy()
    nch = orig.shape[1]
    gains = []
    for ch in range(nch):
        ic = I[:, ch % inst.shape[1]]
        oc = O[:, ch]
        if gain_mode == "auto":
            den = float(np.dot(ic, ic))
            g = float(np.dot(oc, ic) / den) if den > 0 else 0.0
        elif gain_mode == "peak":
            g = peak_gain
        elif gain_mode == "fixed":
            g = 10.0 ** (fixed_db / 20.0)
        else:  # unity
            g = 1.0
        gains.append(g)
        out[o_start:o_start + L, ch] = oc - g * ic

    info = {
        "lag_samples": lag,
        "offset_seconds": lag / 44100.0,  # informativo; sr real abajo
        "overlap_seconds": L,             # se ajusta con sr afuera
        "gains": gains,
        "peak": float(np.max(np.abs(out))) if out.size else 0.0,
    }
    return out, info


def write(path, data, sr, subtype="PCM_24"):
    """Escribe WAV. El headroom ya se aplico en la entrada (-6 dB). Aqui solo
    una red de seguridad: si por algo el pico se pasara (raro), baja un poco."""
    peak = float(np.max(np.abs(data))) if data.size else 0.0
    extra_db = 0.0
    if peak > 0.999:
        f = 0.999 / peak
        data = data * f
        extra_db = 20.0 * np.log10(f)
    sf.write(path, data, sr, subtype=subtype)
    return extra_db
