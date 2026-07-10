"""
KPIS OFICIAIS — validador determinístico dos indicadores macro.

O Gemini continua sendo a IA de BUSCA (clipping, sinais, editorial). Mas os
NÚMEROS dos indicadores macro não podem depender do modelo: aqui eles são
buscados direto nas APIs oficiais (BCB/SGS e IBGE/SIDRA) e SOBREPÕEM o que o
Gemini tiver proposto — garantindo 100% de acurácia. Se a API oficial falhar
para um indicador, mantém-se o valor do Gemini (nunca quebra o motor).

Cada indicador traz, quando faz sentido: variação no mês, ACUMULADO NO ANO e 12 meses.

Sem dependências novas: usa só a biblioteca padrão (urllib).
Séries verificadas contra a realidade conhecida (jul/2026):
  SELIC meta 432 (fallback efetiva 1178) · Câmbio PTAX venda 1 · IPCA mês 433 / 12m 13522
  Desemprego PNAD 6381 v4099 · Varejo PMC 8880 v11708(mês)/v11710(ano)
  PIM 8888 v11601(mês)/v11602(ano) · IPP 6903 v1396(mês)/v1395(ano)
"""
import json
import time
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
    if url in _CACHE:
        return _CACHE[url]
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
        except Exception:
            pass
        if i < tries - 1:
            time.sleep(1.0 * (i + 1))
    _CACHE[url] = None
    return None


def _bcb(cod, n=60):
    """Série BCB/SGS diária → lista [(date, valor_float)] mais antigo→recente."""
    j = _get(f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{cod}/dados/ultimos/{n}?formato=json")
    out = []
    for o in (j or []):
        try:
            d, m, y = (int(x) for x in o["data"].split("/"))
            out.append((date(y, m, d), float(str(o["valor"]).replace(",", "."))))
        except (ValueError, KeyError, TypeError):
            continue
    return out


def _bcb_mensal(cod, n=24):
    """Série BCB/SGS mensal → mesmo formato do SIDRA [(ano, mes, valor, periodo)]."""
    return [(d.year, d.month, v, f"{_MABBR[d.month]}/{str(d.year)[2:]}")
            for (d, v) in _bcb(cod, n)]


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
    Indicadores que a API não devolver saem como None (o motor mantém o do Gemini)."""
    ref = ref or date.today()

    selic = _bcb(432, 40) or _bcb(1178, 60)     # meta Copom; fallback efetiva
    cambio = _bcb(1, 60)
    ipca_m = _bcb_mensal(433, 24)
    ipca_12 = _bcb_mensal(13522, 24)
    desemp = _sidra("/t/6381/n1/all/v/4099/p/last%2018")
    varejo_m = _sidra("/t/8880/n1/all/v/11708/p/last%2018/c11046/56734")
    varejo_a = _sidra("/t/8880/n1/all/v/11710/p/last%2018/c11046/56734")
    pim_m = _sidra("/t/8888/n1/all/v/11601/p/last%2018/c544/129314")
    pim_a = _sidra("/t/8888/n1/all/v/11602/p/last%2018/c544/129314")
    ipp_m = _sidra("/t/6903/n1/all/v/1396/p/last%2018")
    ipp_a = _sidra("/t/6903/n1/all/v/1395/p/last%2018")

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
                         "sub": f"Dólar PTAX venda · BCB/SGS · {ca[0].strftime('%d/%m/%Y')}",
                         "fonte": "BCB/SGS"}

    # IPCA (mês + acum. ano + 12m)
    ip = _pick_mensal(ipca_m, ref, 1, 10) if ipca_m else None
    if ip:
        y, m, val = ip[0], ip[1], ip[2]
        prev = next((v for (yy, mm, v, *_ ) in reversed(ipca_m)
                     if (yy, mm) < (y, m)), None)
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


def validar_kpis(kpis_gemini, ref=None, verbose=True):
    """BLINDAGEM: substitui os números do Gemini pelos oficiais (fonte da verdade).
    Mantém a ordem/estrutura; onde a API oficial falhar, preserva o do Gemini.
    Registra no log toda divergência corrigida (auditoria)."""
    oficiais = coletar_kpis(ref)
    if not oficiais:
        if verbose:
            print("[kpis] APIs oficiais indisponíveis — mantendo KPIs do Gemini nesta rodada.")
        return kpis_gemini or []

    por_fam = {_familia(k["label"]): k for k in oficiais}
    usados = set()
    saida = []

    # 1) para cada KPI do Gemini, sobrepõe pelo oficial da mesma família (se houver)
    for g in (kpis_gemini or []):
        fam = _familia(g.get("label", ""))
        of = por_fam.get(fam)
        if of:
            usados.add(fam)
            g_val = str(g.get("valor", "")).strip()
            if verbose and g_val and g_val != of["valor"]:
                print(f"[kpis] {fam}: Gemini disse '{g_val}' → corrigido para OFICIAL '{of['valor']}'.")
            saida.append(dict(of))
        else:
            saida.append(g)  # sem fonte oficial: mantém o do Gemini

    # 2) garante que TODOS os oficiais apareçam (mesmo se o Gemini omitiu algum)
    for fam, of in por_fam.items():
        if fam not in usados:
            saida.append(dict(of))

    # 3) reordena na sequência canônica
    ordem = {"selic": 0, "ipca": 1, "cambio": 2, "desemprego": 3, "varejo": 4, "pim": 5, "ipp": 6}
    saida.sort(key=lambda k: ordem.get(_familia(k.get("label", "")), 99))
    return saida


if __name__ == "__main__":
    import sys
    ref = None
    if len(sys.argv) > 1:  # data ISO opcional p/ teste: python kpis_oficiais.py 2026-06-05
        ref = date.fromisoformat(sys.argv[1])
    for k in coletar_kpis(ref):
        print(f"  {k['label']:<16} {k['valor']:<12} [{k['cor']}]  {k['sub']}")
