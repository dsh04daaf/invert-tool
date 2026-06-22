# InvertTool

Inversión de fase por lotes para extraer acapellas. Dejas el par
**original + instrumental** en una carpeta, encuentra el offset solo
(correlación cruzada), invierte la instrumental y la resta:

```
acapella = original − instrumental
```

La instrumental es **siempre** la que se invierte. Sin limpieza de residuos
(eso lo haces aparte si quieres, p. ej. con un separador tipo Demucs/MDX).

## Uso

1. Pon los pares en `input/`:
   - dos archivos sueltos, uno con `instrumental` / `inst` en el nombre y el otro
     el original, **o**
   - una subcarpeta con exactamente 2 archivos.
2. Corre `InvertTool` (o `python app.py`).
3. Elige **1) Procesar**. El resultado sale en `output/` como
   `<nombre> - acapella.wav`.

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
