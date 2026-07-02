"""
MOTOR DO CLIPPING DE MERCADO
Roda no GitHub Actions toda segunda-feira.
Fluxo: carrega histórico do Supabase → chama Gemini com busca web →
processa resposta → recalcula relevância → grava de volta → gera dados do portal.
"""
import os
import json
import re
from datetime import date, datetime, timedelta

from google import genai
from google.genai import types
from supabase import create_client

from prompt_geracao import montar_prompt

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
MODELO       = "gemini-2.5-flash"   # modelo gratuito com busca nativa

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
# CHAMA O GEMINI com busca web nativa
# ─────────────────────────────────────────────────────────
def gerar_analise(prompt):
    client = genai.Client(api_key=GEMINI_KEY)
    grounding = types.Tool(google_search=types.GoogleSearch())
    resp = client.models.generate_content(
        model=MODELO,
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[grounding],
            temperature=0.4,
        ),
    )
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
- Texto CORRIDO, de fácil leitura, entre 180 e 280 palavras. Sem listas, sem tópicos.
- Estrutura implícita: (1) o quadro geral da semana; (2) o que evoluiu em relação às semanas
  anteriores — cite a trajetória, o que se confirmou ou mudou; (3) o que isso significa em termos
  práticos para os setores de indústria, comércio e serviços; (4) o ponto de atenção para as próximas semanas.
- Seja específico e ancorado nos dados e sinais fornecidos. Nada de generalidades vagas.
- Tom: sóbrio, seguro, de quem acompanha o cenário há tempo. Português do Brasil.

Responda SOMENTE com o texto do editorial, sem título, sem aspas, sem markdown."""

    try:
        client = genai.Client(api_key=GEMINI_KEY)
        resp = client.models.generate_content(
            model=MODELO,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.5),
        )
        texto = (resp.text or "").strip()
        if not texto:
            return None
        return {"texto": texto, "gerado_em": datetime.utcnow().isoformat(),
                "n_sinais_considerados": ctx["n_ativos"]}
    except Exception as e:
        print(f"[motor] Editorial falhou (não crítico): {e}")
        return None


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
            "ultima_observacao": ultima_obs, "periodo_observacao": ultima_per,
            "data_identificacao": s.get("data_identificacao", ""),
            "origem": s.get("origem") or "real",
        })

    saida = {
        "periodo": chave, "label": label,
        "gerado_em": datetime.utcnow().isoformat(),
        "editorial": editorial,  # análise longitudinal automática (pode ser None)
        "clipping": normalizar_clipping(dados.get("clipping", [])),
        "pestel": dados.get("pestel", []),
        "kpis": dados.get("kpis", []),
        "longitudinal": longitudinal,
    }
    os.makedirs("data", exist_ok=True)
    with open(f"data/{chave}.json", "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)
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
