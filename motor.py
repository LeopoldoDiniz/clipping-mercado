"""
MOTOR DO CLIPPING DE MERCADO — v5 (IA via Claude, memória de TEMAS no repositório)

A parte de IA (busca web + redação) é feita pelo Claude numa sessão (local ou rotina
agendada na nuvem), sem API. O motor cuida de tudo o que é determinístico, em 3 passos:

  python motor.py preparar  2026-W46   → data/raw/2026-W46/prompt_coleta.md
      (Claude pesquisa e grava data/raw/2026-W46/coleta.json, no formato definido em prompt_geracao.py)
  python motor.py processar 2026-W46   → valida a coleta, atualiza temas.json/temas_noticias.json,
                                          grava data/raw/2026-W46/prompt_editorial.md
      (Claude escreve data/raw/2026-W46/editorial.txt)
  python motor.py publicar  2026-W46   → KPIs oficiais (BCB/IBGE) + data/2026-W46.json,
                                          data/ultimo.json e data/index.json

Sem a semana, usa a semana ISO atual. A memória longitudinal vive em temas.json (temas, dicionário
palavra→tema, leituras semanais) e temas_noticias.json (palavra e tema de cada notícia) — ver
temas_motor.py. data/sinais.json ficou congelado como histórico em 10/11/2026.
Semanas devem ser fechadas em ORDEM CRONOLÓGICA.
"""
import os
import sys
import json
import re
import glob
from datetime import date, datetime, timedelta

from prompt_geracao import montar_prompt
from kpis_oficiais import validar_kpis, coletar_kpis_setoriais, coletar_ipca_grupos
import temas_motor as TM

# ─────────────────────────────────────────────────────────
# CONFIGURAÇÃO
# ─────────────────────────────────────────────────────────
MEMORIA_SINAIS_CONGELADA = "data/sinais.json"   # histórico; não é mais lido nem gravado
RAW = "data/raw"                      # insumos de trabalho por semana (fora do git)
SETORES = ("industria", "comercio", "servicos", "agro", "construcao", "ecommerce")


# ─────────────────────────────────────────────────────────
# FONTES OFICIAIS: mapa palavra-chave → homepage oficial.
# Usado como fallback quando a coleta traz URL inválida/proibida.
# ─────────────────────────────────────────────────────────
FONTES_OFICIAIS = {
    "ibge": "https://agenciadenoticias.ibge.gov.br",
    "focus": "https://www.bcb.gov.br/publicacoes/focus",
    "bcb": "https://www.bcb.gov.br",
    "banco central": "https://www.bcb.gov.br",
    "fgv": "https://portalibre.fgv.br",
    "ibre": "https://portalibre.fgv.br",
    "ipea": "https://www.ipea.gov.br",
    "cni": "https://noticias.portaldaindustria.com.br",
    "mdic": "https://www.gov.br/mdic/pt-br",
    "anp": "https://www.gov.br/anp/pt-br",
    "fiesp": "https://www.fiesp.com.br",
    "cnc": "https://portaldocomercio.org.br",
    "fecom": "https://www.fecomerciomg.org.br",
    "cndl": "https://cndl.org.br",
    "spc": "https://cndl.org.br",
    "nielsen": "https://nielseniq.com/global/pt",
    "sebrae": "https://sebrae.com.br",
    "febraban": "https://portal.febraban.org.br",
    "senado": "https://www12.senado.leg.br/noticias",
    "camara": "https://www.camara.leg.br/noticias",
    "câmara": "https://www.camara.leg.br/noticias",
    "receita": "https://www.gov.br/receitafederal/pt-br",
    "cade": "https://www.gov.br/cade/pt-br",
    "mit": "https://mittechreview.com.br",
    "aneel": "https://www.gov.br/aneel/pt-br",
    "mma": "https://www.gov.br/mma/pt-br",
    "b3": "https://www.b3.com.br",
    "valor": "https://valor.globo.com",
    "exame": "https://exame.com",
    "infomoney": "https://www.infomoney.com.br",
    "epbr": "https://epbr.com.br",
    "serasa": "https://www.serasaexperian.com.br",
    "anfavea": "https://www.anfavea.com.br",
    "abimaq": "https://www.abimaq.org.br",
    "abras": "https://www.abras.com.br",
    "fenabrave": "https://www.fenabrave.org.br",
    "anatel": "https://www.gov.br/anatel/pt-br",
    "abes": "https://abessoftware.com.br",
    # Agro
    "cna": "https://www.cnabrasil.org.br",
    "cepea": "https://www.cepea.org.br",
    "conab": "https://www.conab.gov.br",
    "embrapa": "https://www.embrapa.br",
    "mapa": "https://www.gov.br/agricultura/pt-br",
    "agricultura": "https://www.gov.br/agricultura/pt-br",
    "imea": "https://www.imea.com.br",
    "notícias agrícolas": "https://www.noticiasagricolas.com.br",
    "noticias agricolas": "https://www.noticiasagricolas.com.br",
    "canal rural": "https://www.canalrural.com.br",
    "abiec": "https://www.abiec.com.br",
    "abpa": "https://www.abpa-br.org",
    "abiove": "https://abiove.org.br",
    "unica": "https://unica.com.br",
    # Construção civil
    "cbic": "https://cbic.org.br",
    "sinduscon": "https://www.sindusconsp.com.br",
    "abrainc": "https://www.abrainc.org.br",
    "secovi": "https://www.secovi.com.br",
    "abramat": "https://www.abramat.org.br",
    "snic": "https://www.snic.org.br",
    "sinapi": "https://www.caixa.gov.br",
    "caixa": "https://www.caixa.gov.br",
    "incc": "https://portalibre.fgv.br",
    "anamaco": "https://www.anamaco.com.br",
    # E-commerce
    "abcomm": "https://abcomm.org",
    "neotrust": "https://neotrust.com.br",
    "mcc": "https://www.mccenet.com.br",
    "conversion": "https://www.conversion.com.br",
    "e-commerce brasil": "https://www.ecommercebrasil.com.br",
    "ecommerce brasil": "https://www.ecommercebrasil.com.br",
    "nuvemshop": "https://www.nuvemshop.com.br",
    "vtex": "https://vtex.com/br-pt",
    "mercado livre": "https://www.mercadolivre.com.br",
    "shopee": "https://shopee.com.br",
    "amazon": "https://www.amazon.com.br",
    "magalu": "https://www.magazineluiza.com.br",
    "magazine luiza": "https://www.magazineluiza.com.br",
    "reclame aqui": "https://www.reclameaqui.com.br",
    # ─── Ampliação de fontes (2026-07): imprensa econômica + associações/índices por setor ───
    # Macro / imprensa econômica
    "estadão": "https://www.estadao.com.br/economia",
    "estadao": "https://www.estadao.com.br/economia",
    "broadcast": "https://www.estadao.com.br/economia",
    "folha": "https://www1.folha.uol.com.br/mercado",
    "o globo": "https://oglobo.globo.com/economia",
    "brazil journal": "https://braziljournal.com",
    "neofeed": "https://neofeed.com.br",
    "money times": "https://www.moneytimes.com.br",
    "cnn": "https://www.cnnbrasil.com.br",
    "poder360": "https://www.poder360.com.br",
    "agência brasil": "https://agenciabrasil.ebc.com.br/economia",
    "agencia brasil": "https://agenciabrasil.ebc.com.br/economia",
    "tesouro": "https://www.gov.br/tesouronacional/pt-br/noticias",
    "fazenda": "https://www.gov.br/fazenda/pt-br/assuntos/noticias",
    "peic": "https://pesquisascnc.com.br/pesquisas",
    "pesquisascnc": "https://pesquisascnc.com.br/pesquisas",
    # Indústria
    "pmi": "https://www.pmi.spglobal.com/public?language=pt",
    "aço brasil": "https://www.acobrasil.org.br",
    "aco brasil": "https://www.acobrasil.org.br",
    "abiquim": "https://abiquim.org.br/comunicacao/noticias",
    "abinee": "http://www.abinee.org.br/noticias",
    "abit": "https://www.abit.org.br/noticias",
    "iedi": "https://www.iedi.org.br",
    "firjan": "https://www.firjan.com.br/imprensa",
    "fiemg": "https://www.fiemg.com.br/noticias",
    "sindipeças": "https://www.sindipecas.org.br",
    "sindipecas": "https://www.sindipecas.org.br",
    "abraciclo": "https://abraciclo.com.br/press-release",
    "autodata": "https://www.autodata.com.br/news",
    "automotive business": "https://www.automotivebusiness.com.br/noticias",
    # Comércio
    "cielo": "https://blog.cielo.com.br/indice-icva",
    "icva": "https://blog.cielo.com.br/indice-icva",
    "equifax": "https://www.equifax.com.br/sobre-a-equifax/sala-de-imprensa",
    "boa vista": "https://www.equifax.com.br/sobre-a-equifax/sala-de-imprensa",
    "sbvc": "https://sbvc.com.br/conteudos/noticias",
    "ibevar": "https://www.ibevar.org.br",
    "abf": "https://www.abf.com.br/a-abf/imprensa",
    "abrasce": "https://abrasce.com.br/imprensa",
    "abad": "https://abad.com.br/indicadores",
    "apas": "https://apas.com.br",
    "idv": "https://www.idv.org.br/sala-imprensa/releases",
    "consumidor moderno": "https://consumidormoderno.com.br",
    "diário do comércio": "https://dcomercio.com.br",
    "diario do comercio": "https://dcomercio.com.br",
    "novo varejo": "https://novovarejo.com.br",
    "supervarejo": "https://www.supervarejo.com.br/noticias",
    "infovarejo": "https://infovarejo.com.br",
    # Serviços
    "anbima": "https://www.anbima.com.br/pt_br/imprensa/sala-de-imprensa.htm",
    "cnseg": "https://cnseg.org.br/noticias",
    "susep": "https://www.gov.br/susep/pt-br/central-de-conteudos/noticias",
    "abecs": "https://abecs.org.br/imprensa",
    "conexis": "https://conexis.org.br/noticias",
    "teletime": "https://teletime.com.br",
    "telesíntese": "https://telesintese.com.br/plantao-de-noticias",
    "telesintese": "https://telesintese.com.br/plantao-de-noticias",
    "convergência digital": "https://convergenciadigital.com.br",
    "convergencia digital": "https://convergenciadigital.com.br",
    "ccee": "https://www.ccee.org.br/pt/web/guest/noticias",
    "canalenergia": "https://www.canalenergia.com.br/noticias",
    "brasscom": "https://brasscom.org.br/noticias",
    "mobile time": "https://www.mobiletime.com.br/noticias",
    # Agro
    "agrolink": "https://www.agrolink.com.br/noticias",
    "compre rural": "https://www.comprerural.com/categorias/noticias",
    "agribiz": "https://www.theagribiz.com/ultimos-posts",
    "cultivar": "https://revistacultivar.com.br/noticias",
    "beefpoint": "https://www.beefpoint.com.br/noticias",
    "sou agro": "https://souagro.net",
    "agribrasilis": "https://agribrasilis.com",
    "forbes": "https://forbes.com.br/forbes-agro",
    "aprosoja": "https://aprosojabrasil.com.br/comunicacao",
    "abag": "https://abag.com.br/noticias-abag",
    "sociedade rural": "https://www.srb.org.br",
    "abrapa": "https://abrapa.com.br",
    "ocb": "https://somoscooperativismo.coop.br/noticias",
    "somos cooperativismo": "https://somoscooperativismo.coop.br/noticias",
    "fpa": "https://agencia.fpagropecuaria.org.br",
    "anda": "https://anda.org.br",
    "datagro": "https://portal.datagro.com",
    "safras": "https://safras.com.br/noticias",
    "jbs": "https://mediaroom.jbs.com.br",
    # Construção civil
    "abecip": "https://www.abecip.org.br/imprensa/noticias",
    "cidades": "https://www.gov.br/cidades/pt-br/assuntos/noticias-1",
    "aecweb": "https://www.aecweb.com.br/revista-digital/noticias",
    "massa cinzenta": "https://www.cimentoitambe.com.br/massa-cinzenta",
    "cimento itambé": "https://www.cimentoitambe.com.br/massa-cinzenta",
    "cimento itambe": "https://www.cimentoitambe.com.br/massa-cinzenta",
    "grandes construções": "https://grandesconstrucoes.com.br/noticias/todas",
    "grandes construcoes": "https://grandesconstrucoes.com.br/noticias/todas",
    "empreiteiro": "https://revistaoe.com.br",
    "abcp": "https://abcp.org.br/category/imprensa",
    "cau": "https://caubr.gov.br/noticias",
    "confea": "https://www.confea.org.br/noticias",
    "ademi": "https://ademi.org.br/mercado-imobiliario-brasil",
    "mrv": "https://www.mrv.com.br/institucional/pt/a-mrv/releases",
    "cyrela": "https://ri.cyrela.com.br",
    "votorantim cimentos": "https://www.votorantimcimentos.com.br/noticias",
    # E-commerce
    "e-commerce news": "https://ecommercenews.com.br",
    "novarejo": "https://portalnovarejo.com.br",
    "meio & mensagem": "https://www.meioemensagem.com.br/proxxima",
    "meio e mensagem": "https://www.meioemensagem.com.br/proxxima",
    "proxxima": "https://www.meioemensagem.com.br/proxxima",
    "camara-e": "https://camara-e.net/category/news",
    "economia digital": "https://camara-e.net/category/news",
    "senacon": "https://www.gov.br/mj/pt-br/assuntos/noticias",
    "procon": "https://www.procon.sp.gov.br/category/noticias",
    "casas bahia": "https://www.grupocasasbahia.com.br/imprensa",
    "shein": "https://www.sheingroup.com/newsroom",
}

# Domínios que NUNCA podem aparecer como fonte (inclui o próprio portal)
DOMINIOS_PROIBIDOS = (
    "github.io", "githubusercontent", "github.com", "vercel.app", "netlify",
    "pages.dev", "vertexaisearch", "grounding-api-redirect",
    "google.com/search", "googleusercontent",
)


def url_valida(url):
    """URL é aceitável se for http(s) e não estiver na lista proibida."""
    if not url or not isinstance(url, str):
        return False
    u = url.strip().lower()
    if not (u.startswith("http://") or u.startswith("https://")):
        return False
    return not any(dom in u for dom in DOMINIOS_PROIBIDOS)


def fallback_fonte(nome):
    """Encontra a homepage oficial pela palavra-chave no nome da fonte."""
    n = (nome or "").lower()
    for chave, home in FONTES_OFICIAIS.items():
        if chave in n:
            return home
    return None


def normalizar_clipping(itens):
    """
    Normaliza os itens de clipping para o formato canônico:
      {setores, titulo, texto, fontes:[{nome,url}]}
    - Aceita o formato novo (fontes: array) e o antigo (fonte + url).
    - Valida cada URL; se inválida/proibida, troca pela homepage oficial da fonte;
      se nem isso existir, remove o link (o portal exibe a fonte sem link).
    """
    saida = []
    for it in itens or []:
        fontes_brutas = it.get("fontes")
        if not fontes_brutas:
            # formato antigo: fonte (string) + url
            fontes_brutas = [{"nome": it.get("fonte", ""), "url": it.get("url", "")}]

        fontes_limpa = []
        for f in fontes_brutas:
            nome = (f.get("nome") or f.get("fonte") or "").strip()
            url = (f.get("url") or "").strip()
            if not url_valida(url):
                url = fallback_fonte(nome)  # pode ser None → sem link
            fontes_limpa.append({"nome": nome or "Fonte", "url": url})

        saida.append({
            "setores": it.get("setores") or ["transversal"],
            "titulo": it.get("titulo", ""),
            "texto": it.get("texto", ""),
            "fontes": fontes_limpa,
        })
    return saida


# ─────────────────────────────────────────────────────────
# PERÍODO: calcula o rótulo da semana ISO atual
# ─────────────────────────────────────────────────────────
def periodo_atual(chave=None):
    """Rótulo/intervalo da semana ISO. Sem chave, usa a semana de hoje."""
    if chave:
        a, s = chave.upper().split("-W")
        inicio = date.fromisocalendar(int(a), int(s), 1)
    else:
        hoje = date.today()
        inicio = hoje - timedelta(days=hoje.weekday())
    ano, semana, _ = inicio.isocalendar()
    fim = inicio + timedelta(days=4)
    meses = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
             "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
    label = f"Semana {semana} · {meses[inicio.month]} {ano}"
    chave = f"{ano}-W{semana:02d}"
    return chave, label, inicio.isoformat(), fim.isoformat()


def _data_ref(chave):
    """Data que entra nos registros da memória: hoje, ou a sexta da semana se ela já passou
    (backfill) — para a memória não datar registros de setembro como de novembro."""
    return min(date.today(), _sexta_da_chave(chave))


def _sexta_da_chave(chave):
    """Sexta-feira (ISO) da semana da chave 'AAAA-Www' — data de referência dos KPIs oficiais."""
    try:
        a, s = chave.split("-W")
        return date.fromisocalendar(int(a), int(s), 5)
    except (ValueError, AttributeError):
        return date.today()


# ─────────────────────────────────────────────────────────
# EXTRAI JSON da coleta (tolerante a lixo em volta)
# ─────────────────────────────────────────────────────────
def extrair_json(texto):
    # remove cercas de markdown se houver
    texto = re.sub(r"^```(?:json)?|```$", "", texto.strip(), flags=re.MULTILINE).strip()
    # pega do primeiro { ao último }
    ini = texto.find("{")
    fim = texto.rfind("}")
    if ini == -1 or fim == -1:
        raise ValueError("Coleta não contém JSON.")
    return json.loads(texto[ini:fim + 1])


# ─────────────────────────────────────────────────────────
# MEMÓRIA LONGITUDINAL: temas (temas.json + temas_noticias.json) — ver temas_motor.py.
# data/sinais.json fica CONGELADO como histórico (não é mais lido nem gravado).
# ─────────────────────────────────────────────────────────
def _agora():
    return datetime.utcnow().isoformat() + "+00:00"


# ─────────────────────────────────────────────────────────
# CONFERÊNCIA DA COLETA (o que o Claude gravou em coleta.json)
# Erro = bloqueia o processamento. Aviso = segue, mas fica registrado.
# ─────────────────────────────────────────────────────────
def _palavras(t):
    return len(str(t or "").split())


def conferir_coleta(dados, T):
    erros, avisos = [], []
    for k in ("clipping", "pestel", "kpis", "porter", "analise"):
        if not dados.get(k):
            erros.append(f"campo obrigatório ausente/vazio: {k}")
    clip = dados.get("clipping") or []
    por_setor = {s: sum(1 for it in clip if s in (it.get("setores") or [])) for s in SETORES}
    for s, n in por_setor.items():
        if n < 15:
            avisos.append(f"clipping {s}: {n} itens (meta 15-20)")
    longos = [it.get("titulo", "")[:50] for it in clip if _palavras(it.get("texto")) > 35]
    if longos:
        avisos.append(f"{len(longos)} itens de clipping com texto > 35 palavras")
    proibidas = [f.get("url") for it in clip for f in (it.get("fontes") or [])
                 if f.get("url") and not url_valida(f.get("url"))]
    if proibidas:
        avisos.append(f"{len(proibidas)} URLs inválidas/proibidas (serão trocadas pela home oficial)")
    dims = [p.get("dim") for p in dados.get("pestel") or []]
    if sorted(dims) != sorted("PESTAL"):
        erros.append(f"pestel deve ter as 6 dimensões P,E,S,T,A,L — veio {dims}")
    if len(dados.get("kpis") or []) != 7:
        erros.append(f"kpis deve ter 7 itens — veio {len(dados.get('kpis') or [])}")
    faltam_porter = [s for s in SETORES if s not in (dados.get("porter") or {})]
    if faltam_porter:
        erros.append(f"porter sem os setores: {faltam_porter}")
    faltam_an = [s for s in SETORES if s not in ((dados.get("analise") or {}).get("setores") or {})]
    if faltam_an:
        erros.append(f"analise sem os setores: {faltam_an}")
    erros += TM.conferir(clip, dados.get("leituras_temas"), dados.get("novos_temas"), T)
    resumo = (f"{len(clip)} notícias ({', '.join(f'{s} {n}' for s, n in por_setor.items())}) · "
              f"{len(dados.get('leituras_temas') or {})} leituras de tema · "
              f"{len(dados.get('novos_temas') or [])} temas novos")
    return erros, avisos, resumo


# ─────────────────────────────────────────────────────────
# EDITORIAL longitudinal — o motor monta o prompt; o Claude escreve o texto
# ─────────────────────────────────────────────────────────
def _editorial_anterior(chave):
    """Editorial da semana publicada IMEDIATAMENTE anterior a esta (não o ultimo.json,
    que no backfill seria uma semana do futuro)."""
    ordem = _ordem_chave(chave)
    melhor, texto = -1, ""
    for fn in glob.glob("data/*.json"):
        m = re.match(r"(\d{4}-W\d+)\.json$", os.path.basename(fn))
        if not m:
            continue
        o = _ordem_chave(m.group(1))
        if melhor < o < ordem:
            try:
                with open(fn, encoding="utf-8") as f:
                    t = (json.load(f).get("editorial") or {}).get("texto", "")
            except (OSError, json.JSONDecodeError):
                t = ""
            if t:
                melhor, texto = o, t
    return texto


def _coletar_contexto_editorial(T, C, chave, dados):
    """Reúne as TRÊS camadas que tornam o editorial longitudinal:
       (1) estado atual e (2) trajetória dos temas (contagem semanal calculada + leitura), (3) editorial anterior."""
    trajetorias, materializados = TM.contexto_editorial(T, C, chave)
    return {
        "trajetorias": trajetorias,
        "n_ativos": len(trajetorias),
        "materializados": materializados,
        "novos": [n.get("nome", "") for n in dados.get("novos_temas") or []],
        "editorial_anterior": _editorial_anterior(chave),
        "kpis": dados.get("kpis", []),
    }


def montar_prompt_editorial(T, C, chave, label, dados):
    ctx = _coletar_contexto_editorial(T, C, chave, dados)

    kpis_txt = " | ".join(f"{k.get('label','')}: {k.get('valor','')} ({k.get('sub','')})"
                          for k in ctx["kpis"])
    traj_txt = "\n".join(ctx["trajetorias"]) or "(sem temas com notícias recentes)"
    cont_txt = (f"No editorial da semana anterior, escrevemos:\n\"{ctx['editorial_anterior']}\"\n"
                f"Dê continuidade: confirme, ajuste ou contraste aquela leitura com o que mudou."
                if ctx["editorial_anterior"] else
                "Esta é a primeira edição do editorial — estabeleça a leitura de base do cenário.")

    fn_ag = os.path.join(_pasta(chave), "agenda.md")
    agenda_txt = (open(fn_ag, encoding="utf-8").read().strip() if os.path.exists(fn_ag)
                  else "(agenda não informada — use apenas datas de divulgação já confirmadas nos dados acima)")

    prompt = f"""Você é o analista-chefe de inteligência de mercado da Nexos. Escreva o EDITORIAL que
ABRE a próxima semana, a partir do fechamento de {label}. O editorial é PREDITIVO: o leitor
quer saber o que esperar e como se posicionar — a síntese do que passou é secundária.

# INDICADORES (fechamento de {label})
{kpis_txt}

# MEMÓRIA LONGITUDINAL — temas: notícias por semana (calculado), direção e leitura vigente (base das projeções)
{traj_txt}

# MUDANÇAS RELEVANTES NESTE CICLO
- Temas com risco ou oportunidade materializado nesta semana: {', '.join(ctx['materializados']) or 'nenhum'}
- Temas novos nesta semana: {', '.join(ctx['novos']) or 'nenhum'}

# AGENDA DAS PRÓXIMAS SEMANAS (divulgações e eventos com data marcada)
{agenda_txt}

# CONTINUIDADE NARRATIVA
{cont_txt}

# COMO ESCREVER
- ESTRUTURA OBRIGATÓRIA, nesta ordem, em texto corrido de 280 a 360 palavras, sem listas:
  (1) PERSPECTIVA — abre o texto: o que esperar nas próximas semanas. Cenário principal e riscos,
      ancorados na trajetória dos temas (esquentando/esfriando, leitura vigente) e na agenda acima.
      Cite as datas que importam. É a maior parte do texto.
  (2) POR SETOR — uma projeção curta por bloco (indústria; comércio e serviços; agro; construção;
      e-commerce): o que deve acontecer e o que fazer.
  (3) RESUMO — fecha o texto: em duas ou três frases, o que aconteceu na semana que passou, com os
      números-chave.
- Toda PROJEÇÃO é marcada como tal ("a tendência é", "o cenário mais provável", "se X, então Y")
  e se apoia num dado ou tema citado. Nunca apresente previsão como fato consumado.
- Se o editorial anterior fez uma projeção, diga em uma frase se ela se confirmou ou não.
- Linguagem FORMAL, mas SEM jargão: um empresário de PME deve entender sem dicionário. Termo técnico
  (ex.: Selic) é explicado em poucas palavras na própria frase.
- Densidade: cada frase carrega informação (número, data, evento, fonte). Nada de enchimento.
- Tom: sóbrio, seguro, de quem acompanha o cenário há tempo. Português do Brasil.

Responda SOMENTE com o texto do editorial, sem título, sem aspas, sem markdown."""
    return prompt, ctx["n_ativos"]


def _kpi_indisponivel(v):
    s = str(v or "").strip()
    if not s or re.fullmatch(r"[-–—\s]+", s):
        return True
    return bool(re.search(
        r"n[ãa]o\s+(dispon|divulg|informad|h[áa]|houve)|indispon|"
        r"sem\s+(dado|coleta|divulga)|aguard|a\s+divulgar|pendente|n/d", s, re.I))


def _kpi_sem_proj(v):
    return re.sub(r"\s*\(proj\.[^)]*\)", "", str(v or "")).strip()


def _kpi_bucket(label):
    L = (label or "").lower()
    mapa = [
        ("selic", ("selic",)), ("ipca", ("ipca",)),
        ("cambio", ("câmbio", "cambio", "dólar", "dolar")),
        ("desemprego", ("desemprego", "pnad", "desocup")),
        ("varejo", ("varejo", "pmc")),
        ("pim", ("pim", "produção industrial", "producao industrial")),
        ("ipp", ("ipp",)),
    ]
    for nome, termos in mapa:
        if any(t in L for t in termos):
            return nome
    return L


def _ordem_chave(ch):
    try:
        a, s = ch.split("-W")
        return int(a) * 100 + int(s)
    except (ValueError, AttributeError):
        return -1


def reconciliar_kpis(kpis, chave):
    """Ponto 1a — herança determinística do último valor conhecido.

    Se um KPI não foi divulgado nesta semana ('Não disponível', 'Não divulgado',
    'Sem dados', etc.), busca nas semanas anteriores (data/*.json) o valor real
    mais recente do MESMO indicador e o assume como parâmetro, anotando no 'sub'
    a semana de referência. Não depende da IA obedecer — é código puro.
    """
    ordem_atual = _ordem_chave(chave)
    anteriores = []
    try:
        for fn in glob.glob("data/*.json"):
            base = os.path.basename(fn)
            if base in ("index.json", "ultimo.json"):
                continue
            m = re.match(r"(\d{4}-W\d+)\.json$", base)
            if not m or _ordem_chave(m.group(1)) >= ordem_atual:
                continue
            with open(fn, encoding="utf-8") as f:
                j = json.load(f)
            anteriores.append((_ordem_chave(m.group(1)),
                               j.get("label", m.group(1)),
                               j.get("kpis", [])))
    except (OSError, json.JSONDecodeError):
        anteriores = []
    anteriores.sort(key=lambda t: t[0], reverse=True)

    saida = []
    for k in kpis:
        kk = dict(k)
        if _kpi_indisponivel(kk.get("valor")):
            bucket = _kpi_bucket(kk.get("label"))
            for _, lbl_ant, kpis_ant in anteriores:
                # SÓ herda de semana com procedência oficial ('fonte' preenchida).
                # As semanas 29 a 31 de 2026 guardam números que a IA inventou
                # enquanto a API do BCB estava fora (fonte=None); sem este filtro a
                # herança os ressuscitaria e a contaminação viraria permanente.
                cand = next((x for x in kpis_ant
                             if _kpi_bucket(x.get("label")) == bucket
                             and x.get("fonte")
                             and not _kpi_indisponivel(_kpi_sem_proj(x.get("valor")))),
                            None)
                if cand:
                    kk["valor"] = _kpi_sem_proj(cand.get("valor"))
                    kk["sub"] = (f"Último dado oficial disponível ({lbl_ant}) — "
                                 f"fonte não respondeu nesta coleta.")
                    kk["fonte"] = cand.get("fonte")
                    kk["herdado_de"] = lbl_ant
                    break
        saida.append(kk)
    return saida


def gerar_dados_portal(dados, T, C, chave, label, editorial=None, status="fechada", ref_kpi=None,
                       leituras=None):
    """Gera data/<periodo>.json que o frontend consome.
    status: "fechada" (memória consolidada) ou "em_andamento" (prévia diária).
    leituras: leituras de tema ainda não consolidadas (prévia da semana corrente)."""
    # bloco longitudinal do portal = os temas mais relevantes (números calculados das notícias)
    longitudinal = TM.longitudinal(T, C, chave, leituras)

    # BLINDAGEM DE ACURÁCIA: a IA busca, mas os NÚMEROS macro são validados/
    # sobrepostos pelos valores OFICIAIS (BCB/IBGE) válidos na sexta desta semana,
    # já com acumulado no ano. Se a API oficial falhar, mantém o valor da coleta.
    ref_kpi = ref_kpi or _sexta_da_chave(chave)
    kpis_validados = validar_kpis(dados.get("kpis", []), ref=ref_kpi)
    # Fonte fora do ar: antes de herdar da semana anterior, mantém o último valor OFICIAL já
    # publicado NESTA semana (ex.: rodada diária em ambiente sem acesso ao BCB/IBGE).
    publicado = _ler_json(f"data/{chave}.json", {}) or {}
    ja = {_kpi_bucket(x.get("label")): x for x in publicado.get("kpis") or []
          if x.get("fonte") and not x.get("herdado_de") and not _kpi_indisponivel(x.get("valor"))}
    kpis_validados = [dict(ja[_kpi_bucket(k.get("label"))])
                      if _kpi_indisponivel(k.get("valor")) and _kpi_bucket(k.get("label")) in ja else k
                      for k in kpis_validados]
    # ponto 1a — herança determinística caso algum indicador não venha da API oficial
    kpis_final = reconciliar_kpis(kpis_validados, chave)
    # indicadores setoriais + pressões do IPCA por grupo: OFICIAIS (IBGE), determinísticos.
    # Válidos na sexta desta semana (mesma lógica de defasagem dos macros). Não passam pela IA.
    # Falha aqui NUNCA quebra o motor: cai para vazio/None e o front-end degrada com elegância.
    try:
        kpis_setoriais = coletar_kpis_setoriais(ref=ref_kpi)
    except Exception as e:
        print(f"[setoriais] indisponível nesta rodada: {e}")
        kpis_setoriais = []
    try:
        pressoes_ipca = coletar_ipca_grupos(ref=ref_kpi)
    except Exception as e:
        print(f"[pressoes_ipca] indisponível nesta rodada: {e}")
        pressoes_ipca = None
    # mesma regra para setoriais e pressões: sem resposta da fonte, mantém o já publicado na semana
    if not kpis_setoriais:
        kpis_setoriais = [x for x in publicado.get("kpis_setoriais") or [] if not x.get("mkt")]
        if kpis_setoriais:
            print("[setoriais] fonte sem resposta — mantidos os valores oficiais já publicados nesta semana.")
    if not pressoes_ipca and publicado.get("pressoes_ipca"):
        pressoes_ipca = publicado["pressoes_ipca"]
        print("[pressoes_ipca] fonte sem resposta — mantido o quadro já publicado nesta semana.")

    # E-commerce: NÃO há série oficial gratuita. Se a coleta capturou a manchete mensal de uma
    # fonte de MERCADO (MCC-ENET/ABComm/Neotrust), publica com atribuição + badge de estimativa.
    try:
        ie = dados.get("indicador_ecommerce") or {}
        if ie.get("valor"):
            buf = "".join(c for c in str(ie["valor"]) if c.isdigit() or c in ".,-").replace(",", ".")
            try:
                pt = float(buf)
            except ValueError:
                pt = None
            fonte = ie.get("fonte") or "mercado"
            ref = ie.get("referencia") or ""
            cor = "up" if (pt or 0) > 0 else ("down" if (pt or 0) < 0 else "neutral")
            kpis_setoriais = (kpis_setoriais or []) + [{
                "setor": "ecommerce", "setorLabel": "E-commerce", "label": f"E-commerce ({fonte})",
                "valor": str(ie["valor"]), "cor": cor,
                "sub": (ie.get("sub") or "Vendas do e-commerce")
                       + f" · estimativa de mercado · fonte {fonte}" + (f" · {ref}" if ref else ""),
                "ref": ref, "pt": pt, "acum": None, "flow": True, "unit": "%", "mkt": True,
            }]
    except Exception as e:
        print(f"[ecommerce] indicador de mercado indisponível nesta rodada: {e}")

    saida = {
        "periodo": chave, "label": label, "status": status,
        "gerado_em": datetime.utcnow().isoformat(),
        "editorial": editorial,  # análise longitudinal automática (pode ser None)
        "clipping": normalizar_clipping(dados.get("clipping", [])),
        "pestel": dados.get("pestel", []),
        "kpis": kpis_final,
        "kpis_setoriais": kpis_setoriais,   # Serviços/PMS, Construção/SINAPI, Agro/LSPA
        "pressoes_ipca": pressoes_ipca,     # impacto por grupo (IBGE/SIDRA 7060)
        "porter": dados.get("porter", {}),   # 5 Forças por setor (avaliação estrutural)
        "analise": dados.get("analise"),     # leitura acionável por setor + ações do Panorama (dinâmica por semana)
        "longitudinal": longitudinal,
    }
    os.makedirs("data", exist_ok=True)
    with open(f"data/{chave}.json", "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)

    # ultimo.json aponta SEMPRE para a semana mais recente que existe.
    # Só sobrescreve se esta semana for >= à que está em ultimo.json —
    # assim o backfill (que processa semanas passadas) NÃO rebaixa o "último".
    def _ordem(ch):
        try:
            a, s = ch.split("-W"); return int(a) * 100 + int(s)
        except (ValueError, AttributeError):
            return -1
    deve_gravar_ultimo = True
    try:
        if os.path.exists("data/ultimo.json"):
            with open("data/ultimo.json", encoding="utf-8") as f:
                atual_ultimo = json.load(f)
            if _ordem(chave) < _ordem(atual_ultimo.get("periodo", "")):
                deve_gravar_ultimo = False  # esta semana é mais antiga: não rebaixa
    except (json.JSONDecodeError, OSError):
        deve_gravar_ultimo = True
    if deve_gravar_ultimo:
        with open("data/ultimo.json", "w", encoding="utf-8") as f:
            json.dump(saida, f, ensure_ascii=False, indent=2)

    # Mantém o índice de períodos disponíveis (o seletor temporal do portal lê daqui).
    # Lê o índice existente, adiciona/atualiza esta semana, mantém ordenado (mais recente primeiro).
    index_path = "data/index.json"
    indice = {"semanas": []}
    if os.path.exists(index_path):
        try:
            with open(index_path, encoding="utf-8") as f:
                indice = json.load(f)
        except (json.JSONDecodeError, OSError):
            indice = {"semanas": []}

    # extrai ano e número da semana da chave (ex: "2026-W27")
    try:
        ano_s, sem_s = chave.split("-W")
        ordem = int(ano_s) * 100 + int(sem_s)
    except ValueError:
        ordem = 0

    entrada = {"chave": chave, "label": label, "arquivo": f"{chave}.json", "ordem": ordem,
               "status": status}
    # remove entrada antiga desta mesma semana (se for repetição) e insere a nova
    indice["semanas"] = [s for s in indice.get("semanas", []) if s.get("chave") != chave]
    indice["semanas"].append(entrada)
    indice["semanas"].sort(key=lambda s: s.get("ordem", 0), reverse=True)
    indice["atualizado_em"] = datetime.utcnow().isoformat()

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(indice, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────────────────
# ENTRADA: preparar → (Claude: coleta.json) → processar → (Claude: editorial.txt) → publicar
# ─────────────────────────────────────────────────────────
TRAB = "trabalho"          # a partir da rotina diária: pasta VERSIONADA (a nuvem continua de onde parou)
PRIMEIRA_SEMANA_DIARIA = "2026-W46"


def _pasta(chave):
    base = TRAB if _ordem_chave(chave) >= _ordem_chave(PRIMEIRA_SEMANA_DIARIA) else RAW
    p = os.path.join(base, chave)
    os.makedirs(p, exist_ok=True)
    return p


def _ultimo_ciclo(T):
    return TM.ultimo_ciclo(T)


def _semana_anterior(chave):
    a, s = chave.split("-W")
    seg = date.fromisocalendar(int(a), int(s), 1) - timedelta(days=7)
    ano, sem, _ = seg.isocalendar()
    return f"{ano}-W{sem:02d}"


def _checar_ordem(T, chave, permitir_pulo):
    """A memória só avança em ordem: a semana anterior a esta precisa já estar nela.
    Repetir a MESMA semana é permitido (atualização de quinta)."""
    ult = _ultimo_ciclo(T)
    if _ordem_chave(chave) < _ordem_chave(ult):
        sys.exit(f"[motor] ERRO: a memória já está em {ult}; {chave} é anterior. "
                 f"Semanas passadas só podem ser processadas em ordem cronológica.")
    if chave != ult and _semana_anterior(chave) != ult and not permitir_pulo:
        sys.exit(f"[motor] ERRO: a memória está em {ult} e a próxima semana esperada é a "
                 f"seguinte a ela — não {chave}. Use --pular só se o salto for intencional.")


def cmd_preparar(chave, label, ini, fim, permitir_pulo):
    T, C = TM.carregar()
    _checar_ordem(T, chave, permitir_pulo)
    pasta = _pasta(chave)
    prompt = montar_prompt(label, ini, fim, TM.texto_para_coleta(T, C, _semana_anterior(chave)))
    with open(os.path.join(pasta, "prompt_coleta.md"), "w", encoding="utf-8") as f:
        f.write(prompt)
    print(f"[motor] {label} ({chave}) · {ini} a {fim} · {len(T['temas'])} temas na memória")
    print(f"[motor] Prompt da coleta: {pasta}/prompt_coleta.md")
    print(f"[motor] Próximo: gravar a coleta em {pasta}/coleta.json e rodar 'processar {chave}'")


def _ler_coleta(pasta):
    fn = os.path.join(pasta, "coleta.json")
    if not os.path.exists(fn):
        sys.exit(f"[motor] ERRO: falta {fn}")
    with open(fn, encoding="utf-8") as f:
        return extrair_json(f.read())


def cmd_processar(chave, label, permitir_pulo, forcar):
    pasta = _pasta(chave)
    marca = os.path.join(pasta, "processado.json")
    if os.path.exists(marca) and not forcar:
        sys.exit(f"[motor] ERRO: {chave} já foi processada ({marca}). Reprocessar duplicaria "
                 f"leituras; restaure {pasta}/temas_antes.json ou use --forcar.")
    T, C = TM.carregar()
    _checar_ordem(T, chave, permitir_pulo)
    dados = _ler_coleta(pasta)

    erros, avisos, resumo = conferir_coleta(dados, T)
    print(f"[motor] Coleta: {resumo}")
    for a in avisos:
        print(f"[motor] aviso: {a}")
    if erros:
        for e in erros:
            print(f"[motor] ERRO: {e}")
        sys.exit("[motor] Coleta reprovada na conferência — nada foi gravado.")

    with open(os.path.join(pasta, "temas_antes.json"), "w", encoding="utf-8") as f:
        json.dump(T, f, ensure_ascii=False, indent=1)
    n_lei = len(T.get("leituras", []))
    criados, novas = TM.registrar(T, C, chave, dados.get("clipping", []), dados.get("novos_temas"),
                                  _data_ref(chave).isoformat())
    TM.consolidar_leituras(T, chave, dados.get("leituras_temas"))
    TM.salvar(T, C)
    print(f"[motor] Memória de temas atualizada: leituras {n_lei}→{len(T['leituras'])}, "
          f"{len(C['semanas'].get(chave, []))} notícias classificadas, "
          f"{len(novas)} palavras novas, {len(criados)} temas novos")

    prompt, n_ativos = montar_prompt_editorial(T, C, chave, label, dados)
    with open(os.path.join(pasta, "prompt_editorial.md"), "w", encoding="utf-8") as f:
        f.write(prompt)
    with open(marca, "w", encoding="utf-8") as f:
        json.dump({"chave": chave, "em": _agora(), "n_temas_considerados": n_ativos,
                   "avisos": avisos}, f, ensure_ascii=False, indent=2)
    print(f"[motor] Prompt do editorial: {pasta}/prompt_editorial.md")
    print(f"[motor] Próximo: gravar o texto em {pasta}/editorial.txt e rodar 'publicar {chave}'")


def cmd_publicar(chave, label):
    pasta = _pasta(chave)
    marca = os.path.join(pasta, "processado.json")
    if not os.path.exists(marca):
        sys.exit(f"[motor] ERRO: rode 'processar {chave}' antes de publicar.")
    T, C = TM.carregar()
    if _ultimo_ciclo(T) != chave:
        sys.exit(f"[motor] ERRO: a memória já avançou para {_ultimo_ciclo(T)}; publicar {chave} "
                 f"agora mostraria o longitudinal de outra semana.")
    with open(marca, encoding="utf-8") as f:
        info = json.load(f)
    dados = _ler_coleta(pasta)

    editorial = None
    fn_ed = os.path.join(pasta, "editorial.txt")
    if os.path.exists(fn_ed):
        with open(fn_ed, encoding="utf-8") as f:
            texto = f.read().strip()
        if texto:
            n = _palavras(texto)
            if not 280 <= n <= 360:
                print(f"[motor] aviso: editorial com {n} palavras (meta 280-360)")
            editorial = {"texto": texto, "gerado_em": datetime.utcnow().isoformat(),
                         "n_temas_considerados": info.get("n_temas_considerados"),
                         "modelo": "claude"}
    if not editorial:
        print("[motor] aviso: sem editorial nesta edição (segue sem bloquear).")

    # semanas da rotina diária fecham com referência no domingo (órgãos publicam no fim de semana)
    ref = (_domingo_da_chave(chave) if _ordem_chave(chave) >= _ordem_chave(PRIMEIRA_SEMANA_DIARIA)
           else None)
    gerar_dados_portal(dados, T, C, chave, label, editorial, status="fechada", ref_kpi=ref)
    print(f"[motor] Publicado: data/{chave}.json (+ index.json/ultimo.json). Concluído.")


# ─────────────────────────────────────────────────────────
# ROTINA DIÁRIA (v4): atualizar → (análise, se houver gatilho) → previa;  fechar na segunda
#   - no dia a dia só a classificação da semana corrente é gravada (temas_noticias.json + dicionário);
#     as leituras dos temas são consolidadas uma vez, no 'fechar'
#   - gatilhos para reescrever análise são REGRA DE CÓDIGO (não julgamento da IA)
# ─────────────────────────────────────────────────────────
GATILHO_NOTICIAS_SETOR = 3
_KPI_SETOR = {"selic": "panorama", "ipca": "panorama", "cambio": "panorama",
              "desemprego": "panorama", "varejo": "comercio", "pim": "industria", "ipp": "industria"}


def _domingo_da_chave(chave):
    a, s = chave.split("-W")
    return date.fromisocalendar(int(a), int(s), 7)


def _ref_viva(chave):
    """Data de referência dos KPIs na rotina diária: hoje, limitado ao domingo da semana."""
    return min(date.today(), _domingo_da_chave(chave))


def _ler_json(fn, padrao=None):
    if not os.path.exists(fn):
        return padrao
    with open(fn, encoding="utf-8") as f:
        return json.load(f)


def _gravar_json(fn, obj):
    tmp = fn + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, fn)


def _base_coleta(chave):
    """Esqueleto de uma semana nova: PESTEL, Porter e análise herdados da última semana
    publicada (ponto de partida que os gatilhos vão atualizando); clipping vazio."""
    ant = _semana_anterior(chave)
    pub = _ler_json(f"data/{ant}.json", {}) or {}
    return {"clipping": [], "pestel": pub.get("pestel", []), "kpis": pub.get("kpis", []),
            "indicador_ecommerce": None, "porter": pub.get("porter", {}),
            "analise": pub.get("analise") or {"panorama": {"acoes": []}, "setores": {}},
            "leituras_temas": {}, "novos_temas": [], "_kpis_vistos": {}}


def _chave_item(it):
    fontes = it.get("fontes") or []
    url = (fontes[0].get("url") if fontes and isinstance(fontes[0], dict) else "") or ""
    url = re.sub(r"[?#].*$", "", url.strip().lower()).rstrip("/")
    return url or re.sub(r"\W+", " ", (it.get("titulo") or "").lower()).strip()


def _conferir_incremento(inc, T):
    """Mesmas regras de qualidade da coleta semanal, aplicadas só ao que entrou no dia."""
    erros = []
    for i, it in enumerate(inc.get("clipping", [])):
        if not it.get("titulo") or not it.get("texto"):
            erros.append(f"clipping[{i}] sem título/texto")
        if _palavras(it.get("texto", "")) > 35:
            erros.append(f"clipping[{i}] texto com mais de 35 palavras")
        setores = it.get("setores") or []
        if not setores or any(s not in SETORES + ("transversal",) for s in setores):
            erros.append(f"clipping[{i}] setores inválidos: {setores}")
        fontes = it.get("fontes") or []
        if not fontes or not all(url_valida(f.get("url", "")) for f in fontes):
            erros.append(f"clipping[{i}] sem fonte com URL válida")
    erros += TM.conferir(inc.get("clipping", []), inc.get("leituras_temas"), inc.get("novos_temas"), T)
    return erros


def _mesclar(coleta, inc):
    """Junta o incremento do dia à coleta da semana. Retorna as notícias realmente novas."""
    vistos = {_chave_item(it) for it in coleta["clipping"]}
    novas = []
    for it in inc.get("clipping", []):
        k = _chave_item(it)
        if k and k not in vistos:
            vistos.add(k)
            coleta["clipping"].append(it)
            novas.append(it)
    # leituras de tema: uma por tema na semana (a do dia mais recente prevalece; fontes somam;
    # materializado não volta atrás dentro da semana)
    lei = coleta.setdefault("leituras_temas", {})
    for tid, l in (inc.get("leituras_temas") or {}).items():
        velho = lei.get(tid)
        if velho:
            fontes = list(dict.fromkeys((velho.get("fontes") or []) + (l.get("fontes") or [])))
            mat = bool(velho.get("materializado")) or velho.get("status") == "materializado" \
                or bool(l.get("materializado"))
            velho.update(l)
            velho["fontes"] = fontes
            if mat:
                velho["materializado"] = True
                velho["status"] = "materializado"
        else:
            lei[tid] = dict(l)
    ids = {n["id"] for n in coleta.setdefault("novos_temas", [])}
    for n in inc.get("novos_temas") or []:
        if n["id"] not in ids:
            ids.add(n["id"])
            coleta["novos_temas"].append(n)
    return novas


def _gatilhos(coleta, inc, novas, T, C, chave):
    """REGRA (aprovada em 10/11/2026): reescreve a análise do setor quando
    (a) saiu um dos 7 indicadores, (b) um risco/oportunidade de tema materializou,
    (c) entraram >= 3 notícias novas no setor."""
    disparos = {}

    def _marca(setor, motivo):
        disparos.setdefault(setor, []).append(motivo)

    # (a) indicadores oficiais: compara com o que já tinha sido visto nesta semana
    try:
        oficiais = validar_kpis(coleta.get("kpis", []), ref=_ref_viva(chave), verbose=False)
    except Exception as e:
        print(f"[motor] aviso: KPIs oficiais indisponíveis nesta rodada ({e})")
        oficiais = coleta.get("kpis", [])
    vistos = coleta.setdefault("_kpis_vistos", {})
    for k in oficiais:
        b = _kpi_bucket(k.get("label"))
        assinatura = f"{k.get('valor')}|{k.get('sub', '')[:80]}"
        if b in _KPI_SETOR and k.get("fonte") and vistos.get(b) != assinatura:
            if b in vistos:   # primeira leitura da semana não é "divulgação nova"
                _marca(_KPI_SETOR[b], f"indicador {k.get('label')} atualizado: {k.get('valor')}")
            vistos[b] = assinatura
    coleta["kpis"] = oficiais
    # (b) materialização (setores = onde as notícias do tema caíram nas últimas 4 semanas)
    for tid, l in (inc.get("leituras_temas") or {}).items():
        if l.get("materializado") or l.get("status") == "materializado":
            for s in TM.setores_do_tema(T, C, chave, tid) or ["panorama"]:
                _marca("panorama" if s == "transversal" else s, f"tema materializou: {tid}")
    # (c) volume de notícias novas por setor
    cont = {}
    for it in novas:
        for s in it.get("setores", []):
            if s in SETORES:
                cont[s] = cont.get(s, 0) + 1
    for s, n in cont.items():
        if n >= GATILHO_NOTICIAS_SETOR:
            _marca(s, f"{n} notícias novas no setor")
    return disparos


def cmd_atualizar(chave, label):
    """Rodada diária, passo 1: incorpora trabalho/<semana>/incremento.json e calcula gatilhos."""
    pasta = _pasta(chave)
    fn_col, fn_inc = os.path.join(pasta, "coleta.json"), os.path.join(pasta, "incremento.json")
    T, C = TM.carregar()
    coleta = _ler_json(fn_col) or _base_coleta(chave)
    inc = _ler_json(fn_inc, {"clipping": []})
    erros = _conferir_incremento(inc, T)
    if erros:
        for e in erros:
            print(f"[motor] ERRO: {e}")
        sys.exit("[motor] Incremento reprovado — nada foi gravado.")
    novas = _mesclar(coleta, inc)
    hoje = date.today().isoformat()
    criados, palavras = TM.registrar(T, C, chave, coleta["clipping"], coleta.get("novos_temas"), hoje)
    TM.salvar(T, C)
    disparos = _gatilhos(coleta, inc, novas, T, C, chave)
    os.makedirs(os.path.join(pasta, "incrementos"), exist_ok=True)
    if os.path.exists(fn_inc):
        os.replace(fn_inc, os.path.join(pasta, "incrementos", f"{hoje}.json"))
    _gravar_json(fn_col, coleta)
    diario = _ler_json(os.path.join(pasta, "diario.json"), []) or []
    diario.append({"data": hoje, "em": _agora(), "noticias_novas": len(novas),
                   "total_semana": len(coleta["clipping"]), "gatilhos": disparos})
    _gravar_json(os.path.join(pasta, "diario.json"), diario)
    _gravar_json(os.path.join(pasta, "gatilhos.json"), {"data": hoje, "setores": disparos})
    print(f"[motor] {label}: +{len(novas)} notícias (semana: {len(coleta['clipping'])}) · "
          f"{len(palavras)} palavras novas no dicionário, {len(criados)} temas novos")
    if disparos:
        for s, m in disparos.items():
            print(f"[motor] GATILHO {s}: {'; '.join(m)}")
        print(f"[motor] Próximo: gravar {pasta}/analise.json com os setores acima e rodar 'previa {chave}'")
    else:
        print(f"[motor] Sem gatilho: análise segue como está. Próximo: 'previa {chave}'")


def _aplicar_analise(coleta, patch):
    """analise.json = {"setores": {setor: {...}}, "panorama": {"acoes": [...]}, "pestel": [...] }"""
    an = coleta.setdefault("analise", {"panorama": {"acoes": []}, "setores": {}})
    for s, v in (patch.get("setores") or {}).items():
        an.setdefault("setores", {})[s] = v
    if patch.get("panorama"):
        an["panorama"] = patch["panorama"]
    if patch.get("pestel"):
        coleta["pestel"] = patch["pestel"]


def _editorial_aberto(chave):
    """Editorial preditivo que ABRE a semana: o escrito no fechamento da semana anterior."""
    ant = _ler_json(f"data/{_semana_anterior(chave)}.json", {}) or {}
    ed = ant.get("editorial")
    if ed and ed.get("texto"):
        return dict(ed, abertura_de=ant.get("label", ""))
    return None


def cmd_previa(chave, label):
    """Rodada diária, passo 2: publica a semana corrente como 'em andamento' (leituras não consolidadas)."""
    pasta = _pasta(chave)
    coleta = _ler_json(os.path.join(pasta, "coleta.json"))
    if not coleta:
        sys.exit(f"[motor] ERRO: rode 'atualizar {chave}' antes da prévia.")
    fn_an = os.path.join(pasta, "analise.json")
    if os.path.exists(fn_an):
        _aplicar_analise(coleta, _ler_json(fn_an))
        os.makedirs(os.path.join(pasta, "analises"), exist_ok=True)
        os.replace(fn_an, os.path.join(pasta, "analises", f"{date.today().isoformat()}.json"))
        _gravar_json(os.path.join(pasta, "coleta.json"), coleta)
        print("[motor] Análise atualizada pelos gatilhos.")
    T, C = TM.carregar()
    gerar_dados_portal(coleta, T, C, chave, label, _editorial_aberto(chave),
                       status="em_andamento", ref_kpi=_ref_viva(chave),
                       leituras=coleta.get("leituras_temas") or None)
    print(f"[motor] Prévia publicada: data/{chave}.json (em andamento).")


def cmd_fechar(chave, label):
    """Fechamento (rodada de segunda): consolida a semana na memória UMA vez e pede o
    editorial preditivo. Depois: gravar editorial.txt e rodar 'publicar <semana>'."""
    cmd_processar(chave, label, permitir_pulo=False, forcar=False)


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    flags = {a for a in argv if a.startswith("--")}
    cmds = ("preparar", "processar", "publicar", "atualizar", "previa", "fechar")
    if not args or args[0] not in cmds:
        sys.exit("uso: python motor.py " + "|".join(cmds) + " [AAAA-Www] [--pular] [--forcar]")
    chave, label, ini, fim = periodo_atual(args[1] if len(args) > 1 else None)
    if args[0] == "preparar":
        cmd_preparar(chave, label, ini, fim, "--pular" in flags)
    elif args[0] in ("processar", "fechar"):
        cmd_processar(chave, label, "--pular" in flags, "--forcar" in flags)
    elif args[0] == "atualizar":
        cmd_atualizar(chave, label)
    elif args[0] == "previa":
        cmd_previa(chave, label)
    else:
        cmd_publicar(chave, label)


if __name__ == "__main__":
    main(sys.argv[1:])
