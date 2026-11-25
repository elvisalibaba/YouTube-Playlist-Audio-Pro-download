"""Planification des sélections et commandes yt-dlp (sans shell)."""
from __future__ import annotations
import ipaddress
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

PREVIEW_LIMIT = 250
MULTI_LINK_LIMIT = 30
MODES = {"audio_original", "audio_mp3", "audio_m4a", "video_best", "video_mp4"}
QUALITIES = {"best", "2160", "1440", "1080", "720", "480", "360"}


def validate_url(value: str) -> str:
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError("URL invalide.")
    raw = value.strip()
    u = urlsplit(raw)
    if u.scheme not in {"http", "https"} or not u.hostname or u.username or u.password:
        raise ValueError("Utilise un lien public commençant par https:// ou http://.")
    if u.hostname.lower() == "localhost" or u.hostname.lower().endswith(".localhost"):
        raise ValueError("Les adresses locales ne sont pas acceptées.")
    try:
        ip = ipaddress.ip_address(u.hostname.strip("[]"))
        if not ip.is_global:
            raise ValueError("Les adresses IP privées ou réservées ne sont pas acceptées.")
    except ValueError as exc:
        if "ne sont pas acceptées" in str(exc):
            raise
    if u.port and u.port not in {80, 443}:
        raise ValueError("Le port dans ce lien n'est pas autorisé.")
    return raw



def parse_source_urls(value: str) -> list[str]:
    """Une URL pour une playlist ou plusieurs URLs de vidéos individuelles."""
    if not isinstance(value, str) or len(value) > 35000:
        raise ValueError("Liens invalides ou trop longs.")
    urls = [validate_url(line) for line in value.splitlines() if line.strip()]
    if not urls:
        raise ValueError("Colle au moins un lien vidéo ou playlist.")
    if len(urls) > MULTI_LINK_LIMIT:
        raise ValueError(f"Maximum {MULTI_LINK_LIMIT} liens individuels par lot.")
    if len(set(urls)) != len(urls):
        raise ValueError("Retire les liens identiques répétés dans la liste.")
    return urls


def recognize_site(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    if host == "eporner.com" or host.endswith(".eporner.com"):
        return "Eporner"
    if host == "pornhub.com" or host.endswith(".pornhub.com"):
        return "Pornhub"
    if host in {"djatoya.com", "www.djatoya.com"}:
        return "Djatoya"
    if host in {"youtube.com", "youtu.be"} or host.endswith(".youtube.com"):
        return "YouTube"
    return "Autre site compatible"

def normalize_channel(url: str, exclude_shorts: bool) -> tuple[str, bool]:
    """YouTube /@user and /channel/.. roots -> videos tab, not shorts."""
    u = urlsplit(url)
    host = (u.hostname or "").lower()
    path = u.path.rstrip("/")
    if exclude_shorts and host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if re.fullmatch(r"/(?:@[^/]+|channel/[^/]+|c/[^/]+|user/[^/]+)", path):
            return urlunsplit((u.scheme, u.netloc, path + "/videos", u.query, u.fragment)), True
    return url, False


def make_preview_command(python: str, url: str) -> list[str]:
    return [python, "-m", "yt_dlp", "--ignore-config", "--flat-playlist", "--dump-single-json",
            "--playlist-end", str(PREVIEW_LIMIT + 1), "--ignore-errors", "--no-warnings", url]


def make_download_command(python: str, url: str | list[str], folder: str, mode: str,
                          quality: str, indices: list[int] | None, exclude_shorts: bool = True, direct_links: bool = False) -> list[str]:
    urls = [validate_url(u) for u in url] if isinstance(url, list) else [validate_url(url)]
    if not urls or len(urls) > MULTI_LINK_LIMIT:
        raise ValueError("Nombre de liens invalide.")
    if len(urls) > 1 and indices is not None:
        raise ValueError("La sélection multi-liens se fait avant construction des commandes.")
    if mode not in MODES or quality not in QUALITIES:
        raise ValueError("Format ou qualité inconnus.")
    if indices is not None:
        if not indices or len(indices) > PREVIEW_LIMIT or any(type(i) is not int or i < 1 for i in indices):
            raise ValueError("Sélection d'éléments incorrecte.")
        indices = sorted(set(indices))
    output = Path(folder).expanduser().resolve()
    if not output.is_dir():
        raise ValueError("Le dossier de destination doit déjà exister.")
    # Archive by mode to allow downloading an audio and a video of the same source separately.
    archive_name = f"{mode}_{quality}" if mode.startswith("video_") else mode
    archive = output / f".telechargements_{archive_name}.txt"
    cmd = [python, "-m", "yt_dlp", "--ignore-config", "--newline", "--no-overwrites",
           "--continue", "--ignore-errors", "--windows-filenames", "--trim-filenames", "180",
           "--download-archive", str(archive), "-P", str(output),
           "-o", "%(extractor_key|Site)s/%(playlist_title|Vidéos)s/%(playlist_index|0)03d - %(title).150B [%(id)s].%(ext)s",
           "--retries", "5", "--fragment-retries", "5", "--concurrent-fragments", "3"]
    if direct_links:
        cmd.append("--no-playlist")
    if indices is not None:
        cmd.extend(["--playlist-items", ",".join(str(i) for i in indices)])
    elif exclude_shorts:
        # For channel-root URLs, caller already normalized to /videos.
        pass
    if mode.startswith("audio_"):
        cmd.extend(["-f", "bestaudio/best"])
        if mode == "audio_original":
            cmd.extend(["--extract-audio", "--audio-format", "best"])
        else:
            cmd.extend(["--extract-audio", "--audio-format", "mp3" if mode == "audio_mp3" else "m4a",
                        "--audio-quality", "0", "--add-metadata", "--embed-thumbnail"])
    else:
        cap = "" if quality == "best" else f"[height<=?{quality}]"
        if mode == "video_best":
            fmt = f"bv*{cap}+ba/b{cap}"
            cmd.extend(["-f", fmt, "--merge-output-format", "mkv"])
        else:
            # Prefer H.264 + M4A for iPhone; otherwise prefer any MP4-compatible streams.
            fmt = (f"bv*{cap}[vcodec^=avc1]+ba[ext=m4a]/"
                   f"b[ext=mp4]{cap}/bv*{cap}[ext=mp4]+ba[ext=m4a]/"
                   f"bv*{cap}+ba/b{cap}")
            cmd.extend(["-f", fmt, "--merge-output-format", "mp4"])
        cmd.append("--add-metadata")
    cmd.extend(urls)
    return cmd


def parse_entries(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Réponse inattendue du site.")
    incoming = data.get("entries")
    if not isinstance(incoming, list):
        incoming = [data]
    truncated = len(incoming) > PREVIEW_LIMIT
    entries = []
    for idx, item in enumerate(incoming[:PREVIEW_LIMIT], 1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("id") or f"Élément {idx}")[:240]
        source_url = str(item.get("webpage_url") or item.get("url") or "")
        duration = item.get("duration")
        if not isinstance(duration, (int, float)) or duration < 0:
            duration = None
        is_short = "/shorts/" in source_url.lower()
        nested = item.get("_type") == "playlist"
        thumbnail = str(item.get("thumbnail") or "")
        if not thumbnail:
            thumbnails = item.get("thumbnails")
            if isinstance(thumbnails, list):
                for candidate in reversed(thumbnails):
                    if isinstance(candidate, dict) and candidate.get("url"):
                        thumbnail = str(candidate["url"])
                        break
        channel = str(item.get("channel") or item.get("uploader") or item.get("channel_id") or "")[:160]
        entries.append({"index": idx, "title": title, "duration": int(duration) if duration is not None else None,
                        "short": is_short, "nested": nested, "id": str(item.get("id") or "")[:120],
                        "thumbnail": thumbnail[:2000], "channel": channel})
    return {"title": str(data.get("title") or "Média")[:240], "entries": entries,
            "truncated": truncated, "has_playlist": isinstance(data.get("entries"), list)}
