#!/usr/bin/env python3
# lang: Python 3.11+, file: vnum_monitor.py, target: Render Background Worker
# monitores: receive-smss.com · receivesms.co · smsfree24.com · quackr.io · onlinesim.io

import asyncio
import aiohttp
import json
import logging
import os
import re
import random
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from dataclasses import dataclass
from datetime import datetime, timezone
from bs4 import BeautifulSoup
import redis.asyncio as aioredis


# ─── HEALTH SERVER (back4app necesita un puerto HTTP activo) ──────────────────
class _Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")
    def log_message(self, *args):
        pass  # silenciar logs del servidor

def _start_health_server():
    port = int(os.getenv("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), _Health)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logging.info(f"Health server en :{port}")


# ─── CONFIG ───────────────────────────────────────────────────────────────────
WEBHOOK_URL    = os.getenv("DISCORD_WEBHOOK", "PEGA_TU_WEBHOOK_AQUI")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "").strip() or "60")
DATA_FILE      = "seen.json"
BOT_NAME       = "NumBot 🔢"
REDIS_URL      = os.getenv("REDIS_URL")
REDIS_KEY      = "vnum:seen"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
]


# ─── MODELOS ──────────────────────────────────────────────────────────────────
@dataclass
class NumberEntry:
    number  : str
    country : str = "Unknown"
    source  : str = ""
    link    : str = ""

@dataclass
class Target:
    name   : str
    url    : str
    color  : int
    parse  : object


# ─── PARSERS ──────────────────────────────────────────────────────────────────
def _extract_number(text: str) -> str | None:
    m = re.search(r'\+?\d[\d\s\-\(\)]{6,20}', text)
    if not m:
        return None
    return re.sub(r'[\s\-\(\)]', '', m.group(0))


def parse_receive_smss(html: str, base_url: str) -> list[NumberEntry]:
    soup    = BeautifulSoup(html, "html.parser")
    entries = []
    boxes   = []
    for sel in [".number-boxes-itemm", ".number-box", "[class*='number-box']", "[class*='phone-box']"]:
        boxes = soup.select(sel)
        if boxes:
            break
    for box in boxes:
        num_tag  = box.select_one("h4, h3, .number, [class*='number']")
        cnt_tag  = box.select_one("h5, .country, [class*='country']")
        link_tag = box.select_one("a[href]")
        raw      = num_tag.get_text(strip=True) if num_tag else box.get_text(" ", strip=True)
        number   = _extract_number(raw)
        if not number:
            continue
        country = cnt_tag.get_text(strip=True) if cnt_tag else "Unknown"
        href    = link_tag["href"] if link_tag else ""
        link    = (base_url.rstrip("/") + href) if href.startswith("/") else href or base_url
        entries.append(NumberEntry(number=number, country=country, source="receive-smss.com", link=link))
    return entries


def parse_receivesms_co(html: str, base_url: str) -> list[NumberEntry]:
    soup     = BeautifulSoup(html, "html.parser")
    entries  = []
    KEYWORDS = ["United States","Canada","UK","United Kingdom","Germany","France","Australia","Netherlands","Sweden"]
    for row in soup.select("tr, .number-item, [class*='phone']"):
        text   = row.get_text(" ", strip=True)
        number = _extract_number(text)
        if not number:
            continue
        country  = next((kw for kw in KEYWORDS if kw.lower() in text.lower()), "Unknown")
        link_tag = row.select_one("a[href]")
        href     = link_tag["href"] if link_tag else ""
        link     = (base_url.rstrip("/") + href) if href.startswith("/") else href or base_url
        entries.append(NumberEntry(number=number, country=country, source="receivesms.co", link=link))
    return entries


def parse_smsfree24(html: str, base_url: str) -> list[NumberEntry]:
    soup    = BeautifulSoup(html, "html.parser")
    entries = []
    for card in soup.select(".col-phone, .phone-item, article, [class*='phone'], [class*='number']"):
        raw    = card.get_text(" ", strip=True)
        number = _extract_number(raw)
        if not number:
            continue
        cnt_tag  = card.select_one(".country, [class*='country'], [class*='flag']")
        link_tag = card.select_one("a[href]")
        country  = cnt_tag.get_text(strip=True) if cnt_tag else "Unknown"
        href     = link_tag["href"] if link_tag else ""
        link     = (base_url.rstrip("/") + href) if href.startswith("/") else href or base_url
        entries.append(NumberEntry(number=number, country=country, source="smsfree24.com", link=link))
    return entries


def parse_quackr(html: str, base_url: str) -> list[NumberEntry]:
    soup    = BeautifulSoup(html, "html.parser")
    entries = []
    for item in soup.select("a[href*='/temporary-numbers/'], .number-card, [class*='number']"):
        text     = item.get_text(" ", strip=True)
        number   = _extract_number(text)
        if not number:
            continue
        flag_tag = item.select_one("[class*='flag'], [class*='country'], [title]")
        country  = (flag_tag.get("title") or flag_tag.get_text(strip=True)) if flag_tag else "Unknown"
        href     = item.get("href", "")
        link     = ("https://quackr.io" + href) if href.startswith("/") else href or base_url
        entries.append(NumberEntry(number=number, country=country, source="quackr.io", link=link))
    return entries


def parse_onlinesim(html: str, base_url: str) -> list[NumberEntry]:
    soup    = BeautifulSoup(html, "html.parser")
    entries = []
    seen_n  = set()
    for card in soup.select("[class*='number'], [class*='phone'], .item"):
        raw    = card.get_text(" ", strip=True)
        number = _extract_number(raw)
        if not number or number in seen_n:
            continue
        seen_n.add(number)
        cnt_tag  = card.select_one("[class*='country'], [class*='flag']")
        link_tag = card.select_one("a[href]")
        country  = cnt_tag.get_text(strip=True) if cnt_tag else "Unknown"
        href     = link_tag["href"] if link_tag else ""
        link     = ("https://onlinesim.io" + href) if href.startswith("/") else href or base_url
        entries.append(NumberEntry(number=number, country=country, source="onlinesim.io", link=link))
    if not entries:
        for m in re.finditer(r'\+\d{7,15}', soup.get_text()):
            n = m.group(0)
            if n not in seen_n:
                seen_n.add(n)
                entries.append(NumberEntry(number=n, source="onlinesim.io", link=base_url))
    return entries


# ─── TARGETS ──────────────────────────────────────────────────────────────────
TARGETS: list[Target] = [
    Target("receive-smss.com", "https://receive-smss.com/",            0x57F287, parse_receive_smss),
    Target("receivesms.co",    "https://www.receivesms.co/",            0x5865F2, parse_receivesms_co),
    Target("smsfree24.com",    "https://smsfree24.com/",                0xFEE75C, parse_smsfree24),
    Target("quackr.io",        "https://quackr.io/temporary-numbers",   0xEB459E, parse_quackr),
    Target("onlinesim.io",     "https://onlinesim.io/numbers",          0xED4245, parse_onlinesim),
]


# ─── PERSISTENCIA ─────────────────────────────────────────────────────────────
def load_seen_local() -> dict[str, set[str]]:
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return {k: set(v) for k, v in raw.items()}
    except (json.JSONDecodeError, IOError):
        return {}

def save_seen_local(seen: dict[str, set[str]]) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({k: list(v) for k, v in seen.items()}, f, ensure_ascii=False, indent=2)

async def load_seen_redis(rc: aioredis.Redis) -> dict[str, set[str]]:
    raw = await rc.get(REDIS_KEY)
    if not raw:
        return {}
    data = json.loads(raw)
    return {k: set(v) for k, v in data.items()}

async def save_seen_redis(rc: aioredis.Redis, seen: dict[str, set[str]]) -> None:
    await rc.set(REDIS_KEY, json.dumps({k: list(v) for k, v in seen.items()}))


# ─── WEBHOOK ──────────────────────────────────────────────────────────────────
async def send_webhook(session: aiohttp.ClientSession, entry: NumberEntry, color: int) -> None:
    now     = datetime.now(timezone.utc).isoformat()
    payload = {
        "username": BOT_NAME,
        "embeds": [{
            "title"      : "📱 Número nuevo detectado",
            "url"        : entry.link,
            "color"      : color,
            "description": f"### `{entry.number}`\n**País:** {entry.country}\n**Fuente:** [{entry.source}]({entry.link})",
            "fields"     : [
                {"name": "🌍 País",   "value": entry.country,            "inline": True},
                {"name": "📞 Número", "value": f"`{entry.number}`",      "inline": True},
                {"name": "🔗 Link",   "value": f"[Abrir]({entry.link})", "inline": True},
            ],
            "footer"   : {"text": f"vnum_monitor • {entry.source}"},
            "timestamp": now,
        }]
    }
    for attempt in range(3):
        async with session.post(WEBHOOK_URL, json=payload) as resp:
            if resp.status == 204:
                return
            if resp.status == 429:
                data        = await resp.json()
                retry_after = data.get("retry_after", 2)
                logging.warning(f"Rate limit — esperando {retry_after}s")
                await asyncio.sleep(retry_after)
                continue
            logging.error(f"Webhook HTTP {resp.status} en intento {attempt+1}")
            break


# ─── SCRAPER ──────────────────────────────────────────────────────────────────
async def scrape_target(session: aiohttp.ClientSession, target: Target, seen: dict[str, set[str]]) -> list[NumberEntry]:
    headers = {
        "User-Agent"     : random.choice(USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept"         : "text/html,application/xhtml+xml,*/*;q=0.8",
        "Referer"        : "https://www.google.com/",
    }
    try:
        async with session.get(target.url, headers=headers, timeout=aiohttp.ClientTimeout(total=20), allow_redirects=True) as resp:
            if resp.status != 200:
                logging.warning(f"[{target.name}] HTTP {resp.status}")
                return []
            html = await resp.text(errors="replace")
    except asyncio.TimeoutError:
        logging.warning(f"[{target.name}] timeout")
        return []
    except Exception as exc:
        logging.error(f"[{target.name}] fetch error: {exc}")
        return []

    try:
        entries = target.parse(html, target.url)
    except Exception as exc:
        logging.error(f"[{target.name}] parse error: {exc}")
        return []

    bucket = seen.setdefault(target.name, set())
    new    = [e for e in entries if e.number not in bucket]
    for e in new:
        bucket.add(e.number)
    return new


# ─── LOOP ─────────────────────────────────────────────────────────────────────
async def main() -> None:
    logging.basicConfig(
        level   = logging.INFO,
        format  = "[%(asctime)s] %(levelname)s — %(message)s",
        datefmt = "%H:%M:%S",
    )

    if WEBHOOK_URL == "PEGA_TU_WEBHOOK_AQUI":
        logging.error("DISCORD_WEBHOOK no configurado — setealo en las env vars.")
        while True:
            await asyncio.sleep(60)

    redis_client: aioredis.Redis | None = None
    if REDIS_URL:
        redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
        logging.info("Storage: Redis")
        seen = await load_seen_redis(redis_client)
    else:
        logging.info("Storage: JSON local (se resetea en redeploy)")
        seen = load_seen_local()

    is_first_run = not bool(seen)
    if is_first_run:
        logging.info("Primera ejecución — aprendiendo estado inicial (sin notificar)...")

    connector = aiohttp.TCPConnector(limit=10, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        while True:
            logging.info(f"── Ciclo {datetime.now().strftime('%H:%M:%S')}")
            results = await asyncio.gather(
                *[scrape_target(session, t, seen) for t in TARGETS],
                return_exceptions=True,
            )
            new_total = 0
            for target, new_entries in zip(TARGETS, results):
                if isinstance(new_entries, Exception):
                    logging.error(f"[{target.name}] {new_entries}")
                    continue
                if is_first_run:
                    logging.info(f"[{target.name}] {len(seen.get(target.name, set()))} en caché")
                    continue
                for entry in new_entries:
                    logging.info(f"[NUEVO] {entry.number} ({entry.country}) ← {entry.source}")
                    await send_webhook(session, entry, target.color)
                    await asyncio.sleep(0.6)
                    new_total += 1
            if is_first_run:
                logging.info("Estado cargado. Monitoreando.")
                is_first_run = False
            else:
                logging.info(f"── {new_total} nuevo(s)")
            if redis_client:
                await save_seen_redis(redis_client, seen)
            else:
                save_seen_local(seen)
            await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    _start_health_server()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Detenido.")
    except Exception as exc:
        logging.error(f"Error fatal: {exc}")
    # mantener el proceso vivo para back4app aunque el loop falle
    while True:
        import time; time.sleep(60)
