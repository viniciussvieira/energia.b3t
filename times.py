"""Busca de times com escudo usando a lista pública (não oficial) da ESPN.

Baixamos a lista de times de alguns campeonatos e guardamos em memória por 24h.
Se a ESPN estiver fora do ar ou mudar o formato, a busca só volta vazia:
o bolão continua funcionando, apenas sem escudos.
"""
import json
import threading
import time
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/{liga}/teams"
PREFIXO_ESCUDO = "https://a.espncdn.com/"  # só aceitamos imagens desse endereço

LIGAS = {
    "bra.1": "Brasileirão Série A",
    "bra.2": "Brasileirão Série B",
    "bra.copa_do_brazil": "Copa do Brasil",
    "conmebol.libertadores": "Libertadores",
    "conmebol.sudamericana": "Sul-Americana",
    "eng.1": "Premier League",
    "esp.1": "La Liga",
    "ita.1": "Serie A (Itália)",
    "ger.1": "Bundesliga",
    "fra.1": "Ligue 1",
    "por.1": "Liga Portugal",
    "arg.1": "Liga Argentina",
    "fifa.world": "Seleções",
}

CACHE_SEGUNDOS = 60 * 60 * 24
_cache = {"times": [], "atualizado_em": 0.0}
_trava = threading.Lock()


def _normalizar(texto: str) -> str:
    """'Grêmio' -> 'gremio' (sem acento e minúsculo) para a busca ignorar acentos."""
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in sem_acento if not unicodedata.combining(c)).lower().strip()


def _baixar_liga(liga: str) -> list[dict]:
    req = urllib.request.Request(ESPN_URL.format(liga=liga), headers={"User-Agent": "energia-carvalho-bolao/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            dados = json.load(resp)
        itens = dados["sports"][0]["leagues"][0]["teams"]
    except Exception:
        return []

    times = []
    for item in itens:
        t = item.get("team", {})
        logos = t.get("logos") or []
        escudo = logos[0].get("href") if logos else None
        if not t.get("id") or not t.get("displayName"):
            continue
        times.append({
            "id": str(t["id"]),
            "nome": t["displayName"],
            "escudo": escudo if escudo and escudo.startswith(PREFIXO_ESCUDO) else None,
            "liga": LIGAS[liga],
            "_busca": " ".join(_normalizar(t.get(campo, "")) for campo in
                               ("displayName", "shortDisplayName", "location", "abbreviation", "name")),
        })
    return times


def _todos_os_times() -> list[dict]:
    with _trava:
        if _cache["times"] and time.time() - _cache["atualizado_em"] < CACHE_SEGUNDOS:
            return _cache["times"]

        with ThreadPoolExecutor(max_workers=6) as pool:
            listas = list(pool.map(_baixar_liga, LIGAS))

        vistos, times = set(), []
        for lista in listas:  # a ordem de LIGAS dá prioridade aos campeonatos brasileiros
            for t in lista:
                if t["id"] not in vistos:
                    vistos.add(t["id"])
                    times.append(t)

        if times:  # se a ESPN falhar, não apagamos o que já tínhamos
            _cache.update(times=times, atualizado_em=time.time())
        return _cache["times"]


def buscar_times(termo: str, limite: int = 10) -> list[dict]:
    termo = _normalizar(termo)
    if len(termo) < 2:
        return []
    times = _todos_os_times()
    # Primeiro quem começa com o termo, depois quem só contém
    comeca = [t for t in times if any(p.startswith(termo) for p in t["_busca"].split()) or t["_busca"].startswith(termo)]
    ids_comeca = {t["id"] for t in comeca}
    contem = [t for t in times if termo in t["_busca"] and t["id"] not in ids_comeca]
    return [{k: v for k, v in t.items() if k != "_busca"} for t in (comeca + contem)[:limite]]


def pre_carregar_times() -> None:
    """Baixa a lista em segundo plano ao subir o servidor, para a primeira busca ser rápida."""
    threading.Thread(target=_todos_os_times, daemon=True).start()
