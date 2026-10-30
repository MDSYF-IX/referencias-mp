# referencias-mp

Licitaciones de obras adjudicadas en Mercado Público (ChileCompra), como referencia de costo
para la pestaña **Mercado Público** del buscador de referencias de PAT-Pro SNI
(formulador-sni.vercel.app).

Fase inicial: Región de La Araucanía, tipos LR, I2, O1 y O2. Una fila por licitación.

## Archivos publicados (GitHub Pages, rama `gh-pages`)

| Archivo | Contenido |
|---|---|
| `mp/indice.json` | fecha de actualización, tipos, regiones y n por año |
| `mp/uf.json` | fecha → valor UF |
| `mp/<region>/<año>.json` | licitaciones de la región adjudicadas ese año, formato `{"campos": [...], "filas": [[...]]}` |

Campos: `cod, nom, org, reg, com, tipo, fpub, fadj, mon, est, adj, adj_uf, ofe, prov, tipol, bip, obs`.
`adj` = Σ montos de las líneas adjudicadas, en la moneda `mon` (CLP o CLF = UF), tal como viene
(puede incluir o no IVA según las bases). `obs` marca montos no confiables.

## Filtros (`config/filtros.json`)

- `tipos`: tipos de licitación incluidos (el tipo es el sufijo del código: `1234-56-LR26` → LR).
- `palabras_no_obras`: si el nombre contiene una de estas, nunca es obra (adquisición, maquinaria, AIF/ATIF, diseño, estudio, asesoría…).
- `tipos_siempre_obras`: O1 y O2 entran siempre.
- LR / I2: entran si la bandera `Obras` de ChileCompra es 2, o si el nombre tiene una de
  `palabras_obras` y ninguna de `palabras_excluir_si_solo_palabras` (servicio, suministro, mantención).

Tipologías por palabras clave: `config/tipologias.json`.

## Proceso (`.github/workflows/actualizar.yml`)

- **Diario 06:30**: `scripts/diaria.py` (API de Mercado Público, secreto `MP_TICKET`; sin ticket no hace nada).
- **Domingos**: `scripts/carga.py --ultimos 3` concilia con los datos abiertos.
- **A pedido** (Actions → Run workflow → `inicial`): carga de los últimos 60 meses.

Correr dos veces no duplica filas (clave: código de la licitación).

Secretos: `MP_TICKET` (API Mercado Público), `CMF_API_KEY` (opcional, respaldo de la UF si
mindicador.cl no responde). Nunca se escriben en el repositorio ni en el frontend.

## Local

```
python scripts/carga.py --publico public --meses 2025-9 2025-10 --zips zips
MP_TICKET=... python scripts/diaria.py --publico public --muestra 1057956-2-LR25
```
