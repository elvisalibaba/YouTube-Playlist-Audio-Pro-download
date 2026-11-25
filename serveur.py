"""Interface locale de Media Select Pro V6. Aucun serveur externe."""
from __future__ import annotations
import argparse
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

from decouverte import discover, is_listing_page

from moteur import (make_download_command, make_preview_command, normalize_channel,
                    parse_entries, validate_url, parse_source_urls, recognize_site,
                    read_archive_ids, PREVIEW_LIMIT, MODES, QUALITIES)

FROZEN = bool(getattr(sys, "frozen", False))
BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
DATA_BASE = Path(sys.executable).resolve().parent if FROZEN else BASE
HISTORY_FILE = DATA_BASE / "historique.json"
DOWNLOADS_FILE = DATA_BASE / "telechargements.json"
THUMBNAIL_CACHE = {}
THUMBNAIL_LOCK = threading.Lock()


def yt_dlp_runtime():
    return [sys.executable, "--run-yt-dlp"] if FROZEN else sys.executable


def fetch_youtube_thumbnail(video_id):
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("Identifiant de miniature invalide")
    with THUMBNAIL_LOCK:
        cached = THUMBNAIL_CACHE.get(video_id)
    if cached:
        return cached
    last_error = None
    for filename in ("hqdefault.jpg", "mqdefault.jpg", "default.jpg"):
        req = urlrequest.Request(
            f"https://i.ytimg.com/vi/{video_id}/{filename}",
            headers={"User-Agent": "Mozilla/5.0", "Accept": "image/avif,image/webp,image/jpeg,*/*"})
        try:
            with urlrequest.urlopen(req, timeout=15) as response:
                raw = response.read(2_000_001)
            if raw and len(raw) <= 2_000_000:
                with THUMBNAIL_LOCK:
                    if len(THUMBNAIL_CACHE) >= 300:
                        THUMBNAIL_CACHE.pop(next(iter(THUMBNAIL_CACHE)))
                    THUMBNAIL_CACHE[video_id] = raw
                return raw
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = exc
    raise ValueError(f"Miniature indisponible : {last_error or 'réponse vide'}")


class State:
    def __init__(self):
        self.lock = threading.RLock()
        self.token = secrets.token_urlsafe(24)
        self.process = None
        self.preview_process = None
        self.running = False
        self.previewing = False
        self.status = "Prêt"
        self.progress = ""
        self.logs = deque(maxlen=180)
        self.cancel_requested = False
        self.last_command_mode = ""
        self.errors = 0
        self.preview_urls = ()
        self.preview_valid_indices = set()
        self.preview_has_playlist = False
        self.preview_discovered = {}
        self.preview_discovery_mode = False
        self.preview_titles = {}
        self.preview_media = {}
        self.preview_title = ""
        self.active_history_id = ""
        self.active_items = {}
        self.active_quality = "best"
        self.active_folder = ""
        self.history = self._load_history()
        self.downloads = self._load_downloads()

    @staticmethod
    def _load_history():
        try:
            data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            return data[:100] if isinstance(data, list) else []
        except (OSError, ValueError, TypeError):
            return []

    def _save_history(self):
        try:
            temporary = HISTORY_FILE.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(self.history[:100], ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(HISTORY_FILE)
        except OSError:
            pass

    @staticmethod
    def _load_downloads():
        try:
            data = json.loads(DOWNLOADS_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def _save_downloads(self):
        try:
            temporary = DOWNLOADS_FILE.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(self.downloads, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(DOWNLOADS_FILE)
        except OSError:
            pass

    @staticmethod
    def download_key(media_id, mode, quality):
        profile = quality if str(mode).startswith("video_") else mode
        return f"{media_id}|{mode}|{profile}"

    def downloaded_indices(self, mode, quality, folder):
        archive_ids = read_archive_ids(folder, mode, quality) if folder else set()
        with self.lock:
            known_ids = {record.get("id") for record in self.downloads.values()
                         if record.get("mode") == mode and
                         (not str(mode).startswith("video_") or record.get("quality") == quality)}
            ids = archive_ids | known_ids
            return sorted(index for index, media in self.preview_media.items()
                          if media.get("id") and media.get("id") in ids)

    def record_download(self, media_id):
        with self.lock:
            media = self.active_items.get(media_id, {"id": media_id, "title": media_id})
            key = self.download_key(media_id, self.last_command_mode, self.active_quality)
            self.downloads[key] = {
                "id": media_id, "title": media.get("title", media_id),
                "thumbnail": media.get("thumbnail", ""), "mode": self.last_command_mode,
                "quality": self.active_quality, "folder": self.active_folder,
                "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%S")
            }
            self._save_downloads()

    def add_history(self, *, title, count, mode, quality, folder, items):
        with self.lock:
            history_id = secrets.token_hex(8)
            self.history.insert(0, {
                "id": history_id, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "title": str(title or "Téléchargement")[:240], "count": int(count),
                "mode": str(mode), "quality": str(quality), "folder": str(folder)[:1000],
                "items": [str(value)[:240] for value in items[:20]], "status": "En cours"
            })
            self.history = self.history[:100]
            self._save_history()
            return history_id

    def finish_history(self, history_id, status):
        if not history_id:
            return
        with self.lock:
            for entry in self.history:
                if entry.get("id") == history_id:
                    entry["status"] = status
                    entry["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                    break
            self._save_history()

    def history_snapshot(self):
        with self.lock:
            result = [dict(entry) for entry in self.history]
            for entry in result:
                if self.running and entry.get("id") == self.active_history_id:
                    entry["status"] = self.status
                    entry["progress"] = self.progress
                    entry["running"] = True
            return result

    def log(self, line):
        with self.lock:
            completed = re.search(r"MEDIA_SELECT_DONE:([A-Za-z0-9_-]+)", line)
            if completed:
                self.record_download(completed.group(1))
                self.status = "Vidéo enregistrée avec succès"
                return
            self.logs.append(line[:800])
            if "[download]" in line:
                found = re.search(r"\b(\d+(?:\.\d+)?)%", line)
                if found:
                    self.progress = found.group(1) + "%"
                if "Downloading item" in line:
                    self.status = line.strip().replace("[download]", "").strip()
            elif "ERROR:" in line:
                self.errors += 1
                self.status = "Erreur rencontrée, voir le journal"

    def snapshot(self):
        with self.lock:
            return {"running": self.running, "previewing": self.previewing,
                    "status": self.status, "progress": self.progress, "logs": list(self.logs),
                    "errors": self.errors,
                    "active_history_id": self.active_history_id,
                    "ffmpeg": shutil.which("ffmpeg") is not None,
                    "deno": shutil.which("deno") is not None,
                    "python": sys.version.split()[0]}

STATE = State()


def terminate(proc):
    if proc and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            proc.kill()
        except (OSError, ProcessLookupError):
            pass


def work_download(commands):
    """Télécharge par petits lots pour éviter les lignes de commandes trop longues sous Windows."""
    if commands and isinstance(commands[0], str):
        commands = [commands]
    failed = 0
    with STATE.lock:
        history_id = STATE.active_history_id
    history_status = "Erreur"
    try:
        for number, cmd in enumerate(commands, 1):
            with STATE.lock:
                if STATE.cancel_requested:
                    STATE.status = "Téléchargement arrêté"
                    break
                STATE.status = f"Traitement du lot {number}/{len(commands)}"
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            with STATE.lock:
                STATE.process = proc
                cancelled = STATE.cancel_requested
            if cancelled:
                terminate(proc)
            for line in proc.stdout:
                STATE.log(line.rstrip())
            code = proc.wait()
            failed += int(code != 0)
        with STATE.lock:
            if STATE.cancel_requested:
                STATE.status = "Téléchargement arrêté par l'utilisateur"
                history_status = "Arrêté"
            elif failed or STATE.errors:
                STATE.status = (f"Terminé avec {STATE.errors} erreur(s) affichée(s) "
                                f"et {failed} lot(s) en échec. Consulte le journal.")
                history_status = "Terminé avec erreurs"
            else:
                STATE.status = "Traitement terminé. Vérifie les fichiers créés et le journal."
                STATE.progress = "100%"
                history_status = "Terminé"
    except Exception as exc:
        STATE.log(f"Erreur interne : {exc}")
        with STATE.lock:
            STATE.status = f"Échec du lancement : {exc}"
    finally:
        STATE.finish_history(history_id, history_status)
        with STATE.lock:
            STATE.running = False
            STATE.process = None
            STATE.active_history_id = ""


def preview_one(url):
    """Exécute yt-dlp en lecture seule pour un lien, sans télécharger de média."""
    cmd = make_preview_command(yt_dlp_runtime(), url)
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         encoding="utf-8", errors="replace",
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    with STATE.lock:
        STATE.preview_process = p
    try:
        try:
            stdout, stderr = p.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            terminate(p)
            raise ValueError("Analyse trop longue : essaie le lien d'une vidéo précise.")
        if p.returncode != 0 or not stdout.strip():
            lines = (stderr or "").strip().splitlines()
            detail = lines[-1] if lines else "Lien non reconnu ou média inaccessible."
            raise ValueError(detail[:400])
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            raise ValueError("Le site n'a pas renvoyé une liste exploitable.")
        return parse_entries(data)
    finally:
        with STATE.lock:
            STATE.preview_process = None


def preview(urls):
    """Liste native d'un site OU ensemble de liens vidéo unitaires.

    Une page de recherche non prise en charge ne doit jamais être considérée
    comme une playlist téléchargeable.
    """
    with STATE.lock:
        if STATE.previewing or STATE.running:
            raise ValueError("Une autre opération est en cours.")
        STATE.previewing = True
        STATE.preview_urls = ()
        STATE.preview_valid_indices = set()
        STATE.preview_discovered = {}
        STATE.preview_discovery_mode = False
        STATE.preview_titles = {}
        STATE.preview_media = {}
        STATE.preview_title = ""
    try:
        if len(urls) == 1:
            if is_listing_page(urls[0]):
                result = discover(urls[0])
            else:
                result = preview_one(urls[0])
        else:
            items = []
            for index, url in enumerate(urls, 1):
                try:
                    info = preview_one(url)
                except ValueError as exc:
                    raise ValueError(f"Lien {index} ({recognize_site(url)}) : {exc}") from exc
                if len(info["entries"]) != 1 or info["entries"][0]["nested"]:
                    raise ValueError(f"Lien {index} : colle une URL de vidéo individuelle et non une page contenant plusieurs vidéos.")
                item = dict(info["entries"][0])
                item["index"] = index
                item["site"] = recognize_site(url)
                items.append(item)
            result = {"title": f"Sélection de {len(items)} liens", "entries": items,
                      "truncated": False, "has_playlist": True, "batch_links": True}
        result["site"] = recognize_site(urls[0]) if len(urls) == 1 else "Plusieurs sites"
        result.setdefault("batch_links", False)
        with STATE.lock:
            STATE.preview_urls = tuple(urls)
            STATE.preview_valid_indices = {e["index"] for e in result["entries"] if not e["nested"]}
            STATE.preview_has_playlist = bool(result["has_playlist"])
            STATE.preview_discovery_mode = bool(result.get("discovered_links"))
            STATE.preview_discovered = ({e["index"]: e["url"] for e in result["entries"]}
                                        if STATE.preview_discovery_mode else {})
            STATE.preview_titles = {e["index"]: e.get("title", "Vidéo") for e in result["entries"]
                                    if not e["nested"]}
            STATE.preview_media = {e["index"]: {
                "id": e.get("id", ""), "title": e.get("title", "Vidéo"),
                "thumbnail": e.get("thumbnail", "")
            } for e in result["entries"] if not e["nested"]}
            STATE.preview_title = result.get("title", "Téléchargement")
        return result
    finally:
        with STATE.lock:
            STATE.previewing = False
            STATE.preview_process = None


def choose_folder():
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(title="Choisir le dossier pour les téléchargements")
        root.destroy()
        return selected or None
    except Exception:
        return None


class Handler(BaseHTTPRequestHandler):
    server_version = "MediaSelectPro/7.0"

    def log_message(self, fmt, *args):
        pass

    def response(self, status, obj):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            html = (BASE / "interface.html").read_text(encoding="utf-8")
            html = html.replace("__LOCAL_TOKEN__", STATE.token)
            raw = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline' 'self'; script-src 'unsafe-inline' 'self'; connect-src 'self'; img-src 'self' data: https: http:")
            self.end_headers()
            self.wfile.write(raw)
        elif self.path == "/api/status":
            self.response(200, STATE.snapshot())
        elif self.path.startswith("/api/thumbnail/"):
            video_id = self.path.removeprefix("/api/thumbnail/").split("?", 1)[0]
            try:
                raw = fetch_youtube_thumbnail(video_id)
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "private, max-age=86400")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(raw)
            except ValueError as exc:
                self.response(404, {"error": str(exc)})
        else:
            self.response(404, {"error": "Ressource introuvable"})

    def do_POST(self):
        # Requests only from our UI, with a per-session token. Nothing is served on the network.
        if not hmac.compare_digest(self.headers.get("X-Local-Token", ""), STATE.token):
            return self.response(403, {"error": "Accès refusé"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 0 or size > 40000:
                raise ValueError("Requête trop longue")
            data = json.loads(self.rfile.read(size) or b"{}")
            if not isinstance(data, dict):
                raise ValueError("Requête invalide")
            if self.path == "/api/preview":
                urls = parse_source_urls(data.get("url", ""))
                adjusted = False
                if len(urls) == 1:
                    urls[0], adjusted = normalize_channel(urls[0], bool(data.get("exclude_shorts", True)))
                result = preview(urls)
                result["effective_url"] = "\n".join(urls)
                result["adjusted_channel"] = adjusted
                result["preview_limit"] = PREVIEW_LIMIT
                return self.response(200, result)
            if self.path == "/api/folder":
                value = choose_folder()
                return self.response(200, {"folder": value})
            if self.path == "/api/history":
                return self.response(200, {"entries": STATE.history_snapshot()})
            if self.path == "/api/download-info":
                mode = data.get("mode")
                quality = data.get("quality", "best")
                if mode not in MODES or quality not in QUALITIES:
                    raise ValueError("Format ou qualité inconnus.")
                indices = STATE.downloaded_indices(mode, quality, str(data.get("folder") or ""))
                return self.response(200, {"downloaded_indices": indices})
            if self.path == "/api/start":
                urls = parse_source_urls(data.get("url", ""))
                if len(urls) == 1:
                    urls[0], _ = normalize_channel(urls[0], bool(data.get("exclude_shorts", True)))
                mode = data.get("mode")
                quality = data.get("quality", "best")
                selection = data.get("selection", "selected")
                if selection not in {"selected", "all"}:
                    raise ValueError("Choix de la sélection incorrect")
                indices = data.get("indices") if selection == "selected" else None
                with STATE.lock:
                    if STATE.running or STATE.previewing:
                        raise ValueError("Une opération est déjà en cours.")
                    if not STATE.preview_urls or STATE.preview_urls != tuple(urls):
                        raise ValueError("Analyse d'abord ces liens avant de télécharger.")
                    if indices is not None:
                        if not isinstance(indices, list) or not indices or any(type(i) is not int for i in indices):
                            raise ValueError("Sélection d'éléments incorrecte.")
                        if not set(indices).issubset(STATE.preview_valid_indices):
                            raise ValueError("La sélection ne correspond pas à la liste analysée.")
                    requested_indices = sorted(indices or STATE.preview_valid_indices)
                    duplicates = set(STATE.downloaded_indices(
                        mode, quality, str(data.get("folder") or "")))
                    indices = [index for index in requested_indices if index not in duplicates]
                    if not indices:
                        raise ValueError("Cette sélection a déjà été téléchargée dans ce format.")
                    discovered = dict(STATE.preview_discovered)
                    if STATE.preview_discovery_mode:
                        if not discovered:
                            raise ValueError("Aucun lien vidéo détecté sur cette page.")
                        # Liens issus de la page analysée : jamais l'URL du profil ou de l'accueil.
                        order = sorted(discovered)
                        choices = order if indices is None else [n for n in order if n in indices]
                        target = [discovered[n] for n in choices]
                        effective_indices = None
                    elif len(urls) > 1:
                        target = [u for pos, u in enumerate(urls, 1) if indices is None or pos in indices]
                        effective_indices = None
                    else:
                        target = urls[0]
                        effective_indices = indices if STATE.preview_has_playlist else None
                    if isinstance(target, list) and not target:
                        raise ValueError("Aucune vidéo sélectionnée.")
                    if isinstance(target, list):
                        # 8 vidéos par commande : sécurité pour cmd.exe / CreateProcess Windows.
                        commands = [make_download_command(yt_dlp_runtime(), target[j:j + 8],
                                     str(data.get("folder") or ""), mode, quality, None,
                                     direct_links=True) for j in range(0, len(target), 8)]
                    else:
                        commands = [make_download_command(yt_dlp_runtime(), target,
                                    str(data.get("folder") or ""), mode, quality, effective_indices)]
                    STATE.logs.clear()
                    STATE.errors = 0
                    STATE.status = "Démarrage du téléchargement"
                    STATE.progress = ""
                    STATE.running = True
                    STATE.cancel_requested = False
                    STATE.last_command_mode = mode
                    STATE.active_quality = quality
                    STATE.active_folder = str(data.get("folder") or "")
                    selected_indices = sorted(indices)
                    STATE.active_items = {
                        STATE.preview_media[index]["id"]: dict(STATE.preview_media[index])
                        for index in selected_indices if STATE.preview_media.get(index, {}).get("id")
                    }
                    selected_titles = [STATE.preview_titles.get(index, f"Vidéo {index}")
                                       for index in selected_indices]
                    STATE.active_history_id = STATE.add_history(
                        title=STATE.preview_title, count=len(selected_indices), mode=mode,
                        quality=quality, folder=str(data.get("folder") or ""), items=selected_titles)
                threading.Thread(target=work_download, args=(commands,), daemon=True).start()
                return self.response(200, {"ok": True, "skipped": len(duplicates & set(requested_indices))})
            if self.path == "/api/cancel":
                with STATE.lock:
                    if not STATE.running:
                        return self.response(200, {"ok": True})
                    STATE.cancel_requested = True
                    proc = STATE.process
                if proc:
                    threading.Thread(target=terminate, args=(proc,), daemon=True).start()
                return self.response(200, {"ok": True})
            return self.response(404, {"error": "Action inconnue"})
        except Exception as exc:
            self.response(400, {"error": str(exc)[:500]})


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--run-yt-dlp":
        from yt_dlp import main as yt_dlp_main
        yt_dlp_main(sys.argv[2:])
        return
    parser = argparse.ArgumentParser(description="Téléchargeur local multi-sites")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"Media Select Pro V7 : {url}", flush=True)
    print("Garde cette fenêtre ouverte. Ctrl+C pour quitter.", flush=True)
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        terminate(STATE.process)
        terminate(STATE.preview_process)
        server.server_close()

if __name__ == "__main__":
    main()
