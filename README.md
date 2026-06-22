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
