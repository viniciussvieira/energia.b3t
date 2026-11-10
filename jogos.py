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

# Fases do mata-mata como a ESPN escreve -> português
FASES = {
    "first stage": "1ª fase", "second stage": "2ª fase", "third stage": "3ª fase",
    "first round": "1ª fase", "second round": "2ª fase", "third round": "3ª fase",
    "fourth round": "4ª fase", "fifth round": "5ª fase",
    "group": "Fase de grupos", "group stage": "Fase de grupos",
    "knockout round playoffs": "Playoffs", "playoffs": "Playoffs", "playoff round": "Playoffs",
    "rd of 32": "16 avos de final", "round of 32": "16 avos de final",
    "rd of 16": "Oitavas de final", "round of 16": "Oitavas de final",
    "quarterfinals": "Quartas de final", "quarter-finals": "Quartas de final",
    "semifinals": "Semifinal", "semi-finals": "Semifinal",
    "third place": "Disputa de 3º lugar", "final": "Final",
}
JOGO_MATA = {1: "Ida", 2: "Volta"}


def _fase(comp: dict, ev: dict) -> str | None:
    """'Semifinal · Ida' para jogos de mata-mata; None para pontos corridos."""
    titulo = ((comp.get("series") or {}).get("title") or "").strip()
    if not titulo:
        slug = ((ev.get("season") or {}).get("slug") or "").replace("-", " ").strip()
        titulo = slug if slug.lower() in FASES else ""
    if not titulo:
        return None
    fase = FASES.get(titulo.lower(), titulo)
    if titulo.lower().startswith("group "):  # "Group A" -> "Grupo A"
        fase = "Grupo " + titulo[6:]
    perna = JOGO_MATA.get((comp.get("leg") or {}).get("value"))
    return f"{fase} · {perna}" if perna else fase
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
        "time_a_id": str((casa.get("team") or {}).get("id") or ""),
        "time_b_id": str((fora.get("team") or {}).get("id") or ""),
        "fase": _fase(comp, ev),
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
    jogos.sort(key=lambda j: j["data"])
    _sugerir_rodadas(liga, jogos)
    return jogos


def _sugerir_rodadas(liga: str, jogos: list[dict]) -> None:
    """Preenche j['rodada'] ('Rodada 35', 'Semifinal · Ida'...).

    Mata-mata: a ESPN informa a fase. Pontos corridos: a ESPN não informa a rodada, então
    calculamos pela tabela: jogos já disputados pelo time + jogos dele que vêm antes na lista + 1.
    Usamos o maior entre os dois times (o outro pode ter um jogo adiado). É só uma sugestão:
    o admin pode corrigir.
    """
    from odds import tabela  # import aqui para evitar import circular
    tab = None
    proximos_do_time: dict[str, int] = {}
    for j in jogos:
        if j["fase"]:
            j["rodada"] = j["fase"]
            continue
        if tab is None:
            tab = tabela(liga)["times"]
        candidatos = []
        for tid in (j["time_a_id"], j["time_b_id"]):
            if tid in tab:
                candidatos.append(tab[tid]["jogos"] + proximos_do_time.get(tid, 0) + 1)
            proximos_do_time[tid] = proximos_do_time.get(tid, 0) + 1
        j["rodada"] = f"Rodada {max(candidatos)}" if candidatos else None


def placar_do_jogo(liga: str | None, espn_id: str | None, data: datetime | None) -> dict | None:
    """Situação atual de um jogo importado (para sugerir o placar final)."""
    if not liga or not espn_id or liga not in LIGAS or data is None:
        return None
    for dia in _dias(data - timedelta(days=1), 3):
        for j in _jogos_do_dia(liga, dia):
            if j["espn_id"] == espn_id:
                return j
    return None

