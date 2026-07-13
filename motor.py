"""
MOTOR DO CLIPPING DE MERCADO
Roda no GitHub Actions toda segunda-feira.
Fluxo: carrega histórico do Supabase → chama Gemini com busca web →
processa resposta → recalcula relevância → grava de volta → gera dados do portal.
"""
import os
import json
import re
import glob
import time
from datetime import date, datetime, timedelta

from google import genai
from google.genai import types
from supabase import create_client

from prompt_geracao import montar_prompt
from kpis_oficiais import validar_kpis, coletar_kpis_setoriais, coletar_ipca_grupos

# ─────────────────────────────────────────────────────────
# CONFIGURAÇÃO (as chaves vêm dos GitHub Secrets via ambiente)
# ─────────────────────────────────────────────────────────
GEMINI_KEY   = os.environ["GEMINI_API_KEY"].strip()
# Limpa a URL do Supabase: remove espaços, o sufixo /rest/v1 (caminho interno
# que a biblioteca adiciona sozinha) e barra(s) no final. Deixa só o domínio raiz.
_raw_url = os.environ["SUPABASE_URL"].strip()
_raw_url = _raw_url.rstrip("/")
if _raw_url.endswith("/rest/v1"):
    _raw_url = _raw_url[:-len("/rest/v1")]
SUPABASE_URL = _raw_url.rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_KEY"].strip()
MODELO          = "gemini-2.5-flash"        # primário: busca nativa, free tier
# Fallback com COTA DIÁRIA SEPARADA (limite por modelo, não por chave). Suporta
# grounding com Google Search e é o substituto vivo do extinto gemini-2.0-flash
# (desligado pela Google em 01/06/2026). Usar SEMPRE o string estável, não o -preview.
MODELO_FALLBACK = "gemini-2.5-flash-lite"   # cota diária independente do primário

# limiar abaixo do qual um sinal "dorme" após ciclos sem aparecer
LIMIAR_DORMIR = 25.0
CICLOS_PARA_DORMIR = 3

# ─────────────────────────────────────────────────────────
# FONTES OFICIAIS: mapa palavra-chave → homepage oficial.
# Usado como fallback quando o Gemini devolve URL inválida/proibida.
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
# FÓRMULA DE RELEVÂNCIA (espelha a função SQL do Supabase)
# ─────────────────────────────────────────────────────────
def calcular_relevancia(severidade, iminencia, persistencia, corroboracao,
                        materializado, ciclos_sem_aparecer):
    base = (severidade * 0.35 + iminencia * 0.25
            + min(persistencia, 10) * 0.20
            + min(corroboracao, 10) * 0.20)
    mult = 1.25 if materializado else 1.0
    decay = max(1.0 - (ciclos_sem_aparecer * 0.10), 0.4)
    return round(min(base * 10 * mult * decay, 100), 2)


# ─────────────────────────────────────────────────────────
# PERÍODO: calcula o rótulo da semana ISO atual
# ─────────────────────────────────────────────────────────
def periodo_atual():
    hoje = date.today()
    ano, semana, _ = hoje.isocalendar()
    inicio = hoje - timedelta(days=hoje.weekday())
    fim = inicio + timedelta(days=4)
    meses = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
             "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
    label = f"Semana {semana} · {meses[inicio.month]} {ano}"
    chave = f"{ano}-W{semana:02d}"
    return chave, label, inicio.isoformat(), fim.isoformat()


def _sexta_da_chave(chave):
    """Sexta-feira (ISO) da semana da chave 'AAAA-Www' — data de referência dos KPIs oficiais."""
    try:
        a, s = chave.split("-W")
        return date.fromisocalendar(int(a), int(s), 5)
    except (ValueError, AttributeError):
        return date.today()


# ─────────────────────────────────────────────────────────
# EXTRAI JSON da resposta do Gemini (tolerante a lixo em volta)
# ─────────────────────────────────────────────────────────
def extrair_json(texto):
    # remove cercas de markdown se houver
    texto = re.sub(r"^```(?:json)?|```$", "", texto.strip(), flags=re.MULTILINE).strip()
    # pega do primeiro { ao último }
    ini = texto.find("{")
    fim = texto.rfind("}")
    if ini == -1 or fim == -1:
        raise ValueError("Resposta do Gemini não contém JSON.")
    return json.loads(texto[ini:fim + 1])


# ─────────────────────────────────────────────────────────
# FALLBACK DE MODELO: se a COTA DIÁRIA do primário estourar, desvia para o
# secundário (cota diária independente). Não confundir com o limite por MINUTO
# (RPM), que se resolve esperando segundos — esse é tratado por backoff.
# ─────────────────────────────────────────────────────────
def _cota_diaria_esgotada(err):
    """True só quando o erro indica esgotamento da cota DIÁRIA (RPD), que não
    adianta esperar segundos — ela só renova à meia-noite (Pacífico)."""
    s = str(err).lower()
    esgotou = any(t in s for t in ("resource_exhausted", "429", "quota", "exhausted"))
    marca_diaria = any(t in s for t in ("perday", "per day", "requests per day", "daily"))
    return esgotou and marca_diaria


def _gerar(client, prompt, config):
    """Chama o primário; se a cota DIÁRIA do primário estourar, refaz no fallback.
    Retorna (resposta, modelo_usado)."""
    try:
        return client.models.generate_content(
            model=MODELO, contents=prompt, config=config), MODELO
    except Exception as e:
        if _cota_diaria_esgotada(e):
            print(f"[motor] Cota diária de {MODELO} esgotada — desviando para {MODELO_FALLBACK}.")
            return client.models.generate_content(
                model=MODELO_FALLBACK, contents=prompt, config=config), MODELO_FALLBACK
        raise


# ─────────────────────────────────────────────────────────
# CHAMA O GEMINI com busca web nativa
# ─────────────────────────────────────────────────────────
def gerar_analise(prompt):
    client = genai.Client(api_key=GEMINI_KEY)
    grounding = types.Tool(google_search=types.GoogleSearch())
    # 6 setores + porter geram uma resposta maior; eleva o teto de saída para
    # evitar truncamento (2.5-flash suporta até 65k tokens de saída). Continua no free.
    config = types.GenerateContentConfig(
        tools=[grounding], temperature=0.4, max_output_tokens=65536)
    resp, modelo = _gerar(client, prompt, config)
    if modelo != MODELO:
        print(f"[motor] Coleta concluída via fallback ({modelo}).")
    return resp.text


# ─────────────────────────────────────────────────────────
# PROCESSA a resposta e atualiza o Supabase
# ─────────────────────────────────────────────────────────
def processar(dados, sb, chave_periodo, sinais_ativos):
    # mapa dos sinais que existiram antes (para detectar quais NÃO reapareceram)
    reaparecidos = set()

    # 1. ATUALIZAÇÕES de sinais existentes
    for upd in dados.get("atualizacoes_sinais", []):
        sid = upd["id"]
        sinal = next((s for s in sinais_ativos if s["id"] == sid), None)
        if not sinal:
            continue
        reaparecidos.add(sid)

        # CICLO ≠ EXECUÇÃO: só conta ciclo novo se este sinal ainda não teve
        # ciclo contado NESTA semana. Repetições na mesma semana (2ª automática
        # ou botão) atualizam texto/status/corroboração, mas NÃO incrementam
        # persistência — preservando a calibração de 1 ciclo = 1 semana.
        ciclo_novo = (sinal.get("ultimo_ciclo_contado") != chave_periodo)

        if ciclo_novo and upd.get("reapareceu"):
            nova_persistencia = sinal["persistencia"] + 1
        else:
            nova_persistencia = sinal["persistencia"]

        nova_corroboracao = sinal["corroboracao"] + len(upd.get("fontes", []))
        materializado = upd.get("materializado", sinal["materializado"])
        sev = upd.get("severidade", sinal["severidade"])
        imin = upd.get("iminencia", sinal["iminencia"])

        relev = calcular_relevancia(sev, imin, nova_persistencia,
                                    nova_corroboracao, materializado, 0)
        pico = max(relev, sinal["relevancia_pico"])

        campos = {
            "status": upd.get("novo_status", sinal["status"]),
            "severidade": sev, "iminencia": imin,
            "persistencia": nova_persistencia, "corroboracao": nova_corroboracao,
            "materializado": materializado, "ciclos_sem_aparecer": 0,
            "relevancia_atual": relev, "relevancia_pico": pico,
            "ultimo_periodo": chave_periodo,
            "atualizado_em": datetime.utcnow().isoformat(),
        }
        if ciclo_novo:
            campos["ultimo_ciclo_contado"] = chave_periodo
        sb.table("sinais").update(campos).eq("id", sid).execute()

        sb.table("observacoes").insert({
            "sinal_id": sid, "periodo": chave_periodo,
            "texto": upd["texto_observacao"],
            "status_resultante": upd.get("novo_status", sinal["status"]),
            "relevancia_resultante": relev,
            "fontes": upd.get("fontes", []),
            "delta": round(relev - sinal["relevancia_atual"], 2),
        }).execute()

    # 2. SINAIS que NÃO reapareceram → decaimento (SÓ em ciclo novo)
    for sinal in sinais_ativos:
        if sinal["id"] in reaparecidos:
            continue
        # Se este sinal já teve ciclo contado nesta semana, é repetição:
        # não decai de novo. O decaimento só acontece uma vez por semana.
        if sinal.get("ultimo_ciclo_contado") == chave_periodo:
            continue
        ciclos = sinal["ciclos_sem_aparecer"] + 1
        relev = calcular_relevancia(sinal["severidade"], sinal["iminencia"],
                                    sinal["persistencia"], sinal["corroboracao"],
                                    sinal["materializado"], ciclos)
        novo_status = sinal["status"]
        if relev < LIMIAR_DORMIR and ciclos >= CICLOS_PARA_DORMIR:
            novo_status = "dormindo"
        sb.table("sinais").update({
            "ciclos_sem_aparecer": ciclos, "relevancia_atual": relev,
            "status": novo_status,
            "ultimo_ciclo_contado": chave_periodo,
            "atualizado_em": datetime.utcnow().isoformat(),
        }).eq("id", sinal["id"]).execute()

    # 3. NOVOS sinais
    for novo in dados.get("novos_sinais", []):
        relev = calcular_relevancia(novo["severidade"], novo["iminencia"],
                                    1, len(novo.get("fontes", [])),
                                    novo.get("materializado", False), 0)
        res = sb.table("sinais").insert({
            "tipo": novo["tipo"], "titulo": novo["titulo"],
            "dimensao": novo["dimensao"], "setores": novo["setores"],
            "data_identificacao": date.today().isoformat(),
            "status": "materializado" if novo.get("materializado") else "monitorar",
            "severidade": novo["severidade"], "iminencia": novo["iminencia"],
            "persistencia": 1, "corroboracao": len(novo.get("fontes", [])),
            "materializado": novo.get("materializado", False),
            "ciclos_sem_aparecer": 0,
            "relevancia_atual": relev, "relevancia_pico": relev,
            "data_pico": date.today().isoformat(),
            "ultimo_periodo": chave_periodo,
            "ultimo_ciclo_contado": chave_periodo,
        }).execute()
        sid = res.data[0]["id"]
        sb.table("observacoes").insert({
            "sinal_id": sid, "periodo": chave_periodo,
            "texto": novo["texto"], "status_resultante": "monitorar",
            "relevancia_resultante": relev, "fontes": novo.get("fontes", []),
            "delta": relev,
        }).execute()


# ─────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────
def main():
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    chave, label, ini, fim = periodo_atual()
    print(f"[motor] Período: {label} ({chave})")

    # carrega sinais ativos (não dormindo) para a revisão longitudinal
    resp = sb.table("sinais").select("*").neq("status", "dormindo").execute()
    sinais_ativos = resp.data
    print(f"[motor] {len(sinais_ativos)} sinais ativos carregados do Supabase")

    prompt = montar_prompt(label, ini, fim, sinais_ativos)
    print("[motor] Chamando Gemini com busca web...")
    texto = gerar_analise(prompt)

    dados = extrair_json(texto)
    print(f"[motor] JSON recebido: {len(dados.get('clipping', []))} notícias, "
          f"{len(dados.get('novos_sinais', []))} novos sinais, "
          f"{len(dados.get('atualizacoes_sinais', []))} atualizações")

    processar(dados, sb, chave, sinais_ativos)
    print("[motor] Supabase atualizado.")

    # gera o EDITORIAL longitudinal (lê a memória inteira do sistema)
    print("[motor] Gerando editorial analítico...")
    editorial = gerar_editorial(sb, chave, label, dados)
    if editorial:
        print(f"[motor] Editorial gerado ({editorial['n_sinais_considerados']} sinais considerados).")
    else:
        print("[motor] Sem editorial nesta edição (segue sem bloquear).")

    # gera o arquivo de dados do portal (o HTML lê daqui)
    gerar_dados_portal(dados, sb, chave, label, editorial)
    print("[motor] Concluído com sucesso.")



def _coletar_contexto_editorial(sb, chave, dados):
    """Reúne as TRÊS camadas que tornam o editorial longitudinal:
       (1) estado atual, (2) trajetória histórica dos sinais, (3) editorial anterior."""
    # (1) sinais ativos ranqueados por relevância — a fotografia de agora
    ativos = sb.table("sinais").select("*").neq("status", "dormindo") \
               .order("relevancia_atual", desc=True).limit(15).execute().data

    # (2) trajetória: para cada sinal ativo, as últimas 4 observações (evolução no tempo)
    trajetorias = []
    for s in ativos:
        try:
            obs = sb.table("observacoes").select("periodo,texto,status_resultante,relevancia_resultante") \
                    .eq("sinal_id", s["id"]).order("criado_em", desc=True).limit(4).execute().data
        except Exception:
            obs = []
        historico = " | ".join(
            f"{o.get('periodo','?')}: {o.get('status_resultante','')} (rel {o.get('relevancia_resultante','?')})"
            for o in reversed(obs)
        )
        trajetorias.append(
            f"- [{s['tipo'].upper()}] \"{s['titulo']}\" (dim {s['dimensao']}, setores {','.join(s['setores'])}) "
            f"| relevância atual {s['relevancia_atual']}, pico {s.get('relevancia_pico','?')}, "
            f"status {s['status']} | trajetória: {historico or 'primeira aparição'}"
        )

    # sinais que MUDARAM de status recentemente (materializados/adormecidos este ciclo)
    materializados = [s for s in ativos if s["status"] == "materializado"]
    novos = dados.get("novos_sinais", [])

    # (3) editorial da semana anterior — para dar continuidade narrativa
    editorial_anterior = ""
    try:
        if os.path.exists("data/ultimo.json"):
            with open("data/ultimo.json", encoding="utf-8") as f:
                ant = json.load(f)
            editorial_anterior = (ant.get("editorial") or {}).get("texto", "")
    except Exception:
        editorial_anterior = ""

    return {
        "trajetorias": trajetorias,
        "n_ativos": len(ativos),
        "n_materializados": len(materializados),
        "materializados": [s["titulo"] for s in materializados],
        "novos": [n.get("titulo", "") for n in novos],
        "editorial_anterior": editorial_anterior,
        "kpis": dados.get("kpis", []),
    }


def gerar_editorial(sb, chave, label, dados):
    """Gera a análise editorial longitudinal — lê a MEMÓRIA inteira do sistema,
       não só a semana. Retorna dict {texto, gerado_em} ou None em caso de falha."""
    ctx = _coletar_contexto_editorial(sb, chave, dados)

    kpis_txt = " | ".join(f"{k.get('label','')}: {k.get('valor','')} ({k.get('sub','')})"
                          for k in ctx["kpis"])
    traj_txt = "\n".join(ctx["trajetorias"]) or "(sem sinais acumulados ainda)"
    cont_txt = (f"No editorial da semana anterior, escrevemos:\n\"{ctx['editorial_anterior']}\"\n"
                f"Dê continuidade: confirme, ajuste ou contraste aquela leitura com o que mudou."
                if ctx["editorial_anterior"] else
                "Esta é a primeira edição do editorial — estabeleça a leitura de base do cenário.")

    prompt = f"""Você é o analista-chefe de inteligência de mercado da Nexos, escrevendo o
EDITORIAL DA SEMANA para {label}. Este texto é a leitura estratégica que sintetiza
tudo o que o sistema sabe — não apenas os dados desta semana, mas a memória acumulada
de riscos e oportunidades ao longo das semanas.

# INDICADORES DA SEMANA
{kpis_txt}

# MEMÓRIA LONGITUDINAL — sinais acumulados e sua evolução no tempo
{traj_txt}

# MUDANÇAS RELEVANTES NESTE CICLO
- Sinais já materializados (o previsto ocorreu): {', '.join(ctx['materializados']) or 'nenhum'}
- Novos sinais identificados esta semana: {', '.join(ctx['novos']) or 'nenhum'}

# CONTINUIDADE NARRATIVA
{cont_txt}

# COMO ESCREVER
- Linguagem FORMAL, mas SEM jargão técnico. Um empresário de PME deve entender sem dicionário.
  Se precisar citar um termo técnico (ex: SELIC), explique em poucas palavras na própria frase.
- DENSIDADE é a regra: texto CORRIDO de 280 a 360 palavras, analítico e sem listas. Cada frase carrega
  informação (número, evento, fonte) — nada de generalidade, adjetivo vazio ou enchimento.
- Cubra, nesta ordem e ancorado nos dados: (1) o quadro macro da semana (Selic, IPCA, câmbio, atividade)
  com os números-chave; (2) o que MUDOU frente às semanas anteriores (novos sinais, o que materializou);
  (3) uma leitura enxuta por bloco setorial (indústria; comércio e serviços; agro; construção; e-commerce),
  citando o fato concreto de cada um; (4) o ponto de atenção para as próximas semanas. Priorize o acionável.
- Seja específico e ancorado nos dados e sinais fornecidos. Nada de generalidades vagas.
- Tom: sóbrio, seguro, de quem acompanha o cenário há tempo. Português do Brasil.

Responda SOMENTE com o texto do editorial, sem título, sem aspas, sem markdown."""

    # Retry com backoff: a 2ª chamada ao Gemini (editorial) costuma bater no
    # rate limit da cota gratuita logo após a coleta pesada. Espera e tenta de novo.
    client = genai.Client(api_key=GEMINI_KEY)
    esperas = [0, 20, 40]  # 1ª tentativa imediata; depois espera 20s, 40s
    ultimo_erro = None
    for i, espera in enumerate(esperas):
        if espera:
            print(f"[motor] Editorial: aguardando {espera}s antes de nova tentativa (rate limit)...")
            time.sleep(espera)
        try:
            resp, modelo = _gerar(
                client, prompt, types.GenerateContentConfig(temperature=0.5))
            texto = (resp.text or "").strip()
            if texto:
                return {"texto": texto, "gerado_em": datetime.utcnow().isoformat(),
                        "n_sinais_considerados": ctx["n_ativos"], "modelo": modelo}
            ultimo_erro = "resposta vazia"
        except Exception as e:
            ultimo_erro = str(e)
            print(f"[motor] Editorial tentativa {i+1}/{len(esperas)} falhou: {e}")

    # ÚLTIMO RECURSO: uma tentativa limpa no modelo secundário, seja qual for o erro
    # do primário (cota diária, limite por minuto travado ou erro ambíguo). O secundário
    # tem cota/limites independentes, então costuma passar quando o primário está saturado.
    try:
        print(f"[motor] Editorial: última tentativa no fallback {MODELO_FALLBACK}...")
        resp = genai.Client(api_key=GEMINI_KEY).models.generate_content(
            model=MODELO_FALLBACK, contents=prompt,
            config=types.GenerateContentConfig(temperature=0.5))
        texto = (resp.text or "").strip()
        if texto:
            print(f"[motor] Editorial gerado no fallback {MODELO_FALLBACK}.")
            return {"texto": texto, "gerado_em": datetime.utcnow().isoformat(),
                    "n_sinais_considerados": ctx["n_ativos"], "modelo": MODELO_FALLBACK}
    except Exception as e:
        ultimo_erro = str(e)
        print(f"[motor] Editorial: fallback {MODELO_FALLBACK} também falhou: {e}")

    print(f"[motor] Editorial não gerado após {len(esperas)} tentativas + fallback ({ultimo_erro}).")
    return None


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
    a semana de referência. Não depende do Gemini obedecer — é código puro.
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
                cand = next((x for x in kpis_ant
                             if _kpi_bucket(x.get("label")) == bucket
                             and not _kpi_indisponivel(_kpi_sem_proj(x.get("valor")))),
                            None)
                if cand:
                    kk["valor"] = _kpi_sem_proj(cand.get("valor"))
                    kk["sub"] = (f"Sem divulgação nesta semana; "
                                 f"último dado conhecido ({lbl_ant}).")
                    kk["herdado_de"] = lbl_ant
                    break
        saida.append(kk)
    return saida


def gerar_dados_portal(dados, sb, chave, label, editorial=None):
    """Gera data/<periodo>.json que o frontend consome."""
    # busca os sinais mais relevantes para a revisão longitudinal do portal
    top = sb.table("sinais").select("*").neq("status", "dormindo") \
            .order("relevancia_atual", desc=True).limit(9).execute()

    # para cada sinal do topo, busca a observação mais recente (o texto vivo da trajetória)
    longitudinal = []
    for s in top.data:
        ultima_obs, ultima_per = "", ""
        try:
            obs = sb.table("observacoes").select("texto,periodo") \
                    .eq("sinal_id", s["id"]) \
                    .order("criado_em", desc=True).limit(1).execute()
            if obs.data:
                ultima_obs = obs.data[0].get("texto", "")
                ultima_per = obs.data[0].get("periodo", "")
        except Exception:
            pass  # sem observação: o portal usa um texto padrão
        longitudinal.append({
            "id": s["id"], "tipo": s["tipo"], "titulo": s["titulo"],
            "dimensao": s["dimensao"], "setores": s["setores"],
            "status": s["status"], "relevancia": s["relevancia_atual"],
            # eixos da Matriz Risco × Oportunidade (impacto = severidade, iminência)
            "severidade": s.get("severidade"), "iminencia": s.get("iminencia"),
            "ultima_observacao": ultima_obs, "periodo_observacao": ultima_per,
            "data_identificacao": s.get("data_identificacao", ""),
            "origem": s.get("origem") or "real",
        })

    # BLINDAGEM DE ACURÁCIA: o Gemini busca, mas os NÚMEROS macro são validados/
    # sobrepostos pelos valores OFICIAIS (BCB/IBGE) válidos na sexta desta semana,
    # já com acumulado no ano. Se a API oficial falhar, mantém o valor do Gemini.
    ref_kpi = _sexta_da_chave(chave)
    kpis_validados = validar_kpis(dados.get("kpis", []), ref=ref_kpi)
    # ponto 1a — herança determinística caso algum indicador não venha da API oficial
    kpis_final = reconciliar_kpis(kpis_validados, chave)
    # indicadores setoriais + pressões do IPCA por grupo: OFICIAIS (IBGE), determinísticos.
    # Válidos na sexta desta semana (mesma lógica de defasagem dos macros). Não passam pelo Gemini.
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

    # E-commerce: NÃO há série oficial gratuita. Se o Gemini capturou a manchete mensal de uma
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
        "periodo": chave, "label": label,
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

    entrada = {"chave": chave, "label": label, "arquivo": f"{chave}.json", "ordem": ordem}
    # remove entrada antiga desta mesma semana (se for repetição) e insere a nova
    indice["semanas"] = [s for s in indice.get("semanas", []) if s.get("chave") != chave]
    indice["semanas"].append(entrada)
    indice["semanas"].sort(key=lambda s: s.get("ordem", 0), reverse=True)
    indice["atualizado_em"] = datetime.utcnow().isoformat()

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(indice, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
