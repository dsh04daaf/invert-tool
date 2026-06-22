# InvertTool

Inversión de fase por lotes. Dejas pares en una carpeta, encuentra el offset
solo (correlación cruzada), invierte uno y lo resta del otro. Sin limpieza de
residuos (eso lo haces aparte, p. ej. con un separador tipo Demucs/MDX).

## Dos modos (detectados por el nombre)

| Modo | Detecta | Se invierte | Keeper | Salida |
|---|---|---|---|---|
| **Acapella** | `instrumental` / `inst` | la instrumental | el original | `<original> Aca Invert.wav` |
| **Invert** | `extended` / `ext` | el extended | el radio edit | `<radio edit> Invert.wav` |

En modo Invert el radio edit **no** necesita decir "radio": basta con que el
otro diga "extended". El resultado se nombra según el keeper (el que no se
invierte). La detección usa límites de palabra, así que `Next`/`Sextet` no
disparan "ext".

## Uso

1. Pon los pares en `input/`:
   - **subcarpetas con 2 archivos cada una** (recomendado para lotes: 6
     archivos en 3 subcarpetas = 3 pares), **o**
   - 2 archivos sueltos en la raíz (se emparejan por nombre).
2. Corre `InvertTool` (o `python app.py`).
3. Elige **1) Procesar**. El resultado sale en `output/`.

## Defaults

| Ajuste | Valor | Nota |
|---|---|---|
| `gain_mode` | `unity` | g = 1.0: solo alinear + invertir |
| `input_db` | `-6.0` | headroom a la entrada (anti-clip, como en Audacity) |
| `output_subtype` | `PCM_24` | 24-bit |
| `samplerate` | `lowest` | nunca sube de rate; iguala al más bajo |
| `drift` | `auto` | detecta y corrige deriva de tempo/reloj |

Otros `gain_mode`: `peak` (cuadra el techo de master por pico dBFS),
`fixed` (dB manual con `fixed_db`), `auto` (mínimos cuadrados por energía —
**no recomendado**, baja la instrumental de más).

### Auto block-match (instrumental sin máster)

Si la instrumental está en otro estado de procesamiento (p. ej. **sin máster**,
mucho más baja), unity no cancela bien. La tool lo detecta solo: mide la
ganancia óptima global y si se aleja más de `blockmatch_gain_db` (6 dB por
defecto, conservador) de la unidad, usa **block-match** — inversión por bloques
con ganancia y micro-desfase adaptativos que matchea nivel/EQ y sigue la deriva.
Una instrumental solo un poco más baja **no** lo dispara. Se apaga con
`auto_blockmatch: false`.

Se configura desde el menú (opción 2) o editando `config.json`.

### Corrección de deriva (desfase de tempo / sample-clock)

A veces los dos archivos se renderizaron a velocidades **un pelín distintas**
(un bounce en tiempo real vs offline, un SRC con otro reloj, una transferencia
analógica…). Entonces el desfase **no es fijo: crece de forma lineal** a lo largo
del track. Si alineas el inicio, el final se sale, y al revés. Es muy común con
instrumentales oficiales que vienen aparte.

`drift: auto` (default) lo maneja solo, por par, sin que midas nada:

1. Mide el mapeo afín `inst_idx = alpha·orig_idx + beta` por correlación **en la
   banda de graves** (kick/bajo están iguales en la mezcla y en la instru, así
   que cuadra aunque uno tenga voz), con **ajuste robusto** (rechaza outliers /
   beat-hops).
2. **Decide solo**:
   - deriva significativa **y lineal** (residual bajo) → la corrige;
   - despreciable (< ~4 muestras en todo el track) → offset fijo normal;
   - residual alto (no es una recta → son ediciones por secciones, no tempo) o
     fuera de rango de reloj → no fuerza nada.
3. Corrige con **retardo fraccionario por bloques** (FFT phase-ramp, banda
   completa, precisión sub-muestra): re-muestrea la instru a la velocidad exacta
   del original y la resta. Cancela parejo de punta a punta.

`alpha-1` se expresa en **ppm**; un clock drift típico es de pocas ppm. La tool
te imprime cuánta deriva detectó y si la corrigió. Solo actúa en `gain_mode:
unity` (el default); con `off` se ignora y con `on` se fuerza aunque sea chica.

## Sample rate distinto entre los dos archivos

No se puede cancelar fase entre rates distintos (rejillas de tiempo distintas).
La herramienta resamplea (polyphase, alta calidad) al rate más bajo por defecto,
así nunca sube de rate. La cancelación solo ocurre en la banda compartida.

## Build (.exe Windows)

Automático vía GitHub Actions (PyInstaller en runner Windows). Empuja un tag
`v*` y el `.exe` queda en el Release; o corre el workflow a mano
(`workflow_dispatch`) y bájalo de los artifacts.

```
git tag v1.0.0 && git push origin v1.0.0
```

## Local

```
pip install -r requirements.txt
python app.py
```
