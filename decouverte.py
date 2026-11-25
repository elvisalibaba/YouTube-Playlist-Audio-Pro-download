"""Découverte prudente des liens publics de vidéos depuis certaines pages catalogue.

Ne lit pas de flux vidéo, n'utilise ni cookies ni authentification,
ni méthode permettant de contourner des protections. Aucune extraction
universelle des pages : les sites sont reconnus explicitement.
"""
from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener
import ipaddress
import re
import socket

from moteur import validate_url

MAX_PAGE_BYTES = 3_000_000
DISCOVERY_LIMIT = 100
ALLOWED_HOSTS = {
    'eporner.com', 'www.eporner.com', 'fr.eporner.com',
    'djatoya.com', 'www.djatoya.com',
}


def host_kind(url: str) -> str | None:
    host = (urlsplit(url).hostname or '').lower()
    if host in ('eporner.com', 'www.eporner.com', 'fr.eporner.com'):
        return 'eporner'
    if host in ('djatoya.com', 'www.djatoya.com'):
        return 'djatoya'
    return None


def is_video_url(url: str, kind: str) -> bool:
    path = urlsplit(url).path
    if kind == 'eporner':
        return bool(re.fullmatch(r'/video-[A-Za-z0-9]+/[^?#]*/?', path, re.I))
    if kind == 'djatoya':
        return bool(re.fullmatch(r'/video/\d+(?:/[^?#]*)?', path, re.I))
    return False


def is_listing_page(url: str) -> bool:
    kind = host_kind(url)
    if not kind or is_video_url(url, kind):
        return False
    path = urlsplit(url).path
    if kind == 'eporner':
        return bool(re.fullmatch(r'/profile/[^/]+(?:/uploaded-videos(?:/.*)?)?/?', path, re.I))
    # Djatoya utilise des pages de catégories, d'accueil et de chaînes.
    # Toute adresse publique non-video de ce domaine est essayée comme catalogue.
    return True


def normalize_listing_url(url: str) -> str:
    url = validate_url(url)
    if not is_listing_page(url):
        raise ValueError('Cette adresse n’est pas une page catalogue prise en charge.')
    u = urlsplit(url)
    if host_kind(url) == 'eporner' and re.fullmatch(r'/profile/[^/]+/?', u.path, re.I):
        path = u.path.rstrip('/') + '/uploaded-videos/'
        return urlunsplit((u.scheme, u.netloc, path, u.query, ''))
    return url


def validate_fetch_url(url: str, expected_kind: str) -> str:
    u = urlsplit(validate_url(url))
    if u.scheme != 'https' or u.hostname not in ALLOWED_HOSTS or host_kind(url) != expected_kind:
        raise ValueError('Redirection externe ou non sécurisée : chargement interrompu.')
    if u.port is not None and u.port != 443:
        raise ValueError('Port non autorisé.')
    # SSRF : refuser les adresses IP non publiques obtenues par DNS.
    try:
        addresses = socket.getaddrinfo(u.hostname, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError(f'Impossible de résoudre le nom du site : {exc}') from exc
    if not addresses or any(not ipaddress.ip_address(addr[4][0]).is_global for addr in addresses):
        raise ValueError('Adresse réseau non publique : chargement refusé.')
    return url


class RestrictedRedirect(HTTPRedirectHandler):
    def __init__(self, kind: str):
        self.kind = kind
        super().__init__()

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        validate_fetch_url(newurl, self.kind)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def fetch_html(url: str) -> str:
    kind = host_kind(url)
    if not kind:
        raise ValueError('Site non pris en charge pour la découverte de catalogue.')
    url = validate_fetch_url(url, kind)
    opener = build_opener(RestrictedRedirect(kind))
    req = Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; MediaSelectPro/7.0; local-browser)',
        'Accept': 'text/html,application/xhtml+xml',
    })
    try:
        with opener.open(req, timeout=18) as resp:
            ctype = resp.headers.get('Content-Type', '')
            if 'html' not in ctype.lower():
                raise ValueError('La page ne renvoie pas de document HTML.')
            payload = resp.read(MAX_PAGE_BYTES + 1)
            if len(payload) > MAX_PAGE_BYTES:
                raise ValueError('La page est trop volumineuse pour une analyse sûre.')
            charset = resp.headers.get_content_charset() or 'utf-8'
            return payload.decode(charset, errors='replace')
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f'Lecture de la page impossible : {type(exc).__name__} : {exc}') from exc


class AnchorReader(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.current = None
        self.in_title = False
        self.page_title = ''

    def handle_starttag(self, tag, attrs):
        vals = dict(attrs)
        if tag == 'a':
            self.current = {'href': vals.get('href') or '', 'text': '',
                            'hint': vals.get('title') or vals.get('aria-label') or ''}
        if tag == 'img' and self.current and not self.current['hint']:
            self.current['hint'] = vals.get('alt') or ''
        if tag == 'title':
            self.in_title = True

    def handle_data(self, data):
        if self.current:
            self.current['text'] += ' ' + data
        if self.in_title:
            self.page_title += data

    def handle_endtag(self, tag):
        if tag == 'a' and self.current:
            self.links.append(self.current)
            self.current = None
        if tag == 'title':
            self.in_title = False


def clean_title(value: str) -> str:
    return re.sub(r'\s+', ' ', unescape(value or '')).strip()[:240]


def discover(url: str, fetcher=None) -> dict:
    """Retourne une liste UNIQUEMENT de liens vidéo explicites de la page publique.

    Le résultat n'atteste pas que le site propose le téléchargement du flux.
    """
    page_url = normalize_listing_url(url)
    kind = host_kind(page_url)
    source = (fetcher or fetch_html)(page_url)
    parser = AnchorReader()
    parser.feed(source)
    found = []
    known = set()
    next_page = None
    for link in parser.links:
        href = (link.get('href') or '').strip()
        if not href or href.startswith(('#', 'javascript:', 'mailto:', 'data:')):
            continue
        absolute = urljoin(page_url, href)
        u = urlsplit(absolute)
        if u.scheme != 'https' or host_kind(absolute) != kind:
            continue
        complete = absolute
        absolute = urlunsplit((u.scheme, u.netloc, u.path, '', ''))
        if is_video_url(absolute, kind):
            if absolute not in known:
                known.add(absolute)
                title = clean_title(link.get('text') or link.get('hint') or '')
                if not title:
                    title = u.path.rstrip('/').split('/')[-1].replace('-', ' ')
                found.append({'url': absolute, 'title': title, 'duration': None,
                              'short': False, 'nested': False})
        elif not next_page and any(word in clean_title(link.get('text', '')).lower()
                                   for word in ('next', 'en avant', 'suivant', 'suivante', '›')):
            if is_listing_page(complete) and complete != page_url:
                next_page = complete
    limited = found[:DISCOVERY_LIMIT]
    for n, item in enumerate(limited, 1):
        item['index'] = n
        item['id'] = f'video-{n}'
    return {
        'title': clean_title(parser.page_title) or 'Vidéos découvertes',
        'entries': limited,
        'truncated': len(found) > DISCOVERY_LIMIT,
        'has_playlist': True,
        'discovered_links': True,
        'batch_links': False,
        'next_page': next_page,
        'listing_page': page_url,
        'warning': ('Les titres sont détectés depuis les liens de cette page. '
                    'Le téléchargement reste dépendant du lecteur et de yt-dlp. '
                    '« Tous » concerne uniquement les vidéos affichées sur cette page.'),
    }
