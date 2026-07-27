"""
KPIS OFICIAIS — validador determinístico dos indicadores macro.

O Gemini continua sendo a IA de BUSCA (clipping, sinais, editorial). Mas os
NÚMEROS dos indicadores macro não podem depender do modelo: aqui eles são
buscados direto nas APIs oficiais (BCB/SGS, BCB/Olinda e IBGE/SIDRA).

REGRA DURA: nenhum número macro sai daqui sem fonte oficial. Se todas as fontes
de um indicador falharem, ele sai marcado como INDISPONÍVEL — e o motor herda o
último valor oficial conhecido, com a data de referência à vista. O valor do
Gemini NUNCA é publicado como indicador. Essa regra existe porque o contrário
foi tentado: entre as semanas 29 e 31 de 2026 a API do BCB parou de responder de
dentro do runner, o erro foi engolido em silêncio, e o portal publicou Selic de
10,75% (real: 14,25%), câmbio R$ 5,25 (real: R$ 5,07) e IPCA 0,35% (real: 0,16%)
— todos inventados pelo modelo, e ainda atribuídos a "BCB/SGS" na interface.

Cada indicador traz, quando faz sentido: variação no mês, ACUMULADO NO ANO e 12 meses.

Sem dependências novas: usa só a biblioteca padrão (urllib).
Séries verificadas contra a realidade conhecida (jul/2026):
  SELIC meta SGS 432 (fallback efetiva 1178)
  Câmbio PTAX venda SGS 1 (fallback Olinda/PTAX — host distinto do SGS)
  IPCA SIDRA 1737 v63(mês)/v69(ano)/v2265(12m) — FONTE PRIMÁRIA, o IBGE publica
       o índice; SGS 433/13522 é só espelho e vira fallback
  Desemprego PNAD 6381 v4099 · Varejo PMC 8880 v11708(mês)/v11710(ano)
  PIM 8888 v11601(mês)/v11602(ano) · IPP 6903 v1396(mês)/v1395(ano)
"""
import json
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta

_UA = {"User-Agent": "Mozilla/5.0 (nexos-kpi-oficial)"}
_MABBR = ["", "jan", "fev", "mar", "abr", "mai", "jun",
          "jul", "ago", "set", "out", "nov", "dez"]
_MES = {"janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4,
        "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
        "outubro": 10, "novembro": 11, "dezembro": 12,
        "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
        "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12}


# ─────────────────────────── HTTP com cache + retry curto ───────────────────────────
# Cache por URL: a mesma série é reaproveitada entre semanas (backfill chama a
# coleta várias vezes). Guarda até falhas (None) para não repetir retries lentos.
_CACHE = {}


def _get(url, tries=3):
    """GET com cache e retry curto. Devolve None quando a fonte não responde —
    e DIZ isso no log. O silêncio aqui foi o que deixou o portal publicar Selic
    de 10,75% por três semanas: a API do BCB parou de responder de dentro do
    runner, o erro foi engolido, e o número inventado passou como se fosse dado."""
    if url in _CACHE:
        return _CACHE[url]
    host = urllib.parse.urlsplit(url).netloc
    erro = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=12) as r:
                t = r.read().decode("utf-8")
            s = t.strip()
            if s.startswith("[") or s.startswith("{"):
                j = json.loads(s)
                _CACHE[url] = j
                return j
            erro = f"resposta não-JSON ({s[:60]!r})"
        except Exception as e:
            erro = f"{type(e).__name__}: {e}"
        if i < tries - 1:
            time.sleep(1.0 * (i + 1))
    print(f"[kpis] FONTE INDISPONÍVEL: {host} após {tries} tentativas — {erro}")
    print(f"[kpis]   url: {url}")
    _CACHE[url] = None
    return None


# Janela histórica das séries do BCB, em anos. Larga de propósito: uma requisição
# por série atende TODAS as semanas do portal (o backfill filtra por data), em vez
# de uma requisição por semana.
_JANELA_ANOS = 3


def _bcb(cod, n=None):
    """Série BCB/SGS diária → lista [(date, valor_float)] mais antigo→recente.

    Consulta por INTERVALO (dataInicial/dataFinal), não por 'ultimos/N'. O
    endpoint /ultimos/ passou a responder HTTP 400 acima de ~20 observações
    (verificado em 27/07/2026 nas séries 432 e 1), e todas as chamadas daqui
    pediam de 24 a 60. Foi essa mudança — escondida pelo `except` silencioso do
    _get — que tirou Selic, câmbio e IPCA do ar entre as semanas 29 e 31 de 2026.

    `n` é mantido só por compatibilidade de assinatura: a janela é sempre larga."""
    hoje = date.today()
    ini = date(hoje.year - _JANELA_ANOS, 1, 1)
    j = _get(f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{cod}/dados?formato=json"
             f"&dataInicial={ini.strftime('%d/%m/%Y')}"
             f"&dataFinal={hoje.strftime('%d/%m/%Y')}")
    out = []
    for o in (j or []):
        try:
            d, m, y = (int(x) for x in o["data"].split("/"))
            out.append((date(y, m, d), float(str(o["valor"]).replace(",", "."))))
        except (ValueError, KeyError, TypeError):
            continue
    return sorted(out)


def _bcb_mensal(cod, n=24):
    """Série BCB/SGS mensal → mesmo formato do SIDRA [(ano, mes, valor, periodo)]."""
    return [(d.year, d.month, v, f"{_MABBR[d.month]}/{str(d.year)[2:]}")
            for (d, v) in _bcb(cod)]


def _olinda_ptax(ref, dias=12):
    """PTAX venda pelo Olinda — host DIFERENTE do SGS (olinda.bcb.gov.br, não
    api.bcb.gov.br). Existe porque foi exatamente o SGS que ficou inalcançável do
    runner enquanto o resto do BCB seguia no ar: uma segunda porta para o mesmo
    dado oficial. Mesmo formato de _bcb: [(date, valor)] antigo→recente."""
    ini = (ref - timedelta(days=dias)).strftime("%m-%d-%Y")
    fim = ref.strftime("%m-%d-%Y")
    url = ("https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
           f"CotacaoDolarPeriodo(dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
           f"?@dataInicial='{ini}'&@dataFinalCotacao='{fim}'"
           "&$format=json&$select=cotacaoVenda,dataHoraCotacao")
    j = _get(url)
    out = []
    for o in ((j or {}).get("value") or []):
        try:
            d = date.fromisoformat(str(o["dataHoraCotacao"])[:10])
            out.append((d, float(o["cotacaoVenda"])))
        except (ValueError, KeyError, TypeError):
            continue
    return sorted(out)


def _sidra_ipca(n=36):
    """IPCA direto do IBGE (tabela 1737): mês, acumulado no ano e 12 meses.
    É a FONTE PRIMÁRIA — o IBGE é quem calcula e publica o IPCA; o SGS 433/13522
    apenas espelha. Buscar no espelho era um salto desnecessário, e foi por ele
    que o IPCA caiu junto quando o SGS parou. Devolve dict de listas no formato
    do SIDRA [(ano, mes, valor, periodo)]."""
    j = _get("https://apisidra.ibge.gov.br/values/t/1737/n1/all/v/63,69,2265"
             f"/p/last%20{n}/h/n")
    por_var = {"63": [], "69": [], "2265": []}
    for x in (j or []):
        cod, v = str(x.get("D2C", "")), x.get("V", "")
        if cod not in por_var or v in ("...", "..", "-", None):
            continue
        try:
            per = str(x.get("D3C", ""))          # AAAAMM
            y, m = int(per[:4]), int(per[4:6])
            por_var[cod].append((y, m, float(str(v).replace(",", ".")),
                                 f"{_MABBR[m]}/{str(y)[2:]}"))
        except (ValueError, TypeError):
            continue
    return {"mes": sorted(por_var["63"]), "ano": sorted(por_var["69"]),
            "doze": sorted(por_var["2265"])}


def _sidra(path):
    """SIDRA → lista [(ano, mes, valor_float, periodo_str)] mais antigo→recente."""
    j = _get(f"https://apisidra.ibge.gov.br/values{path}/h/n")
    out = []
    for x in (j or []):
        per = x.get("D3N", "")
        v = x.get("V", "")
        if v in ("...", "..", "-", None):
            continue
        try:
            parts = per.split(" ")
            ano = int(parts[-1])
            token = parts[0].split("-")[-1].lower()
            mes = _MES.get(token, 1)
            out.append((ano, mes, float(str(v).replace(",", ".")), per))
        except (ValueError, IndexError):
            continue
    return out


# ─────────────────────── seleção por data de referência ───────────────────────
def _rel_date(y, m, add_m, day):
    """Data estimada de DIVULGAÇÃO de um dado mensal de referência (y,m)."""
    total = (m - 1) + add_m
    yy = y + total // 12
    mm = total % 12 + 1
    return date(yy, mm, min(day, 28))


def _pick_mensal(serie, ref, add_m, day):
    """Último obs mensal já DIVULGADO até a data ref (respeita o calendário)."""
    best = None
    for (y, m, val, per) in serie:
        if _rel_date(y, m, add_m, day) <= ref:
            if best is None or (y, m) > (best[0], best[1]):
                best = (y, m, val, per)
    return best


def _pick_diario(serie, ref):
    best = None
    for (d, val) in serie:
        if d <= ref and (best is None or d > best[0]):
            best = (d, val)
    return best


def _br(v, dec=2):
    return f"{v:.{dec}f}".replace(".", ",")


def _cor(cur, prev, lower_better):
    if prev is None or cur == prev:
        return "neutral"
    return "up" if ((cur < prev) == lower_better) else "down"


def _ipca_acum_ano(serie_mensal, ano, mes_ref):
    """Acumulado no ano do IPCA: compõe as variações mensais de jan até mes_ref."""
    fator = 1.0
    achou = False
    for tup in serie_mensal:
        y, m, val = tup[0], tup[1], tup[2]
        if y == ano and 1 <= m <= mes_ref:
            fator *= (1 + val / 100.0)
            achou = True
    return (fator - 1) * 100.0 if achou else None


# ─────────────────────────── COLETA OFICIAL ───────────────────────────
def coletar_kpis(ref=None):
    """Monta os 7 KPIs macro oficiais válidos na data `ref` (default hoje).
    Retorna lista no schema canônico {label, valor, cor, sub, fonte, acum_ano?}.
    Indicador cuja fonte oficial não responder simplesmente NÃO entra na lista —
    quem chama trata a ausência (ver validar_kpis). Nunca há preenchimento por
    estimativa aqui."""
    ref = ref or date.today()

    selic = _bcb(432, 40) or _bcb(1178, 60)     # meta Copom; fallback efetiva
    cambio = _bcb(1, 60) or _olinda_ptax(ref)   # SGS; fallback Olinda (outro host)

    # IPCA: IBGE primeiro (fonte primária), SGS só como espelho de reserva.
    _ipca = _sidra_ipca(36)
    ipca_m, ipca_ano, ipca_12 = _ipca["mes"], _ipca["ano"], _ipca["doze"]
    if not ipca_m:
        print("[kpis] IPCA: SIDRA indisponível — tentando espelho BCB/SGS.")
        ipca_m, ipca_ano, ipca_12 = _bcb_mensal(433), [], _bcb_mensal(13522)
    desemp = _sidra("/t/6381/n1/all/v/4099/p/last%2036")
    varejo_m = _sidra("/t/8880/n1/all/v/11708/p/last%2036/c11046/56734")
    varejo_a = _sidra("/t/8880/n1/all/v/11710/p/last%2036/c11046/56734")
    pim_m = _sidra("/t/8888/n1/all/v/11601/p/last%2036/c544/129314")
    pim_a = _sidra("/t/8888/n1/all/v/11602/p/last%2036/c544/129314")
    ipp_m = _sidra("/t/6903/n1/all/v/1396/p/last%2036")
    ipp_a = _sidra("/t/6903/n1/all/v/1395/p/last%2036")

    out = {}

    # SELIC (meta a.a.) — tendência: juro menor é leitura positiva
    se = _pick_diario(selic, ref) if selic else None
    if se:
        prev = _pick_diario([o for o in selic if o[0] <= se[0] - timedelta(days=20)], se[0])
        out["selic"] = {"label": "SELIC", "valor": f"{_br(se[1])}% a.a.",
                        "cor": _cor(se[1], prev[1] if prev else None, True),
                        "sub": f"Taxa básica de juros · BCB/SGS · {se[0].strftime('%d/%m/%Y')}",
                        "fonte": "BCB/SGS"}

    # Câmbio (dólar PTAX venda)
    ca = _pick_diario(cambio, ref) if cambio else None
    if ca:
        prev = _pick_diario([o for o in cambio if o[0] <= ca[0] - timedelta(days=20)], ca[0])
        out["cambio"] = {"label": "Câmbio (US$)", "valor": f"R$ {_br(ca[1])}",
                         "cor": _cor(ca[1], prev[1] if prev else None, True),
                         "sub": f"Dólar PTAX venda · BCB · {ca[0].strftime('%d/%m/%Y')}",
                         "fonte": "BCB/PTAX"}

    # IPCA (mês + acum. ano + 12m)
    ip = _pick_mensal(ipca_m, ref, 1, 10) if ipca_m else None
    if ip:
        y, m, val = ip[0], ip[1], ip[2]
        prev = next((v for (yy, mm, v, *_ ) in reversed(ipca_m)
                     if (yy, mm) < (y, m)), None)
        # Acumulado no ano: prefere o PUBLICADO pelo IBGE (v69). O cálculo por
        # composição só entra se o IBGE não devolver a série — número oficial
        # ganha de número derivado, mesmo quando os dois deveriam coincidir.
        acum = next((v for (yy, mm, v, *_ ) in reversed(ipca_ano or [])
                     if (yy, mm) == (y, m)), None)
        if acum is None:
            acum = _ipca_acum_ano(ipca_m, y, m)
        i12 = next((v for (yy, mm, v, *_ ) in reversed(ipca_12) if (yy, mm) == (y, m)), None)
        meta_ipca = "meta 3,0% (teto 4,5%)"   # meta contínua de inflação (CMN)
        sub = f"Mês · {meta_ipca} · IBGE · {_MABBR[m]}/{str(y)[2:]}"
        if acum is not None:
            sub = (f"Mês · acum. ano {_br(acum)}%"
                   + (f" · 12m {_br(i12)}%" if i12 is not None else "")
                   + f" · {meta_ipca} · IBGE {_MABBR[m]}/{str(y)[2:]}")
        out["ipca"] = {"label": "IPCA", "valor": f"{_br(val)}%",
                       "cor": _cor(val, prev, True), "sub": sub, "fonte": "IBGE",
                       "acum_ano": None if acum is None else round(acum, 2)}

    # Desemprego (PNAD, trimestre móvel)
    de = _pick_mensal(desemp, ref, 1, 28) if desemp else None
    if de:
        y, m, val, per = de
        prev = next((v for (yy, mm, v, *_ ) in reversed(desemp) if (yy, mm) < (y, m)), None)
        out["desemprego"] = {"label": "Desemprego", "valor": f"{_br(val, 1)}%",
                             "cor": _cor(val, prev, True),
                             "sub": f"PNAD Contínua · IBGE · {per}", "fonte": "IBGE"}

    # Varejo PMC (mês aj. sazonal + acum. ano)
    va = _pick_mensal(varejo_m, ref, 2, 13) if varejo_m else None
    if va:
        y, m, val, _ = va
        prev = next((v for (yy, mm, v, *_ ) in reversed(varejo_m) if (yy, mm) < (y, m)), None)
        acum = next((v for (yy, mm, v, *_ ) in varejo_a if (yy, mm) == (y, m)), None)
        sub = f"Vol. de vendas m/m (aj. sazonal)" + (f" · acum. ano {_br(acum, 1)}%" if acum is not None else "") + f" · IBGE {_MABBR[m]}/{str(y)[2:]}"
        out["varejo"] = {"label": "Varejo (PMC)", "valor": f"{_br(val, 1)}%",
                         "cor": _cor(val, prev, False), "sub": sub, "fonte": "IBGE",
                         "acum_ano": None if acum is None else round(acum, 2)}

    # PIM (produção física mês + acum. ano)
    pi = _pick_mensal(pim_m, ref, 2, 4) if pim_m else None
    if pi:
        y, m, val, _ = pi
        prev = next((v for (yy, mm, v, *_ ) in reversed(pim_m) if (yy, mm) < (y, m)), None)
        acum = next((v for (yy, mm, v, *_ ) in pim_a if (yy, mm) == (y, m)), None)
        sub = f"Produção física m/m" + (f" · acum. ano {_br(acum, 1)}%" if acum is not None else "") + f" · IBGE {_MABBR[m]}/{str(y)[2:]}"
        out["pim"] = {"label": "PIM (Indústria)", "valor": f"{_br(val, 1)}%",
                      "cor": _cor(val, prev, False), "sub": sub, "fonte": "IBGE",
                      "acum_ano": None if acum is None else round(acum, 2)}

    # IPP (preços ao produtor mês + acum. ano)
    pp = _pick_mensal(ipp_m, ref, 1, 28) if ipp_m else None
    if pp:
        y, m, val, _ = pp
        prev = next((v for (yy, mm, v, *_ ) in reversed(ipp_m) if (yy, mm) < (y, m)), None)
        acum = next((v for (yy, mm, v, *_ ) in ipp_a if (yy, mm) == (y, m)), None)
        sub = f"Preços ao produtor m/m" + (f" · acum. ano {_br(acum)}%" if acum is not None else "") + f" · IBGE {_MABBR[m]}/{str(y)[2:]}"
        out["ipp"] = {"label": "IPP", "valor": f"{_br(val)}%",
                      "cor": _cor(val, prev, True), "sub": sub, "fonte": "IBGE",
                      "acum_ano": None if acum is None else round(acum, 2)}

    # ordem canônica dos 7 indicadores
    ordem = ["selic", "ipca", "cambio", "desemprego", "varejo", "pim", "ipp"]
    return [out[k] for k in ordem if k in out]


# ─────────────────── INDICADORES SETORIAIS + PRESSÕES DO IPCA ───────────────────
# Determinísticos (IBGE/SIDRA), como os macros. NÃO passam pelo Gemini.
def _cor_delta(v):
    if v is None:
        return "neutral"
    return "up" if v > 0.05 else ("down" if v < -0.05 else "neutral")


def _br_mil(v):
    """1976.37 → '1.976,37' (milhar com ponto, decimal com vírgula)."""
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _br_int(v):
    """1976.37 → '1.976' (milhar com ponto, sem centavos)."""
    return f"{round(v):,}".replace(",", ".")


def _sidra_raw(path):
    return _get(f"https://apisidra.ibge.gov.br/values{path}/h/n") or []


def _prev_mensal(serie, y, m):
    best = None
    for (yy, mm, val, per) in serie:
        if (yy, mm) < (y, m) and (best is None or (yy, mm) > (best[0], best[1])):
            best = (yy, mm, val, per)
    return best


# grupos do IPCA (classificação c315, tabela 7060) + ícone p/ o card de pressões
_IPCA_GRUPOS = [
    ("7170", "Alimentação e bebidas", "🍎"), ("7445", "Habitação", "⚡"),
    ("7486", "Artigos de residência", "🛋️"), ("7558", "Vestuário", "👕"),
    ("7625", "Transportes", "🚌"), ("7660", "Saúde e cuidados", "➕"),
    ("7712", "Despesas pessoais", "🎭"), ("7766", "Educação", "📚"),
    ("7786", "Comunicação", "📱"),
]


def coletar_ipca_grupos(ref=None):
    """'O que está pressionando o IPCA': impacto (p.p.) de cada grupo no mês.
    impacto = peso × variação / 100 (soma ≈ IPCA do mês). Fonte: IBGE/SIDRA 7060.
    Escolhe o mês já DIVULGADO (~dia 10 do mês seguinte). None se a API falhar."""
    ref = ref or date.today()
    ids = ",".join(g[0] for g in _IPCA_GRUPOS)
    raw = _sidra_raw(f"/t/7060/n1/all/v/63,66/p/last%2036/c315/{ids}")
    gmap, meses = {}, set()
    for x in raw:
        per = x.get("D3N", "")
        v = x.get("V")
        if v in ("...", "..", "-", None):
            continue
        try:
            parts = per.split(" ")
            ano = int(parts[-1])
            mes = _MES.get(parts[0].split("-")[-1].lower(), 0)
            val = float(str(v).replace(",", "."))
        except (ValueError, IndexError):
            continue
        if not mes:
            continue
        g = x.get("D4C")
        key = (ano, mes)
        meses.add(key)
        gmap.setdefault(key, {}).setdefault(g, {})
        if "peso" in x.get("D2N", "").lower():   # D2 = variável (Variação mensal / Peso mensal)
            gmap[key][g]["peso"] = val
        else:
            gmap[key][g]["var"] = val
    disp = [k for k in meses if _rel_date(k[0], k[1], 1, 10) <= ref]
    if not disp:
        return None
    ano, mes = max(disp)
    gm = gmap.get((ano, mes), {})
    grupos = []
    for gid, nome, ico in _IPCA_GRUPOS:
        o = gm.get(gid, {})
        if o.get("peso") is not None and o.get("var") is not None:
            grupos.append({"nome": nome, "ico": ico,
                           "val": round(o["peso"] * o["var"] / 100.0, 3)})
    if not grupos:
        return None
    grupos.sort(key=lambda x: x["val"], reverse=True)
    return {"ref": f"{_MABBR[mes]}/{str(ano)[2:]}", "mes": mes, "ano": ano, "grupos": grupos}


def coletar_kpis_setoriais(ref=None):
    """Indicadores setoriais (incrementais aos macros) válidos na data `ref`:
    Serviços (PMS), Construção (SINAPI custo m²) e Agro (LSPA safra de grãos).
    Cada um traz numéricos (pt/acum/flow) para o gráfico. IBGE/SIDRA, determinístico."""
    ref = ref or date.today()
    pms_m = _sidra("/t/5906/n1/all/v/11623/p/last%2036/c11046/56726")
    pms_a = _sidra("/t/5906/n1/all/v/11625/p/last%2036/c11046/56726")
    sin_c = _sidra("/t/2296/n1/all/v/48/p/last%2036")
    sin_m = _sidra("/t/2296/n1/all/v/1196/p/last%2036")
    sin_a = _sidra("/t/2296/n1/all/v/1197/p/last%2036")
    lspa = _sidra("/t/6588/n1/all/v/35/p/last%2036/c48/39428")
    out = []

    pm = _pick_mensal(pms_m, ref, 2, 13) if pms_m else None   # PMS ~45d de defasagem
    if pm:
        y, m, val, _ = pm
        pa = next((v for (yy, mm, v, *_ ) in pms_a if (yy, mm) == (y, m)), None)
        sub = ("Volume · var. m/m (aj.saz.)"
               + (f" · acum. ano {'+' if pa >= 0 else ''}{_br(pa, 1)}%" if pa is not None else "")
               + f" · IBGE/PMS {_MABBR[m]}/{str(y)[2:]}")
        out.append({"setor": "servicos", "setorLabel": "Serviços", "label": "Serviços (PMS)",
                    "valor": f"{'+' if val >= 0 else ''}{_br(val, 1)}%", "cor": _cor_delta(val),
                    "sub": sub, "ref": f"{_MABBR[m]}/{str(y)[2:]}", "pt": round(val, 2),
                    "acum": None if pa is None else round(pa, 2), "flow": True, "unit": "%"})

    sc = _pick_mensal(sin_c, ref, 1, 8) if sin_c else None
    if sc:
        y, m, val, _ = sc
        sm = next((v for (yy, mm, v, *_ ) in sin_m if (yy, mm) == (y, m)), None)
        sa = next((v for (yy, mm, v, *_ ) in sin_a if (yy, mm) == (y, m)), None)
        sub = ("Custo médio da construção"
               + (f" · +{_br(sm, 2)}% mês" if sm is not None else "")
               + (f" · acum. ano +{_br(sa, 2)}%" if sa is not None else "")
               + f" · IBGE/SINAPI {_MABBR[m]}/{str(y)[2:]}")
        out.append({"setor": "construcao", "setorLabel": "Construção", "label": "Custo m² (SINAPI)",
                    "valor": f"R$ {_br_int(val)}", "cor": _cor_delta(sm if sm is not None else 0),
                    "sub": sub, "ref": f"{_MABBR[m]}/{str(y)[2:]}", "pt": round(val, 2),
                    "acum": None if sa is None else round(sa, 2), "flow": False, "unit": "R$/m²"})

    incc = _bcb_mensal(192, 20)   # INCC/FGV var % mensal (custo de mercado da construção; SGS cap=20 obs)
    ic = _pick_mensal(incc, ref, 1, 6) if incc else None
    if ic:
        y, m, val, _ = ic
        ica = _ipca_acum_ano(incc, y, m)   # acumulado no ano: compõe as variações mensais (jan→ref)
        sub = ("Custo da construção (mercado) · var. mês"
               + (f" · acum. ano {'+' if ica >= 0 else ''}{_br(ica, 2)}%" if ica is not None else "")
               + f" · FGV/BCB-SGS {_MABBR[m]}/{str(y)[2:]}")
        out.append({"setor": "construcao", "key": "construcao_incc", "setorLabel": "Construção",
                    "label": "INCC (FGV)", "valor": f"{'+' if val >= 0 else ''}{_br(val, 2)}%",
                    "cor": _cor_delta(val), "sub": sub, "ref": f"{_MABBR[m]}/{str(y)[2:]}",
                    "pt": round(val, 2), "acum": None if ica is None else round(ica, 2),
                    "flow": True, "unit": "%"})

    ls = _pick_mensal(lspa, ref, 1, 8) if lspa else None
    if ls:
        y, m, val, _ = ls
        lp = _prev_mensal(lspa, y, m)
        mt = val / 1e6
        rev = ((val - lp[2]) / lp[2] * 100) if lp else None
        sub = (f"Estimativa da safra {y}"
               + (f" · {'+' if rev >= 0 else ''}{_br(rev, 1)}% vs. mês anterior" if rev is not None else "")
               + f" · IBGE/LSPA {_MABBR[m]}/{str(y)[2:]}")
        out.append({"setor": "agro", "setorLabel": "Agro", "label": "Safra de grãos (LSPA)",
                    "valor": f"{_br(mt, 1)} Mt", "cor": _cor_delta(rev), "sub": sub,
                    "ref": f"{_MABBR[m]}/{str(y)[2:]}", "pt": round(mt, 1),
                    "acum": None, "flow": False, "unit": "Mt"})
    return out


# ─────────────────────────── VALIDADOR ───────────────────────────
def _familia(label):
    L = (label or "").lower()
    if "selic" in L:
        return "selic"
    if "ipca" in L:
        return "ipca"
    if any(t in L for t in ("câmbio", "cambio", "dólar", "dolar")):
        return "cambio"
    if any(t in L for t in ("desemprego", "pnad", "desocup")):
        return "desemprego"
    if any(t in L for t in ("varejo", "pmc")):
        return "varejo"
    if "ipp" in L or "produtor" in L:
        return "ipp"
    if any(t in L for t in ("pim", "produção ind", "producao ind", "indústria", "industria")):
        return "pim"
    return L


# As 7 famílias macro do painel. A lista é FECHADA de propósito: o painel é
# construído a partir dela, não a partir do que o modelo resolveu devolver.
_FAMILIAS_MACRO = {
    "selic": ("SELIC", 0), "ipca": ("IPCA", 1), "cambio": ("Câmbio (US$)", 2),
    "desemprego": ("Desemprego", 3), "varejo": ("Varejo (PMC)", 4),
    "pim": ("PIM (Indústria)", 5), "ipp": ("IPP", 6),
}

# Marca que o motor lê para acionar a herança do último valor oficial conhecido.
INDISPONIVEL = "—"


def validar_kpis(kpis_gemini, ref=None, verbose=True):
    """Monta o painel macro EXCLUSIVAMENTE com números de fonte oficial.

    O argumento `kpis_gemini` entra apenas como material de AUDITORIA: serve para
    registrar no log o que o modelo tinha proposto e o quanto errou. Nenhum valor
    dele chega ao painel — nem quando a fonte oficial falha.

    Família sem dado oficial sai com valor INDISPONÍVEL e fonte None; o motor
    (reconciliar_kpis) então herda o último valor oficial conhecido, com a semana
    de referência à vista. Antes, esse caminho devolvia o número do Gemini, e foi
    assim que uma Selic de 10,75% ficou três semanas no ar como se fosse do BCB."""
    oficiais = coletar_kpis(ref) or []
    por_fam = {_familia(k["label"]): k for k in oficiais}
    proposto = {_familia(g.get("label", "")): str(g.get("valor", "")).strip()
                for g in (kpis_gemini or [])}

    saida, faltando = [], []
    for fam, (rotulo, _) in sorted(_FAMILIAS_MACRO.items(), key=lambda kv: kv[1][1]):
        of = por_fam.get(fam)
        if of:
            g_val = proposto.get(fam)
            if verbose and g_val and g_val != of["valor"]:
                print(f"[kpis] {fam}: Gemini disse '{g_val}' → OFICIAL '{of['valor']}'.")
            saida.append(dict(of))
        else:
            faltando.append(fam)
            if verbose:
                descartado = proposto.get(fam)
                extra = f" (descartado o valor '{descartado}' do Gemini)" if descartado else ""
                print(f"[kpis] {fam}: SEM FONTE OFICIAL nesta rodada{extra} — "
                      f"marcado como indisponível para herdar o último valor oficial.")
            saida.append({"label": rotulo, "valor": INDISPONIVEL, "cor": "neutro",
                          "sub": "Fonte oficial indisponível nesta coleta",
                          "fonte": None})

    if verbose and faltando:
        print(f"[kpis] ATENÇÃO: {len(faltando)}/{len(_FAMILIAS_MACRO)} indicadores "
              f"sem fonte oficial: {', '.join(faltando)}")
    return saida


if __name__ == "__main__":
    import sys
    ref = None
    if len(sys.argv) > 1:  # data ISO opcional p/ teste: python kpis_oficiais.py 2026-06-05
        ref = date.fromisoformat(sys.argv[1])
    for k in coletar_kpis(ref):
        print(f"  {k['label']:<16} {k['valor']:<12} [{k['cor']}]  {k['sub']}")
