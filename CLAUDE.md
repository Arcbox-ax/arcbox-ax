# CLAUDE.md — ArcBOX-AX

App web Flask para gestionar ROMs del Xbox Series S vía FTP. Corre en `http://localhost:5000`.

## Archivos

```
kalita-app/
├── app.py               — backend Flask: rutas API, FTP, descarga, thumb scraping
├── templates/
│   └── index.html       — frontend SPA completo (CSS + HTML + JS en un archivo)
└── .gitignore
```

No hay requirements.txt. Dependencias: `flask`, stdlib (`ftplib`, `threading`, `queue`, `urllib`).

## Iniciar la app

```bash
python3 app.py
# Si el puerto 5000 está ocupado:
fuser -k 5000/tcp && python3 app.py
# En background:
nohup python3 app.py > /tmp/kalita-app.log 2>&1 &
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

SPA vanilla JS, sin frameworks.

### Estructura JS

```
GRUPOS[]          — grupos por marca con logos SVG (Nintendo, Sega, Sony, etc.)
SISTEMAS_META{}   — (viene del backend via /api/sistemas)
state{}           — currentSistema, games, filter, search, jobs, xboxOnline, openGroups
```

### Funciones principales

| Función | Descripción |
|---------|-------------|
| `loadSistemas()` | Carga sidebar + home con brand cards |
| `loadSistema(id)` | Carga juegos de un sistema |
| `renderSidebar()` | Renderiza grupos colapsables |
| `renderHome()` | Renderiza brand cards en el contenido |
| `renderGames(data)` | Tabla de juegos con estado local/Xbox |
| `download(sistema, filename, upload)` | Inicia descarga de un ROM |
| `downloadAll(sistema, upload)` | Descarga todos los faltantes |
| `toggleSidebar()` | Abre/cierra sidebar en mobile |
| `onGlobalSearch(q)` | Búsqueda global con debounce |
| `connectSSE()` | Conecta a `/api/events` para progreso en tiempo real |

### Sidebar grupos (GRUPOS array)
Cada grupo tiene `id`, `label`, `sistemas[]` y `logo` (SVG inline).
Grupos definidos: Nintendo, Sega, Atari, SNK, Arcade, Sony, Commodore, NEC, Pioneros, Bandai, Sinclair, MSX, Clásicos PC.

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

- Al agregar un sistema nuevo: añadir en `SISTEMAS_META` (app.py) y en el grupo correspondiente dentro de `GRUPOS` (index.html)
- CSS en `index.html` usa sentinel comments implícitos por sección — mantener el orden: header → layout → sidebar → content → table → queue → mobile
- SSE se reconecta automáticamente si se pierde la conexión
