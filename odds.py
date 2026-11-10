"""Sugestão automática de ODDs a partir da classificação dos campeonatos (ESPN).

Como funciona (modelo de Poisson, o mais usado em análise de futebol):
1. Para cada time: força de ataque = gols feitos por jogo / média do campeonato;
   força de defesa = gols sofridos por jogo / média do campeonato.
   Com poucos jogos, a força é puxada para a média (1.0), para não exagerar.
2. Gols esperados no jogo:
   mandante  = média × ataque do mandante × defesa do visitante × vantagem de casa
   visitante = média × ataque do visitante × defesa do mandante × desvantagem fora
3. Com a distribuição de Poisson calculamos a chance de cada placar (0x0, 1x0, ...)
   e somamos para ter as chances de vitória do mandante, empate e vitória do visitante.
   O Poisson puro exagera o favorito e subestima o empate, então misturamos 70% do modelo
   com 30% da média histórica do futebol (mandante 46%, empate 27%, visitante 27%).
   Times de campeonatos diferentes (ex: Série A x Série B na Copa do Brasil) recebem
   um peso pelo nível do campeonato de onde vêm.
4. ODD = 1 / (chance × (1 + margem)). A margem faz o bolão, no longo prazo,
   não pagar mais JC do que recebe (como a margem das casas de apostas).
   A ODD de placar exato usa a chance do placar mais provável do jogo.

Se a ESPN não responder ou o time não estiver na tabela, o time é tratado como "médio".
"""
import json
import math
import threading
import time
import urllib.request

from times import LIGAS

TABELA_URL = "https://site.api.espn.com/apis/v2/sports/soccer/{liga}/standings"
CACHE_SEGUNDOS = 6 * 60 * 60

MARGEM = 0.08            # 8% de margem da casa
VANTAGEM_CASA = 1.15     # mandante faz ~15% mais gols que o esperado
DESVANTAGEM_FORA = 0.92  # visitante faz ~8% menos
MEDIA_PADRAO = 1.30      # gols por time por jogo, se a tabela não tiver dados
JOGOS_CONFIANCA = 5      # com 5 jogos, metade do peso é do time e metade da média
PESO_MODELO = 0.70       # 70% modelo + 30% média histórica (mandante/empate/visitante)
MEDIA_HISTORICA = (0.46, 0.27, 0.27)
# Nível dos campeonatos (só usado quando os dois times vêm de campeonatos diferentes)
NIVEL_LIGA = {"bra.2": 0.82}
MAX_GOLS = 10
ODD_MIN, ODD_MAX = 1.05, 50.0

# Onde procurar times que não estão na tabela do campeonato do jogo
# (ex: Copa do Brasil tem times da Série B; Libertadores tem times argentinos)
LIGAS_EXTRAS = ["bra.1", "bra.2", "arg.1", "eng.1", "esp.1", "ita.1", "ger.1", "fra.1", "por.1"]

_cache: dict[str, tuple[float, dict]] = {}
_trava = threading.Lock()


def _stat(entrada: dict, nome: str) -> float:
    for s in entrada.get("stats") or []:
        if s.get("name") == nome:
            try:
                return float(s.get("value") or 0)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def tabela(liga: str) -> dict:
    """{'times': {id: {...}}, 'media': gols por time por jogo} de um campeonato (cache de 6h)."""
    with _trava:
        guardado = _cache.get(liga)
        if guardado and time.time() - guardado[0] < CACHE_SEGUNDOS:
            return guardado[1]

    req = urllib.request.Request(TABELA_URL.format(liga=liga), headers={"User-Agent": "energia-carvalho-bolao/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            dados = json.load(resp)
    except Exception:
        return {"times": {}, "media": MEDIA_PADRAO}

    times, gols_total, jogos_total = {}, 0.0, 0.0
    for grupo in dados.get("children") or []:  # Libertadores tem vários grupos; pontos corridos tem um só
        for e in (grupo.get("standings") or {}).get("entries") or []:
            t = e.get("team") or {}
            if not t.get("id"):
                continue
            jogos = _stat(e, "gamesPlayed")
            gf, gc = _stat(e, "pointsFor"), _stat(e, "pointsAgainst")
            times[str(t["id"])] = {
                "nome": t.get("displayName") or "",
                "posicao": int(_stat(e, "rank")) or None,
                "jogos": int(jogos),
                "gols_pro": int(gf),
                "gols_contra": int(gc),
                "pontos": int(_stat(e, "points")),
            }
            gols_total += gf
            jogos_total += jogos

    media = gols_total / jogos_total if jogos_total else MEDIA_PADRAO
    resultado = {"times": times, "media": media}
    if times:
        with _trava:
            _cache[liga] = (time.time(), resultado)
    return resultado


def _achar_time(time_id: str | None, liga: str) -> tuple[dict | None, float, str | None]:
    """Procura o time na tabela do campeonato do jogo e, se não achar, nas outras."""
    if not time_id:
        return None, MEDIA_PADRAO, None
    ordem = [liga] + [l for l in LIGAS_EXTRAS if l != liga]
    for l in ordem:
        if l not in LIGAS:
            continue
        t = tabela(l)
        if time_id in t["times"]:
            return t["times"][time_id], t["media"], l
    return None, MEDIA_PADRAO, None


def _forca(gols: int, jogos: int, media: float) -> float:
    """Força relativa (1.0 = média), puxada para 1.0 quando o time tem poucos jogos."""
    if jogos <= 0 or media <= 0:
        return 1.0
    bruta = (gols / jogos) / media
    peso = jogos / (jogos + JOGOS_CONFIANCA)
    return peso * bruta + (1 - peso) * 1.0


def _poisson(k: int, lam: float) -> float:
    return math.exp(-lam) * lam ** k / math.factorial(k)


def _odd(prob: float) -> float:
    if prob <= 0:
        return ODD_MAX
    return round(min(ODD_MAX, max(ODD_MIN, 1 / (prob * (1 + MARGEM)))), 2)


def sugerir(liga: str, time_a_id: str | None, time_b_id: str | None) -> dict:
    """ODDs sugeridas para mandante (A) x visitante (B)."""
    liga = liga if liga in LIGAS else "bra.1"
    a, media_a, liga_a = _achar_time(time_a_id, liga)
    b, media_b, liga_b = _achar_time(time_b_id, liga)
    media = tabela(liga)["media"] if liga_a or liga_b else MEDIA_PADRAO

    atk_a = _forca(a["gols_pro"], a["jogos"], media_a) if a else 1.0
    def_a = _forca(a["gols_contra"], a["jogos"], media_a) if a else 1.0
    atk_b = _forca(b["gols_pro"], b["jogos"], media_b) if b else 1.0
    def_b = _forca(b["gols_contra"], b["jogos"], media_b) if b else 1.0

    # Série A x Série B (ou outro nível): o time do campeonato mais fraco ataca menos e defende pior
    if liga_a and liga_b and liga_a != liga_b:
        nivel_a, nivel_b = NIVEL_LIGA.get(liga_a, 1.0), NIVEL_LIGA.get(liga_b, 1.0)
        atk_a, def_a = atk_a * nivel_a, def_a / nivel_a
        atk_b, def_b = atk_b * nivel_b, def_b / nivel_b

    gols_a = media * atk_a * def_b * VANTAGEM_CASA
    gols_b = media * atk_b * def_a * DESVANTAGEM_FORA

    p_casa = p_empate = p_fora = 0.0
    melhor_prob, melhor_placar = 0.0, (0, 0)
    for i in range(MAX_GOLS + 1):
        pi = _poisson(i, gols_a)
        for j in range(MAX_GOLS + 1):
            p = pi * _poisson(j, gols_b)
            if i > j:
                p_casa += p
            elif i == j:
                p_empate += p
            else:
                p_fora += p
            if p > melhor_prob:
                melhor_prob, melhor_placar = p, (i, j)

    total = p_casa + p_empate + p_fora  # ~1.0 (o que passa de 10 gols é desprezível)
    p_casa, p_empate, p_fora = p_casa / total, p_empate / total, p_fora / total
    h_casa, h_empate, h_fora = MEDIA_HISTORICA
    p_casa = PESO_MODELO * p_casa + (1 - PESO_MODELO) * h_casa
    p_empate = PESO_MODELO * p_empate + (1 - PESO_MODELO) * h_empate
    p_fora = PESO_MODELO * p_fora + (1 - PESO_MODELO) * h_fora

    def resumo(t, liga_t):
        if not t:
            return None
        return {**t, "liga": LIGAS.get(liga_t, liga_t)}

    return {
        "odd_casa": _odd(p_casa),
        "odd_empate": _odd(p_empate),
        "odd_fora": _odd(p_fora),
        "odd_placar": _odd(melhor_prob),
        "prob_casa": round(p_casa * 100, 1),
        "prob_empate": round(p_empate * 100, 1),
        "prob_fora": round(p_fora * 100, 1),
        "placar_provavel": f"{melhor_placar[0]} x {melhor_placar[1]}",
        "gols_esperados_a": round(gols_a, 2),
        "gols_esperados_b": round(gols_b, 2),
        "time_a": resumo(a, liga_a),
        "time_b": resumo(b, liga_b),
    }
