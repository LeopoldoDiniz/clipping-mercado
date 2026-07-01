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
GEMINI_KEY   = os.environ["GEMINI_API_KEY"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
MODELO       = "gemini-2.5-flash"   # modelo gratuito com busca nativa

# limiar abaixo do qual um sinal "dorme" após ciclos sem aparecer
LIMIAR_DORMIR = 25.0
CICLOS_PARA_DORMIR = 3


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
    # mapa dos sinais que existiam antes (para detectar quais NÃO reapareceram)
    reaparecidos = set()

    # 1. ATUALIZAÇÕES de sinais existentes
    for upd in dados.get("atualizacoes_sinais", []):
        sid = upd["id"]
        sinal = next((s for s in sinais_ativos if s["id"] == sid), None)
        if not sinal:
            continue
        reaparecidos.add(sid)

        nova_persistencia = sinal["persistencia"] + (1 if upd.get("reapareceu") else 0)
        nova_corroboracao = sinal["corroboracao"] + len(upd.get("fontes", []))
        materializado = upd.get("materializado", sinal["materializado"])
        sev = upd.get("severidade", sinal["severidade"])
        imin = upd.get("iminencia", sinal["iminencia"])

        relev = calcular_relevancia(sev, imin, nova_persistencia,
                                    nova_corroboracao, materializado, 0)
        pico = max(relev, sinal["relevancia_pico"])

        sb.table("sinais").update({
            "status": upd.get("novo_status", sinal["status"]),
            "severidade": sev, "iminencia": imin,
            "persistencia": nova_persistencia, "corroboracao": nova_corroboracao,
            "materializado": materializado, "ciclos_sem_aparecer": 0,
            "relevancia_atual": relev, "relevancia_pico": pico,
            "ultimo_periodo": chave_periodo,
            "atualizado_em": datetime.utcnow().isoformat(),
        }).eq("id", sid).execute()

        sb.table("observacoes").insert({
            "sinal_id": sid, "periodo": chave_periodo,
            "texto": upd["texto_observacao"],
            "status_resultante": upd.get("novo_status", sinal["status"]),
            "relevancia_resultante": relev,
            "fontes": upd.get("fontes", []),
            "delta": round(relev - sinal["relevancia_atual"], 2),
        }).execute()

    # 2. SINAIS que NÃO reapareceram → decaimento
    for sinal in sinais_ativos:
        if sinal["id"] in reaparecidos:
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

    # gera o arquivo de dados do portal (o HTML lê daqui)
    gerar_dados_portal(dados, sb, chave, label)
    print("[motor] Concluído com sucesso.")


def gerar_dados_portal(dados, sb, chave, label):
    """Gera data/<periodo>.json que o frontend consome."""
    # busca os sinais mais relevantes para a revisão longitudinal do portal
    top = sb.table("sinais").select("*").neq("status", "dormindo") \
            .order("relevancia_atual", desc=True).limit(9).execute()

    saida = {
        "periodo": chave, "label": label,
        "gerado_em": datetime.utcnow().isoformat(),
        "clipping": dados.get("clipping", []),
        "pestel": dados.get("pestel", []),
        "kpis": dados.get("kpis", []),
        "longitudinal": [
            {
                "id": s["id"], "tipo": s["tipo"], "titulo": s["titulo"],
                "dimensao": s["dimensao"], "setores": s["setores"],
                "status": s["status"], "relevancia": s["relevancia_atual"],
            } for s in top.data
        ],
    }
    os.makedirs("data", exist_ok=True)
    with open(f"data/{chave}.json", "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)
    with open("data/ultimo.json", "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
