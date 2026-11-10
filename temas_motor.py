"""
TEMAS — memória interna do motor (substitui os sinais desde 10/11/2026).

- temas.json          : lista de temas, regras, dicionário palavra→tema, leituras por semana, último ciclo.
- temas_noticias.json : a palavra e o tema de cada notícia publicada, por semana.

A classificação é do Claude: cada notícia recebe UMA palavra (campo interno "palavra" no item
da coleta/incremento); o dicionário resolve o tema. Palavra nova vem com "tema"; tema novo vem
em "novos_temas". Nada disso aparece no portal nem filtra notícias.

Tudo o que é número aqui é CALCULADO a partir das notícias classificadas (participação do tema
nas notícias da semana e da janela de 4 semanas). O único julgamento é a leitura semanal do tema
(tipo risco/oportunidade, texto, status), escrita pelo Claude em "leituras_temas".
"""
import json
import os
import unicodedata
from datetime import datetime

TEMAS = "temas.json"
CLASSIF = "temas_noticias.json"
JANELA = 4                 # semanas (a corrente + 3 anteriores) para impacto e direção
DIRECAO_SOBE = 1.3         # participação na semana >= 1,3x a das 3 anteriores → esquentando
DIRECAO_CAI = 0.7          # <= 0,7x → esfriando
TOP_PORTAL = 9
DIMS = list("PESTAL")
STATUS = ("monitorar", "em_curso", "materializado")


def _agora():
    return datetime.utcnow().isoformat() + "+00:00"


def _ordem(ch):
    try:
        a, s = ch.split("-W")
        return int(a) * 100 + int(s)
    except (ValueError, AttributeError):
        return -1


def _k(w):
    return unicodedata.normalize("NFC", str(w or "").strip()).lower()


def _ler(fn):
    with open(fn, encoding="utf-8") as f:
        return json.load(f)


def _gravar(fn, obj):
    tmp = fn + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, fn)


def carregar():
    return _ler(TEMAS), _ler(CLASSIF)


def salvar(T, C):
    T["atualizado_em"] = _agora()
    _gravar(TEMAS, T)
    _gravar(CLASSIF, C)


def ultimo_ciclo(T):
    return T.get("ultimo_ciclo", "")


def _por_id(T):
    return {t["id"]: t for t in T["temas"]}


def dicionario(T):
    return {_k(w): t for w, t in T["dicionario"].items()}


# ─────────────────────────────────────────────────────────
# CONFERÊNCIA da classificação (coleta semanal ou incremento diário)
# ─────────────────────────────────────────────────────────
def conferir(itens, leituras, novos_temas, T):
    erros = []
    ids = set(_por_id(T))
    for i, n in enumerate(novos_temas or []):
        if not n.get("id") or not n.get("nome") or n.get("dimensao") not in DIMS \
                or n.get("tipo") not in ("risco", "oportunidade"):
            erros.append(f"novos_temas[{i}] precisa de id, nome, dimensao (PESTAL) e tipo")
        elif n["id"] in ids:
            erros.append(f"novos_temas[{i}]: tema '{n['id']}' já existe")
        else:
            ids.add(n["id"])
    dic = dicionario(T)
    proib = {_k(p) for p in T.get("proibidas", [])}
    for i, it in enumerate(itens or []):
        w = str(it.get("palavra") or "").strip()
        if not w or " " in w:
            erros.append(f"clipping[{i}] sem palavra única (campo 'palavra'): {it.get('titulo', '')[:50]}")
        elif _k(w) in proib:
            erros.append(f"clipping[{i}] palavra genérica proibida: '{w}'")
        elif _k(w) in dic:
            if it.get("tema") and it["tema"] != dic[_k(w)]:
                erros.append(f"clipping[{i}] '{w}' já pertence ao tema {dic[_k(w)]}, não a {it['tema']}")
        elif it.get("tema") not in ids:
            erros.append(f"clipping[{i}] palavra nova '{w}' sem 'tema' válido")
    for tid, l in (leituras or {}).items():
        if tid not in ids:
            erros.append(f"leituras_temas: tema desconhecido '{tid}'")
        elif l.get("tipo") not in ("risco", "oportunidade") or l.get("status") not in STATUS \
                or not l.get("texto"):
            erros.append(f"leituras_temas[{tid}] precisa de tipo, status ({'/'.join(STATUS)}) e texto")
    return erros


# ─────────────────────────────────────────────────────────
# REGISTRO: dicionário, temas novos e classificação da semana
# ─────────────────────────────────────────────────────────
def registrar(T, C, chave, itens, novos_temas, quando):
    """Inclui temas e palavras novas e regrava a classificação da semana a partir dos itens
    (a coleta é a fonte da verdade: rodar de novo não duplica nada)."""
    por_id = _por_id(T)
    criados = []
    for n in novos_temas or []:
        if n["id"] not in por_id:
            t = {"id": n["id"], "nome": n["nome"], "dimensao": n["dimensao"], "tipo_padrao": n["tipo"],
                 "indicadores": n.get("indicadores", []), "sinais_origem": []}
            T["temas"].append(t)
            por_id[n["id"]] = t
            criados.append(n["id"])
    dic = dicionario(T)
    novas = {}
    for it in itens:
        w = it["palavra"].strip()
        if _k(w) not in dic:
            T["dicionario"][w] = it["tema"]
            dic[_k(w)] = it["tema"]
            novas[w] = it["tema"]
    if criados or novas:
        T["versao"] = T.get("versao", 1) + 1
        partes = []
        if criados:
            partes.append("temas novos: " + ", ".join(criados))
        if novas:
            partes.append("palavras novas: " + ", ".join(f"{w}→{t}" for w, t in novas.items()))
        T["historico"].append({"versao": T["versao"], "data": quando, "semana": chave,
                               "motivo": "; ".join(partes)})
    C["semanas"][chave] = [{"titulo": it.get("titulo", ""), "palavra": it["palavra"].strip(),
                            "tema": dic[_k(it["palavra"])], "setores": it.get("setores") or []}
                           for it in itens]
    C["semanas"] = dict(sorted(C["semanas"].items(), key=lambda kv: _ordem(kv[0])))
    return criados, novas


def consolidar_leituras(T, chave, leituras):
    """Fechamento da semana: grava as leituras do Claude e avança o ciclo."""
    T["leituras"] = [l for l in T.get("leituras", []) if l["periodo"] != chave]
    for tid, l in (leituras or {}).items():
        T["leituras"].append({"tema": tid, "periodo": chave, "tipo": l["tipo"], "texto": l["texto"],
                              "status": l["status"], "materializado": bool(l.get("materializado"))
                              or l["status"] == "materializado", "fontes": l.get("fontes", [])})
    T["leituras"].sort(key=lambda l: (_ordem(l["periodo"]), l["tema"]))
    T["ultimo_ciclo"] = chave


# ─────────────────────────────────────────────────────────
# MÉTRICAS (calculadas) e LEITURA vigente de cada tema
# ─────────────────────────────────────────────────────────
def _leitura(T, tid, chave, extra=None):
    if extra and tid in extra:
        l = dict(extra[tid])
        l.setdefault("periodo", chave)
        l["materializado"] = bool(l.get("materializado")) or l.get("status") == "materializado"
        return l
    melhor = None
    for l in T.get("leituras", []):
        if l["tema"] == tid and _ordem(l["periodo"]) <= _ordem(chave):
            if melhor is None or _ordem(l["periodo"]) >= _ordem(melhor["periodo"]):
                melhor = l
    return melhor


def metricas(T, C, chave, extra=None):
    """Um registro por tema, com números calculados das notícias classificadas."""
    anteriores = sorted([k for k in C["semanas"] if _ordem(k) < _ordem(chave)], key=_ordem)[-(JANELA - 1):]
    cur = C["semanas"].get(chave, [])
    prev = [it for k in anteriores for it in C["semanas"][k]]
    tot_cur, tot_prev = len(cur), len(prev)
    primeira = {}
    for k in sorted(C["semanas"], key=_ordem):
        if _ordem(k) > _ordem(chave):
            break
        for it in C["semanas"][k]:
            primeira.setdefault(it["tema"], k)
    out = []
    for t in T["temas"]:
        tid = t["id"]
        n_cur = sum(1 for it in cur if it["tema"] == tid)
        n_prev = sum(1 for it in prev if it["tema"] == tid)
        s_cur = n_cur / tot_cur if tot_cur else 0.0
        s_prev = n_prev / tot_prev if tot_prev else 0.0
        s_jan = (n_cur + n_prev) / (tot_cur + tot_prev) if (tot_cur + tot_prev) else 0.0
        if n_cur == 0 and n_prev == 0:
            direcao = "ausente"
        elif n_prev == 0:
            direcao = "novo" if primeira.get(tid) == chave else "retomado"
        elif n_cur == 0:
            direcao = "esfriando"
        else:
            r = s_cur / s_prev
            direcao = "esquentando" if r >= DIRECAO_SOBE else ("esfriando" if r <= DIRECAO_CAI else "estável")
        setores = {}
        for it in cur + prev:
            if it["tema"] == tid:
                for s in it.get("setores") or []:
                    setores[s] = setores.get(s, 0) + 1
        out.append({"tema": t, "n_semana": n_cur, "n_janela": n_cur + n_prev, "s_cur": s_cur,
                    "s_jan": s_jan, "direcao": direcao,
                    "setores": [s for s, _ in sorted(setores.items(), key=lambda kv: -kv[1])],
                    "primeira": primeira.get(tid, ""), "leitura": _leitura(T, tid, chave, extra)})
    max_jan = max((m["s_jan"] for m in out), default=0) or 1
    max_cur = max((m["s_cur"] for m in out), default=0) or 1
    janela = set(anteriores + [chave])
    for m in out:
        m["impacto"] = round(10 * m["s_jan"] / max_jan, 1)
        m["iminencia"] = round(10 * m["s_cur"] / max_cur, 1)
        l = m["leitura"]
        recente_mat = bool(l and l.get("materializado") and l.get("periodo") in janela)
        rel = (0.5 * m["impacto"] + 0.5 * m["iminencia"]) * 10 * (1.25 if recente_mat else 1.0)
        m["relevancia"] = round(min(rel, 100.0), 1)
    out.sort(key=lambda m: (-m["relevancia"], -m["n_janela"], m["tema"]["id"]))
    return out


def longitudinal(T, C, chave, extra=None):
    """Bloco 'longitudinal' do portal (mesmo formato de antes): os temas mais relevantes."""
    saida = []
    for m in metricas(T, C, chave, extra):
        if m["n_janela"] == 0:
            continue
        t, l = m["tema"], m["leitura"] or {}
        saida.append({
            "id": "tema-" + t["id"], "tipo": l.get("tipo") or t.get("tipo_padrao", "risco"),
            "titulo": t["nome"], "dimensao": t.get("dimensao", "E"),
            "setores": m["setores"] or ["transversal"],
            "status": l.get("status") or "monitorar", "relevancia": m["relevancia"],
            "severidade": m["impacto"], "iminencia": m["iminencia"],
            "ultima_observacao": l.get("texto", ""), "periodo_observacao": l.get("periodo", ""),
            "data_identificacao": m["primeira"], "origem": "real",
            "direcao": m["direcao"], "noticias_semana": m["n_semana"],
        })
        if len(saida) == TOP_PORTAL:
            break
    return saida


def setores_do_tema(T, C, chave, tid):
    for m in metricas(T, C, chave):
        if m["tema"]["id"] == tid:
            return m["setores"]
    return []


def contexto_editorial(T, C, chave, extra=None):
    """Linhas de trajetória por tema para o prompt do editorial (base das projeções)."""
    semanas = sorted([k for k in C["semanas"] if _ordem(k) <= _ordem(chave)], key=_ordem)[-6:]
    linhas = []
    for m in metricas(T, C, chave, extra):
        if m["n_janela"] == 0:
            continue
        t, l = m["tema"], m["leitura"] or {}
        serie = ", ".join(f"{k[-3:]} {sum(1 for it in C['semanas'][k] if it['tema'] == t['id'])}"
                          for k in semanas)
        ind = f" | indicadores ligados: {', '.join(t['indicadores'])}" if t.get("indicadores") else ""
        linhas.append(
            f"- {t['nome']} [{(l.get('tipo') or t.get('tipo_padrao', 'risco')).upper()}, "
            f"{l.get('status') or 'monitorar'}] direção {m['direcao']} | relevância {m['relevancia']} | "
            f"notícias por semana: {serie} | leitura ({l.get('periodo') or '—'}): {l.get('texto') or '—'}{ind}")
    materializados = [_por_id(T)[l["tema"]]["nome"] for l in T.get("leituras", [])
                      if l["periodo"] == chave and l.get("materializado")]
    if extra:
        materializados = [_por_id(T)[tid]["nome"] for tid, l in extra.items()
                          if l.get("materializado") or l.get("status") == "materializado"]
    return linhas, materializados


def texto_para_coleta(T, C, chave):
    """Bloco do prompt de coleta: temas e dicionário vigentes (para a classificação)."""
    ms = metricas(T, C, chave)
    linhas = []
    for m in ms:
        t, l = m["tema"], m["leitura"] or {}
        palavras = sorted((w for w, x in T["dicionario"].items() if x == t["id"]), key=str.lower)
        linhas.append(f"- {t['id']} — {t['nome']} | leitura vigente ({l.get('periodo') or '—'}): "
                      f"{l.get('texto') or '—'} | palavras: {', '.join(palavras)}")
    return "\n".join(linhas)
