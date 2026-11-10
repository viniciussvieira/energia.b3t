"""Calendário e placares de jogos, usando o placar público (não oficial) da ESPN.

- buscar_proximos(liga, dias): jogos que ainda vão começar, para o admin importar como bolão.
- placar_do_jogo(liga, espn_id, data): placar de um jogo, para sugerir o resultado.

Se a ESPN cair ou mudar o formato, as funções só voltam vazias: o admin continua
podendo criar bolões e lançar resultados na mão.
"""
import json
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from times import LIGAS, PREFIXO_ESCUDO

PLACAR_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/{liga}/scoreboard?dates={dia}"
CACHE_SEGUNDOS = 10 * 60   # calendário e placares mudam pouco; evita bater na ESPN a cada clique
MAX_DIAS = 30

_cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}
_trava = threading.Lock()


def _ler_data(texto: str) -> datetime | None:
    """'2026-10-23T00:30Z' -> datetime UTC sem fuso (como guardamos no banco)."""
    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
    except (AttributeError, ValueError):
        return None


def _gols(valor) -> int | None:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _converter_evento(ev: dict, liga: str) -> dict | None:
    try:
        comp = ev["competitions"][0]
        times = {c.get("homeAway"): c for c in comp["competitors"]}
        casa, fora = times["home"], times["away"]
    except (KeyError, IndexError, TypeError):
        return None
    data = _ler_data(ev.get("date") or comp.get("date"))
    status = (ev.get("status") or {}).get("type") or {}
    if not ev.get("id") or data is None:
        return None

    def escudo(c):
        url = (c.get("team") or {}).get("logo")
        return url if url and url.startswith(PREFIXO_ESCUDO) else None

    return {
        "espn_id": str(ev["id"]),
        "liga": liga,
        "liga_nome": LIGAS[liga],
        "data": data,
        "time_a": (casa.get("team") or {}).get("displayName") or "Mandante",
        "escudo_a": escudo(casa),
        "time_b": (fora.get("team") or {}).get("displayName") or "Visitante",
        "escudo_b": escudo(fora),
        "estado": status.get("state") or "pre",          # "pre", "in" ou "post"
        "encerrado": bool(status.get("completed")),
        "situacao": status.get("shortDetail") or status.get("detail") or "",
        "placar_a": _gols(casa.get("score")),
        "placar_b": _gols(fora.get("score")),
    }


def _jogos_do_dia(liga: str, dia: str) -> list[dict]:
    """Jogos de um dia (AAAAMMDD) num campeonato, com cache de 10 minutos."""
    chave = (liga, dia)
    with _trava:
        guardado = _cache.get(chave)
        if guardado and time.time() - guardado[0] < CACHE_SEGUNDOS:
            return guardado[1]

    req = urllib.request.Request(PLACAR_URL.format(liga=liga, dia=dia), headers={"User-Agent": "energia-carvalho-bolao/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            eventos = json.load(resp).get("events") or []
    except Exception:
        return []  # falhou: não guarda no cache, tenta de novo na próxima

    jogos = [j for j in (_converter_evento(ev, liga) for ev in eventos) if j]
    with _trava:
        _cache[chave] = (time.time(), jogos)
    return jogos


def _dias(inicio: datetime, quantidade: int) -> list[str]:
    return [(inicio + timedelta(days=i)).strftime("%Y%m%d") for i in range(quantidade)]


def buscar_proximos(liga: str, dias: int = 14) -> list[dict]:
    """Jogos que ainda não começaram, do mais próximo para o mais distante."""
    if liga not in LIGAS:
        return []
    dias = max(1, min(dias, MAX_DIAS))
    agora = datetime.utcnow()
    # Começa um dia antes: o "dia" da ESPN pode não bater com o UTC
    lista_dias = _dias(agora - timedelta(days=1), dias + 1)
    with ThreadPoolExecutor(max_workers=8) as pool:
        por_dia = list(pool.map(lambda d: _jogos_do_dia(liga, d), lista_dias))

    vistos, jogos = set(), []
    for lista in por_dia:
        for j in lista:
            if j["espn_id"] in vistos:
                continue
            vistos.add(j["espn_id"])
            if j["estado"] == "pre" and j["data"] > agora:
                jogos.append(j)
    return sorted(jogos, key=lambda j: j["data"])


def placar_do_jogo(liga: str | None, espn_id: str | None, data: datetime | None) -> dict | None:
    """Situação atual de um jogo importado (para sugerir o placar final)."""
    if not liga or not espn_id or liga not in LIGAS or data is None:
        return None
    for dia in _dias(data - timedelta(days=1), 3):
        for j in _jogos_do_dia(liga, dia):
            if j["espn_id"] == espn_id:
                return j
    return None

