#!/usr/bin/env python3
"""
ArcBOX-AX — Interfaz web para gestionar ROMs del Xbox
Corre en http://localhost:5000
"""

import json, ftplib, threading, time, urllib.request, urllib.error, queue, os, re
from pathlib import Path
from flask import Flask, render_template, jsonify, request, Response, stream_with_context, send_file

app = Flask(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────

XBOX_IP   = "192.168.1.51"
XBOX_PORT = 21
XBOX_USER = "ftp"
XBOX_PASS = "ftp"
BASE_DIR  = Path.home() / "roms-backup"
JSONL_BASE   = "https://raw.githubusercontent.com/Arley4d/roms/main/{}.jsonl"
MAME_URL_TPL = "https://archive.org/download/mame-roms-split/MAME%20ROMs%20%28split%29/{}.zip"
CACHE_DIR    = BASE_DIR / ".cache"
THUMB_DIR    = BASE_DIR / ".thumbs"
THUMB_BASE   = "https://raw.githubusercontent.com/libretro-thumbnails/{system}/master/Named_Boxarts/{game}.png"

LIBRETRO_SYSTEM = {
    "scummvm":      "ScummVM",
    "psx":          "Sony - PlayStation",
    "arcade":       "MAME",
    "neogeo":       "SNK - Neo Geo",
    "fbneo":        "FBNeo - Arcade Games",
    "snes":         "Nintendo - Super Nintendo Entertainment System",
    "n64":          "Nintendo - Nintendo 64",
    "gba":          "Nintendo - Game Boy Advance",
    "gb":           "Nintendo - Game Boy",
    "gbc":          "Nintendo - Game Boy Color",
    "megadrive":    "Sega - Mega Drive - Genesis",
    "mastersystem": "Sega - Master System - Mark III",
    "nes":          "Nintendo - Nintendo Entertainment System",
    "nds":          "Nintendo - DS",
    "gamegear":     "Sega - Game Gear",
    "ngpc":         "SNK - Neo Geo Pocket Color",
    "ngp":          "SNK - Neo Geo Pocket",
    "sega32x":      "Sega - 32X",
    "pce":          "NEC - PC Engine - TurboGrafx 16",
    "atari2600":    "Atari - 2600",
    "jaguar":       "Atari - Jaguar",
    "lynx":         "Atari - Lynx",
    "virtualboy":   "Nintendo - Virtual Boy",
    "dreamcast":    "Sega - Dreamcast",
    "saturn":       "Sega - Saturn",
    "msx1":         "Microsoft - MSX",
    "wonderswan":   "Bandai - WonderSwan Color",
    "zxspectrum":   "Sinclair - ZX Spectrum +3",
    "amstrad":      "Amstrad - CPC",
    "pc98":         "NEC - PC-98",
    "pcfx":         "NEC - PC-FX",
    "c64":          "Commodore - 64",
    "ps2":          "Sony - PlayStation 2",
    "psp":          "Sony - PlayStation Portable",
    "gamecube":     "Nintendo - GameCube",
    "wii":          "Nintendo - Wii",
    "3ds":          "Nintendo - Nintendo 3DS",
    "fds":          "Nintendo - Family Computer Disk System",
    "segacd":       "Sega - Mega-CD",
    "neogeocd":     "SNK - Neo Geo CD",
    "pcecd":        "NEC - PC Engine CD - TurboGrafx-CD",
    "sg1000":       "Sega - SG-1000",
    "naomi":        "Sega - NAOMI",
    "atari5200":    "Atari - 5200",
    "atari7800":    "Atari - 7800",
    "atarist":      "Atari - ST",
    "atari800":     "Atari - 8-bit",
    "amiga":        "Commodore - Amiga",
    "amigacd32":    "Commodore - Amiga CD32",
    "vic20":        "Commodore - VIC-20",
    "colecovision": "Coleco - ColecoVision",
    "intellivision":"Mattel - Intellivision",
    "vectrex":      "GCE - Vectrex",
    "odyssey2":     "Magnavox - Odyssey2",
    "channelf":     "Fairchild - Channel F",
    "supervision":  "Watara - Supervision",
    "3do":          "3DO - 3DO",
    "x68000":       "Sharp - X68000",
    "dos":          "DOS",
    "apple2":       "Apple - II",
    "apple2gs":     "Apple - IIGS",
    "msx2":         "Microsoft - MSX2",
    "pokemini":     "Nintendo - Pokemon Mini",
    "satellaview":  "Nintendo - Satellaview",
}

def thumb_game_name(rom_name):
    name = Path(rom_name).stem if '.' in rom_name else rom_name
    return re.sub(r'[\\/:*?"<>|#]', '_', name)

_STOP_WORDS = {'of', 'the', 'and', 'a', 'an', 'in', 'to', 'for', 'or', 'at', 'by', 'on'}

def _normalize_title(s):
    words = s.split()
    return ' '.join(w if i == 0 else (w.lower() if w.lower() in _STOP_WORDS else w)
                    for i, w in enumerate(words))

def _fetch_thumb_url(sys_repo, game, timeout=10):
    def _try(g):
        game_enc = urllib.request.quote(g, safe='()')
        url = THUMB_BASE.format(system=sys_repo, game=game_enc)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                ct   = r.headers.get("Content-Type", "")
                data = r.read()
            if "image" in ct and len(data) > 500:
                return data
            alias = data.decode("utf-8", errors="ignore").strip()
            if alias.endswith(".png"):
                return _try(Path(alias).stem)
        except Exception:
            pass
        return None

    data = _try(game)
    if data: return data
    base = re.sub(r'\s*\(.*', '', game).strip()
    if base != game:
        data = _try(base)
        if data: return data
    norm = _normalize_title(base)
    if norm != base:
        return _try(norm)
    return None

def get_or_fetch_thumb(sistema, rom_name):
    libretro = LIBRETRO_SYSTEM.get(sistema)
    if not libretro:
        return None
    game = thumb_game_name(rom_name)
    dest = THUMB_DIR / sistema / (game + ".png")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return dest
    sys_repo = libretro.replace(' ', '_')
    try:
        data = _fetch_thumb_url(sys_repo, game)
        if data:
            dest.write_bytes(data)
            return dest
    except Exception:
        pass
    return None

SISTEMAS_META = {
    "scummvm":      {"label": "ScummVM (PC Clásico)", "ftp": "/DRIVES/E/ROMs/scummvm",      "icon": "💻"},
    "psx":          {"label": "PlayStation 1",        "ftp": "/DRIVES/E/ROMs/psx",           "icon": "🎮"},
    "arcade":       {"label": "Arcade (FBNeo)",        "ftp": "/DRIVES/E/ROMs/arcade",        "icon": "🕹️"},
    "mame":         {"label": "MAME",                 "ftp": "/DRIVES/E/ROMs/arcade",        "icon": "👾", "mame": True},
    "neogeo":       {"label": "Neo Geo",              "ftp": "/DRIVES/E/ROMs/arcade",        "icon": "🥊"},
    "snes":         {"label": "Super Nintendo",       "ftp": "/DRIVES/E/ROMs/snes",          "icon": "🍄"},
    "n64":          {"label": "Nintendo 64",          "ftp": "/DRIVES/E/ROMs/n64",           "icon": "🎯"},
    "gba":          {"label": "Game Boy Advance",     "ftp": "/DRIVES/E/ROMs/gba",           "icon": "📱"},
    "gb":           {"label": "Game Boy",             "ftp": "/DRIVES/E/ROMs/gameboy",       "icon": "🟩"},
    "gbc":          {"label": "Game Boy Color",       "ftp": "/DRIVES/E/ROMs/gbc",           "icon": "🌈"},
    "megadrive":    {"label": "Mega Drive / Genesis", "ftp": "/DRIVES/E/ROMs/genesis",       "icon": "⚡"},
    "mastersystem": {"label": "Master System",        "ftp": "/DRIVES/E/ROMs/mastersystem",  "icon": "🔵"},
    "nes":          {"label": "Nintendo NES",         "ftp": "/DRIVES/E/ROMs/nes",           "icon": "🔴"},
    "nds":          {"label": "Nintendo DS",          "ftp": "/DRIVES/E/ROMs/nds",           "icon": "📟"},
    "gamegear":     {"label": "Game Gear",            "ftp": "/DRIVES/E/ROMs/gamegear",      "icon": "🎲"},
    "ngpc":         {"label": "Neo Geo Pocket Color", "ftp": "/DRIVES/E/ROMs/ngpc",          "icon": "🟠"},
    "sega32x":      {"label": "Sega 32X",             "ftp": "/DRIVES/E/ROMs/sega32x",       "icon": "🔷"},
    "pce":          {"label": "PC Engine",            "ftp": "/DRIVES/E/ROMs/pce",           "icon": "🟡"},
    "atari2600":    {"label": "Atari 2600",           "ftp": "/DRIVES/E/ROMs/atari2600",     "icon": "🔲"},
    "jaguar":       {"label": "Atari Jaguar",         "ftp": "/DRIVES/E/ROMs/jaguar",        "icon": "🐆"},
    "lynx":         {"label": "Atari Lynx",           "ftp": "/DRIVES/E/ROMs/lynx",          "icon": "🟦"},
    "virtualboy":   {"label": "Virtual Boy",          "ftp": "/DRIVES/E/ROMs/virtualboy",    "icon": "🔴"},
    "dreamcast":    {"label": "Dreamcast",            "ftp": "/DRIVES/E/ROMs/dreamcast",     "icon": "🌀"},
    "saturn":       {"label": "Sega Saturn",          "ftp": "/DRIVES/E/ROMs/saturn",        "icon": "💫"},
    "msx1":         {"label": "MSX",                  "ftp": "/DRIVES/E/ROMs/msx",           "icon": "🖥️"},
    "wonderswan":   {"label": "WonderSwan Color",     "ftp": "/DRIVES/E/ROMs/wonderswan",    "icon": "🦢"},
    "zxspectrum":   {"label": "ZX Spectrum",          "ftp": "/DRIVES/E/ROMs/zxspectrum",    "icon": "🖤"},
    "amstrad":      {"label": "Amstrad CPC",           "ftp": "/DRIVES/E/ROMs/amstrad",       "icon": "⌨️"},
    "pc98":         {"label": "NEC PC-98",             "ftp": "/DRIVES/E/ROMs/pc98",          "icon": "🖥️"},
    "pcfx":         {"label": "PC-FX",                 "ftp": "/DRIVES/E/ROMs/pcfx",          "icon": "📼"},
    "c64":          {"label": "Commodore 64",          "ftp": "/DRIVES/E/ROMs/c64",           "icon": "🍞"},
    "ps2":          {"label": "PlayStation 2",         "ftp": "/DRIVES/E/ROMs/ps2",           "icon": "💿"},
    "psp":          {"label": "PlayStation Portable",  "ftp": "/DRIVES/E/ROMs/psp",           "icon": "📱"},
    "gamecube":     {"label": "GameCube",              "ftp": "/DRIVES/E/ROMs/gamecube",      "icon": "🟣"},
    "wii":          {"label": "Nintendo Wii",          "ftp": "/DRIVES/E/ROMs/wii",           "icon": "🎯"},
    "3ds":          {"label": "Nintendo 3DS",          "ftp": "/DRIVES/E/ROMs/3ds",           "icon": "📺"},
    "fds":          {"label": "Famicom Disk System",   "ftp": "/DRIVES/E/ROMs/fds",           "icon": "💾"},
    "segacd":       {"label": "Sega CD / Mega CD",     "ftp": "/DRIVES/E/ROMs/segacd",        "icon": "💿"},
    "neogeocd":     {"label": "Neo Geo CD",            "ftp": "/DRIVES/E/ROMs/neogeocd",      "icon": "💿"},
    "pcecd":        {"label": "PC Engine CD",          "ftp": "/DRIVES/E/ROMs/pcecd",         "icon": "💿"},
    "sg1000":       {"label": "Sega SG-1000",          "ftp": "/DRIVES/E/ROMs/sg1000",        "icon": "🎮"},
    "naomi":        {"label": "Sega NAOMI",            "ftp": "/DRIVES/E/ROMs/naomi",         "icon": "🕹️"},
    "atari5200":    {"label": "Atari 5200",            "ftp": "/DRIVES/E/ROMs/atari5200",     "icon": "🕹️"},
    "atari7800":    {"label": "Atari 7800",            "ftp": "/DRIVES/E/ROMs/atari7800",     "icon": "🎮"},
    "atarist":      {"label": "Atari ST",              "ftp": "/DRIVES/E/ROMs/atarist",       "icon": "🖱️"},
    "atari800":     {"label": "Atari 800",             "ftp": "/DRIVES/E/ROMs/atari800",      "icon": "⌨️"},
    "amiga":        {"label": "Amiga",                 "ftp": "/DRIVES/E/ROMs/amiga",         "icon": "🖥️"},
    "amigacd32":    {"label": "Amiga CD32",            "ftp": "/DRIVES/E/ROMs/amigacd32",     "icon": "💿"},
    "vic20":        {"label": "VIC-20",                "ftp": "/DRIVES/E/ROMs/vic20",         "icon": "🖥️"},
    "colecovision": {"label": "ColecoVision",          "ftp": "/DRIVES/E/ROMs/colecovision",  "icon": "🎮"},
    "intellivision":{"label": "Intellivision",         "ftp": "/DRIVES/E/ROMs/intellivision", "icon": "🕹️"},
    "vectrex":      {"label": "Vectrex",               "ftp": "/DRIVES/E/ROMs/vectrex",       "icon": "📺"},
    "odyssey2":     {"label": "Odyssey 2",             "ftp": "/DRIVES/E/ROMs/odyssey2",      "icon": "🎮"},
    "channelf":     {"label": "Channel F",             "ftp": "/DRIVES/E/ROMs/channelf",      "icon": "📺"},
    "supervision":  {"label": "Supervision",           "ftp": "/DRIVES/E/ROMs/supervision",   "icon": "📱"},
    "3do":          {"label": "3DO",                   "ftp": "/DRIVES/E/ROMs/3do",           "icon": "💿"},
    "x68000":       {"label": "Sharp X68000",          "ftp": "/DRIVES/E/ROMs/x68000",        "icon": "🖥️"},
    "dos":          {"label": "DOS",                   "ftp": "/DRIVES/E/ROMs/dos",           "icon": "💾"},
    "apple2":       {"label": "Apple II",              "ftp": "/DRIVES/E/ROMs/apple2",        "icon": "🍎"},
    "apple2gs":     {"label": "Apple IIGS",            "ftp": "/DRIVES/E/ROMs/apple2gs",      "icon": "🍎"},
    "msx2":         {"label": "MSX2",                  "ftp": "/DRIVES/E/ROMs/msx2",          "icon": "🖥️"},
    "pokemini":     {"label": "Pokémon Mini",          "ftp": "/DRIVES/E/ROMs/pokemini",      "icon": "🟡"},
    "satellaview":  {"label": "Satellaview",           "ftp": "/DRIVES/E/ROMs/satellaview",   "icon": "📡"},
    "ngp":          {"label": "Neo Geo Pocket",        "ftp": "/DRIVES/E/ROMs/ngp",           "icon": "📟"},
}

# ─── Estado global ────────────────────────────────────────────────────────────

download_queue  = queue.Queue()
download_status = {}   # job_id → {name, sistema, progress, speed, eta, state}
sse_clients     = []
jsonl_cache     = {}   # sistema → list of entries
ftp_cache       = {}   # ftp_dir → set of filenames
_ftp_cache_ts   = {}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def fmt_size(b):
    if not b: return "?"
    if b >= 1024**3: return f"{b/1024**3:.1f} GB"
    if b >= 1024**2: return f"{b/1024**2:.1f} MB"
    if b >= 1024:    return f"{b/1024:.1f} KB"
    return f"{b} B"

def get_url(e):
    try: return e["urls"][0]["u"]
    except: return None

def get_size(e):
    if e.get("size_bytes"): return e["size_bytes"]
    try: return e["urls"][0]["size_bytes"]
    except: return 0

def get_ext(e):
    return e.get("ext") or Path(e.get("p", "")).suffix or ""

def sse_broadcast(event, data):
    msg = f"event: {event}\ndata: {json.dumps(data)}\n\n"
    dead = []
    for q in sse_clients:
        try: q.put_nowait(msg)
        except: dead.append(q)
    for q in dead:
        try: sse_clients.remove(q)
        except: pass

# ─── Carga JSONL con caché ─────────────────────────────────────────────────────

# arcade.jsonl usa colección bloqueada (403) → redirigir a fbneo.jsonl
JSONL_OVERRIDE = {"arcade": "fbneo"}

# Lista curada MAME para la app (misma fuente que kalita-xbros.py)
MAME_CURATED = [
    ("Street Fighter 2","sf2"),("SF2 CE","sf2ce"),("SF2 HF","sf2hf"),
    ("Super SF2","ssf2"),("Super SF2 Turbo","ssf2t"),
    ("SF Alpha","sfa"),("SF Alpha 2","sfa2"),("SF Alpha 3","sfa3"),
    ("Marvel vs Capcom","mvsc"),("X-Men vs SF","xmvsf"),
    ("Marvel Super Heroes","msh"),("MSH vs SF","mshvsf"),
    ("Alien vs Predator","avsp"),("Cyberbots","cybots"),
    ("Darkstalkers","dstlk"),("Night Warriors","nwarr"),("Vampire Savior","vsav"),
    ("Final Fight","ffight"),("Final Fight 2","ffight2"),
    ("The Punisher","punisher"),("Knights of the Round","knights"),
    ("Cadillacs and Dinos","dino"),("The Simpsons","simpsons"),
    ("TMNT","tmnt"),("TMNT 2","tmnt2"),
    ("D&D Tower of Doom","dndtower"),("D&D Shadow over Mystara","ddsom"),
    ("Slam Masters","slammast"),("Strider","strider"),("Strider 2","strider2"),
    ("1942","1942"),("1943","1943"),("1943 Kai","1943kai"),("19XX","19xx"),
    ("1944","1944"),("Progear","progear"),("DoDonPachi","ddonpach"),
    ("DonPachi","donpachi"),("ESP Ra.De.","esprade"),("Giga Wing","gigawing"),
    ("Dimahoo","dimahoo"),("Batsugun","batsugun"),("Varth","varth"),
    ("Ghouls n Ghosts","ghouls"),("Gun.Smoke","gunsmoke"),("GnG","gng"),
    ("Contra","contra"),("Super Contra","supercon"),
    ("Gradius","gradius"),("Gradius 2","gradius2"),("Gradius 3","gradius3"),
    ("Life Force","lifefrce"),("X-Men 6P","xmen6p"),
    ("Sunset Riders","sunsetbl"),("Vendetta","vendetta"),
    ("Mortal Kombat","mk"),("MK 2","mk2"),("MK 3","mk3"),("UMK 3","umk3"),
    ("Donkey Kong","dkong"),("DK Jr","dkongjr"),
    ("Pac-Man","pacman"),("Ms. Pac-Man","mspacman"),("Pac-Mania","pacmania"),
    ("Galaga","galaga"),("Galaxian","galaxian"),
    ("Dig Dug","digdug"),("Dig Dug 2","digdug2"),
    ("Frogger","frogger"),("Mr. Do!","mrdo"),("Rastan","rastan"),("Toki","toki"),
    ("Out Run","outrun"),("Space Harrier","sharrier"),
    ("After Burner","aburner"),("Thunder Blade","thndrbld"),
]

def mame_entries_app():
    return [{"n": mid, "ext": ".zip",
             "urls": [{"u": MAME_URL_TPL.format(urllib.request.quote(mid, safe='')), "size_bytes": 0}],
             "type": "file", "_label": label}
            for label, mid in MAME_CURATED]

def cargar_jsonl(sistema):
    if sistema in jsonl_cache:
        return jsonl_cache[sistema]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    jsonl_name = JSONL_OVERRIDE.get(sistema, sistema)
    cache_file = CACHE_DIR / f"{jsonl_name}.jsonl"
    if cache_file.exists() and (time.time() - cache_file.stat().st_mtime) < 3600:
        with open(cache_file) as f:
            lines = f.read().strip().split("\n")
    else:
        url = JSONL_BASE.format(jsonl_name)
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                content = r.read().decode()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                jsonl_cache[sistema] = []
                return []
            raise
        with open(cache_file, "w") as f:
            f.write(content)
        lines = content.strip().split("\n")
    entries = [json.loads(l) for l in lines if l]
    BLOCKED = ["humblecollection", "humblebundle"]
    files = [e for e in entries if e.get("type") == "file" and get_url(e)
             and "torrent" not in (e.get("ext") or "").lower()
             and not any(b in (get_url(e) or "").lower() for b in BLOCKED)]
    jsonl_cache[sistema] = files
    return files

# ─── FTP ──────────────────────────────────────────────────────────────────────

def ftp_connect():
    ftp = ftplib.FTP()
    ftp.connect(XBOX_IP, XBOX_PORT, timeout=10)
    ftp.login(XBOX_USER, XBOX_PASS)
    ftp.set_pasv(True)
    return ftp

def ftp_list_dir(ftp_dir):
    if ftp_dir in ftp_cache and (time.time() - _ftp_cache_ts.get(ftp_dir, 0)) < 60:
        return ftp_cache[ftp_dir]
    try:
        ftp = ftp_connect()
        items = []
        ftp.dir(ftp_dir, items.append)
        ftp.quit()
        names = set()
        for line in items:
            parts = line.split()
            if parts: names.add(parts[-1])
        ftp_cache[ftp_dir] = names
        _ftp_cache_ts[ftp_dir] = time.time()
        return names
    except Exception:
        return set()

def ftp_status():
    try:
        ftp = ftp_connect()
        ftp.quit()
        return True
    except Exception:
        return False

def ftp_upload(local_path, remote_dir, size_bytes, job_id):
    remote = f"{remote_dir}/{local_path.name}"
    ftp = None
    t0 = time.time()
    enviado = 0

    try:
        ftp = ftp_connect()
        with open(local_path, "rb") as f:
            def callback(data):
                nonlocal enviado
                enviado += len(data)
                elapsed = time.time() - t0
                vel = enviado / elapsed if elapsed > 0 else 0
                eta = (size_bytes - enviado) / vel if vel > 0 and size_bytes > 0 else -1
                pct = int(enviado / size_bytes * 100) if size_bytes > 0 else 0
                download_status[job_id].update({
                    "state": "uploading",
                    "progress": pct,
                    "speed": int(vel),
                    "eta": int(eta),
                    "transferred": enviado,
                })
                sse_broadcast("progress", {"job_id": job_id, **download_status[job_id]})
            ftp.storbinary(f"STOR {remote}", f, callback=callback)
        ftp_cache.pop(remote_dir, None)
        return True
    except Exception as ex:
        download_status[job_id]["error"] = str(ex)
        return False
    finally:
        try:
            if ftp: ftp.quit()
        except Exception: pass

# ─── Worker de descarga ────────────────────────────────────────────────────────

def download_worker():
    while True:
        job = download_queue.get()
        job_id = job["job_id"]
        try:
            _process_job(job)
        except Exception as ex:
            download_status[job_id].update({"state": "error", "error": str(ex)})
            sse_broadcast("progress", {"job_id": job_id, **download_status[job_id]})
        finally:
            download_queue.task_done()

def _process_job(job):
    job_id   = job["job_id"]
    sistema  = job["sistema"]
    entry    = job["entry"]
    ftp_dir  = job["ftp_dir"]
    upload   = job.get("upload", True)

    nombre   = entry["n"] + get_ext(entry)
    url      = get_url(entry)
    sz       = get_size(entry)
    local_dir = BASE_DIR / sistema
    local_dir.mkdir(parents=True, exist_ok=True)
    dest = local_dir / nombre
    tmp  = dest.with_suffix(".tmp")

    download_status[job_id].update({"state": "downloading", "filename": nombre, "total": sz})
    sse_broadcast("progress", {"job_id": job_id, **download_status[job_id]})

    # Saltar si ya existe completo
    if dest.exists() and (sz == 0 or dest.stat().st_size == sz):
        download_status[job_id].update({"state": "uploading", "progress": 0})
        sse_broadcast("progress", {"job_id": job_id, **download_status[job_id]})
    else:
        # Descarga con resume
        offset = tmp.stat().st_size if tmp.exists() else 0
        t0 = time.time()
        descargado = offset
        velocidades = []

        headers = {"User-Agent": "Mozilla/5.0"}
        if offset: headers["Range"] = f"bytes={offset}-"

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as r, \
             open(tmp, "ab" if offset else "wb") as f:
            while True:
                chunk = r.read(512 * 1024)
                if not chunk: break
                f.write(chunk)
                descargado += len(chunk)
                elapsed = time.time() - t0
                if elapsed > 0:
                    vel = (descargado - offset) / elapsed
                    velocidades.append(vel)
                    if len(velocidades) > 10: velocidades.pop(0)
                    vel_p = sum(velocidades) / len(velocidades)
                    eta = (sz - descargado) / vel_p if vel_p > 0 and sz > 0 else -1
                    pct = int(descargado / sz * 100) if sz > 0 else 0
                    download_status[job_id].update({
                        "progress": pct, "speed": int(vel_p),
                        "eta": int(eta), "transferred": descargado,
                    })
                    sse_broadcast("progress", {"job_id": job_id, **download_status[job_id]})
        tmp.rename(dest)

    # FTP upload
    if upload:
        download_status[job_id].update({"state": "uploading", "progress": 0, "transferred": 0})
        sse_broadcast("progress", {"job_id": job_id, **download_status[job_id]})
        ftp_upload(dest, ftp_dir, sz, job_id)

    download_status[job_id].update({"state": "done", "progress": 100})
    sse_broadcast("progress", {"job_id": job_id, **download_status[job_id]})
    sse_broadcast("done", {"job_id": job_id, "filename": nombre, "sistema": sistema})

# Iniciar worker
threading.Thread(target=download_worker, daemon=True).start()

# ─── Rutas API ────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/sistemas")
def api_sistemas():
    result = []
    for key, meta in SISTEMAS_META.items():
        local_count = len(list((BASE_DIR / key).glob("*"))) if (BASE_DIR / key).exists() else 0
        result.append({
            "id": key,
            "label": meta["label"],
            "icon": meta["icon"],
            "ftp": meta["ftp"],
            "local_count": local_count,
        })
    return jsonify(result)

@app.route("/api/sistema/<sistema>")
def api_sistema(sistema):
    if sistema not in SISTEMAS_META:
        return jsonify({"error": "Sistema no encontrado"}), 404

    meta = SISTEMAS_META[sistema]
    if meta.get("mame"):
        entries = mame_entries_app()
        if sistema not in jsonl_cache:
            jsonl_cache[sistema] = entries
    else:
        try:
            entries = cargar_jsonl(sistema)
        except Exception as ex:
            return jsonify({"error": str(ex)}), 500

    ftp_dir = meta["ftp"]

    # Estado local
    local_files = set()
    local_path = BASE_DIR / sistema
    if local_path.exists():
        local_files = {f.name for f in local_path.iterdir()}

    # Estado Xbox
    xbox_files = ftp_list_dir(ftp_dir)

    search = request.args.get("q", "").lower()

    games = []
    for e in entries:
        nombre = e["n"] + get_ext(e)
        if search and search not in e["n"].lower():
            continue
        sz = get_size(e)
        local = nombre in local_files
        xbox  = nombre in xbox_files
        games.append({
            "name": e["n"],
            "filename": nombre,
            "size": sz,
            "size_fmt": fmt_size(sz),
            "url": get_url(e),
            "local": local,
            "xbox": xbox,
        })

    total_size = sum(g["size"] for g in games)
    return jsonify({
        "sistema": sistema,
        "label": meta["label"],
        "icon": meta["icon"],
        "ftp": ftp_dir,
        "total": len(games),
        "total_size": fmt_size(total_size),
        "games": games,
    })

@app.route("/api/search")
def api_search():
    q = request.args.get("q", "").strip().lower()
    if len(q) < 2:
        return jsonify({"results": [], "total": 0})

    results = []
    sistemas_cargados = list(jsonl_cache.keys())

    for sid in sistemas_cargados:
        meta = SISTEMAS_META.get(sid, {})
        entries = jsonl_cache[sid]
        local_files = {f.name for f in (BASE_DIR / sid).iterdir()} if (BASE_DIR / sid).exists() else set()
        xbox_files  = ftp_cache.get(meta.get("ftp", ""), set())

        for e in entries:
            if q in e["n"].lower():
                filename = e["n"] + get_ext(e)
                results.append({
                    "sistema":    sid,
                    "label":      meta.get("label", sid),
                    "icon":       meta.get("icon", "🎮"),
                    "name":       e["n"],
                    "filename":   filename,
                    "size":       get_size(e),
                    "size_fmt":   fmt_size(get_size(e)),
                    "local":      filename in local_files,
                    "xbox":       filename in xbox_files,
                })

    results.sort(key=lambda x: x["name"].lower())
    return jsonify({"results": results[:200], "total": len(results),
                    "sistemas_indexados": len(sistemas_cargados)})

@app.route("/api/index-all")
def api_index_all():
    """Pre-carga todos los JSONL en caché para que la búsqueda global funcione."""
    def _load():
        for sid in SISTEMAS_META:
            try:
                cargar_jsonl(sid)
                sse_broadcast("index_progress", {"sistema": sid, "done": True})
            except Exception as ex:
                sse_broadcast("index_progress", {"sistema": sid, "done": False, "error": str(ex)})
        sse_broadcast("index_done", {"total": len(jsonl_cache)})
    threading.Thread(target=_load, daemon=True).start()
    return jsonify({"ok": True, "sistemas": list(SISTEMAS_META.keys())})

@app.route("/api/download", methods=["POST"])
def api_download():
    data = request.json
    sistema  = data["sistema"]
    filename = data["filename"]
    upload   = data.get("upload", True)

    if sistema not in SISTEMAS_META:
        return jsonify({"error": "Sistema no encontrado"}), 404

    try:
        entries = cargar_jsonl(sistema)
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500

    entry = next((e for e in entries if (e["n"] + get_ext(e)) == filename), None)
    if not entry:
        return jsonify({"error": "Archivo no encontrado"}), 404

    job_id = f"{sistema}_{filename}_{int(time.time())}"
    download_status[job_id] = {
        "job_id": job_id,
        "sistema": sistema,
        "filename": filename,
        "state": "queued",
        "progress": 0,
        "speed": 0,
        "eta": -1,
        "transferred": 0,
        "total": get_size(entry),
    }
    download_queue.put({
        "job_id": job_id,
        "sistema": sistema,
        "entry": entry,
        "ftp_dir": SISTEMAS_META[sistema]["ftp"],
        "upload": upload,
    })
    sse_broadcast("queued", {"job_id": job_id, "filename": filename, "sistema": sistema})
    return jsonify({"job_id": job_id})

@app.route("/api/download-all", methods=["POST"])
def api_download_all():
    data = request.json
    sistema  = data["sistema"]
    upload   = data.get("upload", True)
    only_missing = data.get("only_missing", True)

    if sistema not in SISTEMAS_META:
        return jsonify({"error": "Sistema no encontrado"}), 404

    entries = cargar_jsonl(sistema)
    ftp_dir = SISTEMAS_META[sistema]["ftp"]

    local_files = set()
    local_path = BASE_DIR / sistema
    if local_path.exists():
        local_files = {f.name for f in local_path.iterdir()}
    xbox_files = ftp_list_dir(ftp_dir) if upload else set()

    jobs = []
    for e in entries:
        filename = e["n"] + get_ext(e)
        if only_missing and (filename in local_files or filename in xbox_files):
            continue
        job_id = f"{sistema}_{filename}_{int(time.time())}"
        download_status[job_id] = {
            "job_id": job_id, "sistema": sistema, "filename": filename,
            "state": "queued", "progress": 0, "speed": 0,
            "eta": -1, "transferred": 0, "total": get_size(e),
        }
        download_queue.put({
            "job_id": job_id, "sistema": sistema, "entry": e,
            "ftp_dir": ftp_dir, "upload": upload,
        })
        jobs.append(job_id)
    return jsonify({"queued": len(jobs), "job_ids": jobs})

@app.route("/api/status")
def api_status():
    xbox = ftp_status()
    queue_size = download_queue.qsize()
    active = [v for v in download_status.values() if v["state"] not in ("done", "error")]
    return jsonify({
        "xbox_online": xbox,
        "queue_size": queue_size,
        "active_jobs": len(active),
        "jobs": list(download_status.values())[-50:],
    })

@app.route("/api/thumb/<sistema>/<path:rom_name>")
def api_thumb(sistema, rom_name):
    dest = get_or_fetch_thumb(sistema, rom_name)
    if dest:
        return send_file(dest, mimetype="image/png")
    return Response(status=404)

@app.route("/api/thumb-scrape/<sistema>", methods=["POST"])
def api_thumb_scrape(sistema):
    """Descarga carátulas de todos los juegos locales de un sistema y las sube al Xbox."""
    if sistema not in SISTEMAS_META:
        return jsonify({"error": "Sistema no encontrado"}), 404

    local_path = BASE_DIR / sistema
    roms = list(local_path.glob("*")) if local_path.exists() else []
    roms = [r for r in roms if r.suffix.lower() not in ('.tmp', '.log')]
    upload = request.json.get("upload", True) if request.json else True

    def _scrape():
        ok = fail = xbox_ok = 0
        ftp = None
        if upload:
            try: ftp = ftp_connect()
            except Exception: ftp = None

        for rom in roms:
            thumb = get_or_fetch_thumb(sistema, rom.stem)
            if thumb:
                ok += 1
                if ftp:
                    try:
                        subida = _ftp_upload_thumb(ftp, sistema, rom.stem)
                        if subida: xbox_ok += 1
                    except Exception:
                        try: ftp = ftp_connect()
                        except Exception: ftp = None
            else:
                fail += 1
            sse_broadcast("thumb_progress", {
                "sistema": sistema, "ok": ok, "fail": fail,
                "total": len(roms), "xbox_ok": xbox_ok,
            })

        try:
            if ftp: ftp.quit()
        except Exception: pass
        sse_broadcast("thumb_done", {"sistema": sistema, "ok": ok, "fail": fail, "xbox_ok": xbox_ok})

    threading.Thread(target=_scrape, daemon=True).start()
    return jsonify({"ok": True, "total": len(roms)})

def _ftp_upload_thumb(ftp, sistema, rom_stem):
    libretro = LIBRETRO_SYSTEM.get(sistema)
    if not libretro: return False
    local = THUMB_DIR / sistema / (thumb_game_name(rom_stem) + ".png")
    if not local.exists(): return False
    remote_dir  = f"/DRIVES/E/RetroArch/thumbnails/{libretro}/Named_Boxarts"
    remote_path = f"{remote_dir}/{local.name}"
    try:
        try: ftp.mkd(remote_dir)
        except Exception: pass
        with open(local, "rb") as f:
            ftp.storbinary(f"STOR {remote_path}", f)
        return True
    except Exception:
        return False

@app.route("/api/ftp-refresh/<sistema>")
def api_ftp_refresh(sistema):
    if sistema not in SISTEMAS_META:
        return jsonify({"error": "Sistema no encontrado"}), 404
    ftp_dir = SISTEMAS_META[sistema]["ftp"]
    ftp_cache.pop(ftp_dir, None)
    files = ftp_list_dir(ftp_dir)
    return jsonify({"ftp_dir": ftp_dir, "count": len(files), "files": list(files)[:50]})

@app.route("/api/events")
def api_events():
    q = queue.Queue()
    sse_clients.append(q)
    def stream():
        try:
            yield "data: connected\n\n"
            while True:
                try:
                    msg = q.get(timeout=30)
                    yield msg
                except queue.Empty:
                    yield ": ping\n\n"
        except GeneratorExit:
            try: sse_clients.remove(q)
            except: pass
    return Response(stream_with_context(stream()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

if __name__ == "__main__":
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"╔══════════════════════════════════════════╗")
    print(f"║  kalita-app  →  http://localhost:5000    ║")
    print(f"╚══════════════════════════════════════════╝")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
