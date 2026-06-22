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


# ---------------------------------------------------------------------------
# Correccion de DERIVA (drift) de velocidad / sample-clock.
# Cuando los dos archivos se renderizaron a velocidades un pelin distintas
# (p. ej. un bounce en tiempo real vs offline, o un SRC con otro reloj), el
# desfase no es fijo: crece de forma LINEAL a lo largo del track. Un offset
# unico cuadra una parte y se sale en el resto. Esto lo mide y lo corrige.
# ---------------------------------------------------------------------------

def _lowband(x, sr, fc=250.0):
    """Filtra a graves (kick/bajo). Esa banda esta IGUAL en la mezcla con voz
    y en la instrumental, asi que la correlacion es fiable aunque uno tenga voz."""
    sos = signal.butter(4, fc, "lp", fs=sr, output="sos")
    return signal.sosfiltfilt(sos, x)


def measure_affine(orig, inst, sr, block_s=2.0, step_s=4.0, search=2000):
    """Mide el mapeo afin  inst_idx = alpha*orig_idx + beta  por correlacion en
    banda de graves, con ajuste robusto (rechazo de outliers / beat-hops).

    alpha ~ 1 + (deriva en ppm)/1e6.  Devuelve (alpha, beta, info).
    info: ok, ppm, drift_samples (deriva total acumulada), resid_std (que tan
    recta es la deriva, en muestras), n_inliers, n_total.
    """
    om = orig.mean(1)
    im = inst.mean(1)
    ol = _lowband(om, sr)
    il = _lowband(im, sr)

    # offset global grueso (decimado) para centrar la busqueda por bloque
    D = 8
    ad = signal.decimate(ol, D, ftype="fir")
    idd = signal.decimate(il, D, ftype="fir")
    cc = signal.correlate(ad, idd, "full", "fft")
    lags = signal.correlation_lags(len(ad), len(idd), "full")
    g0 = int(lags[np.argmax(np.abs(cc))]) * D
    # convencion de align(): i_start = max(0,-lag), o sea inst_idx ~ orig_idx - lag
    i0 = -g0  # inst_idx ~ orig_idx + i0 al inicio

    blk = int(block_s * sr)
    step = max(1, int(step_s * sr))
    N = min(len(ol), len(il))
    xs, ys, ws = [], [], []
    for o_s in range(2 * sr, N - blk, step):
        i_s = o_s + i0
        lo = max(0, i_s - search)
        seg = il[lo:i_s + blk + search]
        if i_s < 0 or len(seg) < blk + 4:
            continue
        a = ol[o_s:o_s + blk]
        cc2 = signal.correlate(seg, a, "valid")
        k = int(np.argmax(np.abs(cc2)))
        b_abs = lo + k
        bseg = il[b_abs:b_abs + blk]
        r = abs(np.dot(a, bseg)) / (np.linalg.norm(a) * np.linalg.norm(bseg) + 1e-12)
        xs.append(o_s)
        ys.append(b_abs)
        ws.append(r)

    xs = np.array(xs, float)
    ys = np.array(ys, float)
    ws = np.array(ws, float)
    if len(xs) < 5:
        return 1.0, float(i0), {"ok": False, "reason": "pocos puntos", "n_total": len(xs)}

    # ajuste robusto ponderado: rechazo iterativo de outliers (MAD)
    mask = ws > max(0.4, np.median(ws) * 0.6)
    if mask.sum() < 5:
        mask = ws > 0.0
    alpha, beta = 1.0, float(i0)
    for _ in range(5):
        if mask.sum() < 3:
            break
        alpha, beta = np.polyfit(xs[mask], ys[mask], 1, w=ws[mask])
        resid = ys - (alpha * xs + beta)
        med = np.median(resid[mask])
        mad = np.median(np.abs(resid[mask] - med)) + 1e-9
        newmask = np.abs(resid - med) < 4.0 * 1.4826 * mad
        newmask &= ws > 0.0
        if newmask.sum() >= 5 and not np.array_equal(newmask, mask):
            mask = newmask
        else:
            break

    resid = ys[mask] - (alpha * xs[mask] + beta)
    info = {
        "ok": True,
        "alpha": float(alpha),
        "beta": float(beta),
        "ppm": float((alpha - 1.0) * 1e6),
        "drift_samples": float((alpha - 1.0) * N),
        "resid_std": float(np.std(resid)) if len(resid) else 0.0,
        "n_inliers": int(mask.sum()),
        "n_total": int(len(xs)),
    }
    return float(alpha), float(beta), info


def needs_drift(info, min_drift_samples=4.0, max_resid=10.0, max_ppm=5000.0):
    """Decide si vale la pena corregir deriva: significativa, lineal (residual
    bajo) y dentro de rango de reloj (no una diferencia de sample-rate/tempo)."""
    if not info.get("ok"):
        return False
    return (abs(info["drift_samples"]) >= min_drift_samples
            and info["resid_std"] <= max_resid
            and abs(info["ppm"]) <= max_ppm
            and info["n_inliers"] >= 5)


def invert_affine(orig, inst, alpha, beta, input_db=-6.0, N=8192):
    """Alinea inst a la grilla de orig con el mapeo afin (inst_idx=alpha*orig_idx
    + beta) usando retardo fraccionario por bloques (FFT phase-ramp, banda
    completa, precision sub-muestra) y resta: out = orig - inst_alineada.
    Ganancia unity. Corrige la deriva de punta a punta."""
    k = 10.0 ** (input_db / 20.0)
    orig = orig * k
    inst = inst * k
    nch = orig.shape[1]
    # igualar canales (si la instru es mono, se usa para ambos)
    if inst.shape[1] < nch:
        inst = np.repeat(inst[:, :1], nch, axis=1)

    hop = N // 2
    win = signal.windows.hann(N, sym=False)
    kfreq = np.fft.rfftfreq(N)
    Ia = np.zeros_like(orig)
    wsum = np.zeros(len(orig))
    for n0 in range(0, len(orig) - N, hop):
        src = alpha * n0 + beta
        i = int(np.floor(src))
        frac = src - i
        if i < 0 or i + N > len(inst):
            continue
        X = np.fft.rfft(inst[i:i + N, :nch], axis=0)
        X *= np.exp(-1j * 2 * np.pi * kfreq * frac)[:, None]
        d = np.fft.irfft(X, n=N, axis=0)
        Ia[n0:n0 + N] += d * win[:, None]
        wsum[n0:n0 + N] += win
    cov = wsum > 1e-6
    wsum[~cov] = 1.0
    Ia /= wsum[:, None]

    out = orig.copy()
    out[cov] = orig[cov] - Ia[cov]
    info = {
        "lag_samples": int(round(beta)),
        "gains": ["unity"],
        "alpha": float(alpha),
        "ppm": float((alpha - 1.0) * 1e6),
        "peak": float(np.max(np.abs(out))) if out.size else 0.0,
    }
    return out, info


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
