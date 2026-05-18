# CLAUDE.md — ArcBOX-AX

App web Flask para gestionar ROMs del Xbox Series S vía FTP. Corre en `http://localhost:5000`.
Repo: https://github.com/Arcbox-ax/arcbox-ax

## Archivos

```
kalita-app/
├── app.py               — backend Flask: rutas API, FTP, descarga, thumb scraping
├── deploy.sh            — script local (en .gitignore): commit + push + restart
├── templates/
│   └── index.html       — frontend SPA completo (CSS + HTML + JS en un archivo)
└── .gitignore
```

No hay requirements.txt. Dependencias: `flask`, stdlib (`ftplib`, `threading`, `queue`, `urllib`).

## Iniciar la app

```bash
# Script local (commit + push + restart):
~/xbox/kalita-app/deploy.sh "mensaje de commit"

# Solo restart (Flask debug=False, requiere restart para ver cambios en templates):
fuser -k 5000/tcp && cd ~/xbox/kalita-app && nohup python3 app.py > /tmp/kalita-app.log 2>&1 &
```

## Configuración (app.py, líneas ~13-24)

| Variable | Valor | Descripción |
|----------|-------|-------------|
| `XBOX_IP` | `192.168.1.51` | IP del Xbox Series S |
| `XBOX_PORT` | `21` | Puerto FTP |
| `BASE_DIR` | `~/roms-backup` | ROMs locales |
| `CACHE_DIR` | `~/roms-backup/.cache` | Cache de JSONLs |
| `THUMB_DIR` | `~/roms-backup/.thumbs` | Carátulas descargadas |
| `JSONL_BASE` | GitHub Arley4d/roms | Fuente de metadatos de ROMs |

## Arquitectura backend (app.py)

### Rutas API

| Ruta | Método | Descripción |
|------|--------|-------------|
| `/` | GET | Sirve el frontend |
| `/api/sistemas` | GET | Lista todos los sistemas con conteo local |
| `/api/sistema/<id>` | GET | Juegos de un sistema (soporta `?q=busqueda`) |
| `/api/search` | GET | Búsqueda global en todos los sistemas cacheados |
| `/api/index-all` | GET | Pre-carga todos los JSONLs en caché |
| `/api/download` | POST | Encola descarga de un ROM |
| `/api/download-all` | POST | Encola todos los ROMs faltantes de un sistema |
| `/api/status` | GET | Estado Xbox + cola de descargas |
| `/api/events` | GET | SSE — progreso en tiempo real |
| `/api/thumb/<sistema>/<rom>` | GET | Carátula del juego |
| `/api/thumb-scrape/<sistema>` | POST | Descarga y sube carátulas al Xbox |

### Estado global

```python
download_queue  # queue.Queue — jobs pendientes
download_status # dict job_id → estado
sse_clients     # lista de colas SSE activas
jsonl_cache     # sistema → lista de entries
ftp_cache       # ftp_dir → set de filenames
```

### Flujo de descarga
1. `POST /api/download` → encola job en `download_queue`
2. Worker thread (`download_worker`) procesa jobs
3. Descarga ROM con resume (`Range` header), guarda en `~/roms-backup/<sistema>/`
4. Sube por FTP al Xbox en `/DRIVES/E/ROMs/<sistema>/`
5. Progreso via SSE a todos los clientes conectados

### Patrones importantes
- `SISTEMAS_META` — dict con label, ruta FTP e ícono de cada sistema
- `LIBRETRO_SYSTEM` — mapeo sistema → nombre repo de carátulas libretro-thumbnails
- `JSONL_OVERRIDE` — `{"arcade": "fbneo"}` (arcade.jsonl bloqueado, usa fbneo.jsonl)
- `MAME_CURATED` — lista curada de ~80 ROMs MAME clásicos

## Arquitectura frontend (index.html)

SPA vanilla JS, sin frameworks. Todo el CSS, HTML y JS en un solo archivo.

### Estructura JS

```
GRUPOS[]          — grupos por marca con logos SVG (Nintendo, Sega, Sony, etc.)
SYSTEM_ICONS{}    — mapeo sistema ID → nombre icono KyleBing (40+ sistemas)
sysIconUrl(id)    — URL raw GitHub de KyleBing/retro-game-console-icons (264w@2x)
state{}           — currentSistema, games, filter, search, jobs, xboxOnline, openGroups
```

`state.openGroups` inicia como `new Set()` — todos los grupos del sidebar contraídos al inicio.

### Home — "Mis ROMs"

Layout Netflix: filas por sistema con scroll horizontal de miniaturas.

- **❤️ Favoritos** — sección arriba si hay ROMs marcados con corazón
- **Top sistemas** — top 10 por `local_count`, cada fila carga sus juegos via `loadRowGames(id)`
- Iconos de consola desde `SYSTEM_ICONS` → raw.githubusercontent.com (KyleBing/retro-game-console-icons)
- Cada miniatura: imagen `/api/thumb/<sistema>/<name>` + botón corazón + nombre truncado

### Favoritos de ROMs

```js
localStorage key: 'arcbox_favorites'  // array de {sistema, filename, name}
getRomFavs()                          // lee y filtra solo objetos válidos
isRomFav(sistema, filename)
toggleRomFav(sistema, filename, name, heartEl)
handleHeartClick(event, el)           // lee data attrs del .game-mini-card padre
```

### Popup hover

- Elemento único `#rom-popup` en el DOM (position:fixed, z-index:500)
- Aparece 300ms después del mouseenter sobre miniatura o thumbnail de tabla
- Muestra: imagen grande + nombre completo + sistema + tamaño + botones ⬇/📤
- `showRomPopup(event, el)` lee `el.dataset.*` para los datos
- `hideRomPopup()` con delay 120ms (permite mover el mouse al popup sin que se cierre)
- `downloadFromPopup(upload)` usa `popup.dataset.sistema/filename`

### Funciones principales

| Función | Descripción |
|---------|-------------|
| `loadSistemas()` | Carga sidebar + home |
| `loadSistema(id)` | Carga vista de juegos de un sistema |
| `renderSidebar()` | Grupos colapsables con emoji del sistema |
| `renderHome()` | async — sección favoritos + filas Netflix |
| `loadRowGames(sysId)` | async — carga juegos locales de una fila |
| `renderGames(data)` | Tabla de juegos con estado local/Xbox |
| `renderRows(games, sistema)` | Filas de tabla con popup hover y botones |
| `download(sistema, filename, upload)` | Inicia descarga/subida de un ROM |
| `downloadAll(sistema, upload)` | Descarga todos los faltantes |
| `toggleSidebar()` | Abre/cierra sidebar en mobile |
| `onGlobalSearch(q)` | Búsqueda global con debounce |

### Botones en tabla de juegos

- **⬇ Local** — azul (`--accent2`), llama `download(..., false)`. Si ya local: `✓ Local` disabled.
- **📤 Xbox** — naranja (`--accent`), llama `download(..., true)`. Si ya en Xbox: `✓ Xbox` disabled.

### Sidebar grupos (GRUPOS array)

Cada grupo tiene `id`, `label`, `sistemas[]` y `logo` (SVG inline).
Grupos: Nintendo, Sega, Atari, SNK, Arcade, Sony, Commodore, NEC, Pioneros, Bandai, Sinclair, MSX, Clásicos PC.
Cada sistema muestra su emoji (`s.icon`) de 18px a la izquierda del nombre.

### Helpers JS

```js
esc(s)       // HTML-escapa para uso en atributos (& → &amp;, " → &quot;)
escJs(s)     // escapa para strings inline en onclick (\\ y ')
fmtSize(b)   // bytes → KB/MB/GB
fmtEta(s)    // segundos → m s / h m
showToast(msg)
```

## Logo ArcBOX-AX

```
ArcBOX   ← "Arc" gris #8888aa + "BOX" naranja #e6a23c, font-size 15
  AX     ← centrado en unión c/B, azul #5b8dee, font-size 9, letter-spacing 5
```

SVG inline en `<h1>`, viewBox 80×36, fondo `#0f0f13`, borde `#2e2e3e`.

## Colores del tema

```css
--bg: #0f0f13       /* fondo principal */
--bg2: #1a1a22      /* header / sidebar */
--bg3: #22222e      /* cards / inputs */
--border: #2e2e3e
--accent: #e6a23c   /* naranja — acción principal */
--accent2: #5b8dee  /* azul — acción secundaria */
--green: #4ade80
--red: #f87171
--yellow: #fbbf24
--text: #e2e2f0
--text2: #8888aa    /* texto secundario */
```

## Responsividad mobile

- Breakpoint principal: `768px`, secundario: `420px`
- Sidebar como drawer — botón `☰` en header, overlay oscuro al abrirse
- Se cierra automáticamente al seleccionar un sistema
- Búsqueda cae a segunda fila full-width en mobile
- Tabla oculta columnas de imagen y tamaño en mobile

## Convenciones

- Al agregar un sistema nuevo: añadir en `SISTEMAS_META` (app.py), en `GRUPOS` (index.html) y en `SYSTEM_ICONS` (index.html) si tiene icono KyleBing
- CSS en `index.html` organizado por sección: header → layout → sidebar → home rows → content → table → queue → mobile → popup
- SSE (`/api/events`) maneja eventos: `progress`, `done`, `queued`, `thumb_progress`, `thumb_done`, `index_progress`, `index_done`
- `data-*` attributes en `.game-mini-card` y wrapper de thumb en tabla: `sistema`, `name`, `filename`, `size`, `local`, `xbox`
- Usar siempre `esc()` para HTML attributes e `escJs()` para inline JS cuando se insertan strings de usuario
