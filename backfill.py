"""
BACKFILL — abastece a base com semanas passadas (executar UMA vez).

Reutiliza o motor.py inteiro (mesma fórmula, mesma blindagem, mesma lógica de ciclo),
apenas rodando-o para períodos anteriores, na ordem cronológica correta
(da semana mais antiga para a mais recente) para as trajetórias se formarem certas.

MODOS (variável MODO abaixo):
  "indicadores" → só KPIs macro reais de cada semana (RECOMENDADO: base íntegra, factual)
  "completo"    → clipping + sinais + KPIs de cada semana (histórico rico, parte reconstruída)

Uso no GitHub Actions: dispare o workflow de backfill (instruções no README abaixo),
ou rode localmente com as 3 variáveis de ambiente (GEMINI_API_KEY, SUPABASE_URL, SUPABASE_KEY).
"""
import os
import json
from datetime import date, timedelta

# importa TODO o motor — garante coerência (fórmula, URLs, ciclo, editorial)
import motor
from motor import (
    genai, types, create_client, extrair_json, processar,
    gerar_dados_portal, gerar_editorial, MODELO, GEMINI_KEY,
    SUPABASE_URL, SUPABASE_KEY,
)
from prompt_geracao import montar_prompt

# ═══════════════════ CONFIGURAÇÃO ═══════════════════
SEMANAS_ATRAS = 5          # quantas semanas passadas abastecer
# Default = "completo". Trata ausência E string vazia (input não renderizado no Actions).
_modo_env = (os.environ.get("BACKFILL_MODO") or "").strip().lower()
MODO = _modo_env if _modo_env in ("completo", "indicadores") else "completo"
MESES = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
         "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]


def periodo_de(semanas_atras):
    """Rótulos ISO de uma semana N semanas atrás (segunda a sexta daquela semana)."""
    hoje = date.today()
    inicio_semana_atual = hoje - timedelta(days=hoje.weekday())
    inicio = inicio_semana_atual - timedelta(weeks=semanas_atras)
    fim = inicio + timedelta(days=4)
    ano, semana, _ = inicio.isocalendar()
    label = f"Semana {semana} · {MESES[inicio.month]} {ano}"
    chave = f"{ano}-W{semana:02d}"
    return chave, label, inicio.isoformat(), fim.isoformat()


# ─────────────────────────────────────────────────────────
# PROMPT "SÓ INDICADORES" — recupera apenas KPIs macro reais (factual)
# ─────────────────────────────────────────────────────────
def prompt_indicadores(label, ini, fim):
    return f"""Você é um analista econômico. Recupere os INDICADORES MACROECONÔMICOS OFICIAIS
do Brasil vigentes na semana {label} ({ini} a {fim}). Use fontes oficiais (IBGE, Banco Central).
Estes são fatos históricos — busque os valores REAIS que valiam naquela data específica.

Responda SOMENTE com JSON válido, sem markdown:
{{
  "kpis": [
    {{"label": "SELIC", "valor": "...", "cor": "neutral", "sub": "vigente na semana"}},
    {{"label": "IPCA-15", "valor": "...", "cor": "up", "sub": "..."}},
    {{"label": "Câmbio", "valor": "...", "cor": "down", "sub": "..."}},
    {{"label": "Desemprego", "valor": "...", "cor": "up", "sub": "PNAD"}},
    {{"label": "Varejo (PMC)", "valor": "...", "cor": "up", "sub": "..."}},
    {{"label": "PIM (Indústria)", "valor": "...", "cor": "down", "sub": "..."}},
    {{"label": "IPP", "valor": "...", "cor": "neutral", "sub": "..."}}
  ]
}}
Regras: valores reais da época; label curto (máx 22 caracteres); cor = up/down/neutral."""


def rodar_indicadores(sb, chave, label, ini, fim):
    """Gera só os KPIs reais da semana e grava o JSON do portal (sem sinais fabricados)."""
    client = genai.Client(api_key=GEMINI_KEY)
    grounding = types.Tool(google_search=types.GoogleSearch())
    resp = client.models.generate_content(
        model=MODELO, contents=prompt_indicadores(label, ini, fim),
        config=types.GenerateContentConfig(tools=[grounding], temperature=0.2),
    )
    dados = extrair_json(resp.text)
    # grava o JSON do portal só com KPIs (clipping/pestel/long vazios; editorial None)
    gerar_dados_portal(
        {"clipping": [], "pestel": [], "kpis": dados.get("kpis", [])},
        sb, chave, label, editorial=None,
    )
    return len(dados.get("kpis", []))



def prompt_completo_retroativo(label, ini, fim, ativos):
    """Prompt de backfill que INSTRUI a busca retroativa de notícias antigas —
    a limitação que faz o clipping vir vazio quando se pede notícia de semanas atrás."""
    from prompt_geracao import montar_prompt
    base = montar_prompt(label, ini, fim, ativos)
    reforco = f"""

# ATENÇÃO — BUSCA RETROATIVA (HISTÓRICO)
Esta é uma reconstrução de uma semana PASSADA ({ini} a {fim}). Notícias antigas exigem
estratégia de busca específica, senão o clipping volta vazio. Faça o seguinte:
- Inclua a DATA nas buscas: adicione "{ini[:7]}" (ano-mês), "maio 2026", "junho 2026" conforme o período.
- Busque por RELEASES e BOLETINS que têm data fixa: "IBGE {ini[:7]}", "IPCA {ini[:7]}",
  "Boletim Focus {ini[:7]}", "CNI sondagem {ini[:7]}", "Copom {ini[:7]}".
- Se não encontrar a matéria EXATA da semana, use a divulgação oficial MAIS PRÓXIMA daquele período
  (ex.: o indicador econômico daquele mês, o comunicado do Copom daquela data).
- É MELHOR trazer 6-10 itens reais e datados do período do que retornar clipping vazio.
- Cada item DEVE ter ao menos uma fonte com URL oficial. NUNCA retorne clipping vazio se houver
  qualquer divulgação econômica relevante naquele mês — e sempre há (IBGE, BCB publicam mensalmente).
"""
    return base + reforco


def prompt_clipping_minimo(label, ini, fim):
    """2ª tentativa: pede SÓ o clipping, focado nas divulgações econômicas oficiais do mês."""
    mes_ano = ini[:7]
    return f"""Liste as principais divulgações econômicas oficiais do Brasil no período {ini} a {fim}
(mês de referência {mes_ano}). Foque no que órgãos oficiais publicaram: IBGE (IPCA, PIM, PMC, PNAD, IPP),
Banco Central (Copom, Focus, crédito), CNI (sondagem industrial), FGV (confiança).

Responda SOMENTE com JSON válido, sem markdown:
{{
  "clipping": [
    {{"setores": ["transversal"], "titulo": "...", "texto": "...",
      "fontes": [{{"nome": "IBGE", "url": "https://agenciadenoticias.ibge.gov.br/..."}}]}}
  ]
}}
Traga entre 6 e 10 divulgações reais daquele mês. Cada uma com fonte oficial e URL.
Se não tiver a URL exata, use a página oficial de notícias do órgão. Nunca retorne lista vazia."""

def rodar_completo(sb, chave, label, ini, fim):
    """Roda o ciclo completo do motor para a semana passada (clipping + sinais + KPIs).
    Marca os sinais como origem='backfill', corrige a data de identificação para a
    semana histórica e NEUTRALIZA a inflação de relevância (pico/persistência):
    a contagem em tempo real recomeça na primeira execução real (W atual)."""
    # snapshot dos IDs que já existiam ANTES desta semana de backfill
    antes = sb.table("sinais").select("id").execute().data
    ids_antes = {r["id"] for r in antes}

    ativos = sb.table("sinais").select("*").neq("status", "dormindo").execute().data
    prompt = prompt_completo_retroativo(label, ini, fim, ativos)
    texto = motor.gerar_analise(prompt)
    dados = extrair_json(texto)

    # FALLBACK: se o clipping veio vazio (limite da busca retroativa), tenta 1 vez
    # com um pedido focado só em divulgações econômicas oficiais daquele mês.
    if not dados.get("clipping"):
        print(f"[backfill] {chave}: clipping vazio, tentando recuperação focada...")
        try:
            reforco = prompt_clipping_minimo(label, ini, fim)
            t2 = motor.gerar_analise(reforco)
            d2 = extrair_json(t2)
            if d2.get("clipping"):
                dados["clipping"] = d2["clipping"]
                print(f"[backfill] {chave}: recuperados {len(d2['clipping'])} itens na 2ª tentativa.")
        except Exception as e:
            print(f"[backfill] {chave}: recuperação de clipping falhou (segue): {e}")

    processar(dados, sb, chave, ativos)

    # identifica os sinais NOVOS criados nesta semana de backfill
    depois = sb.table("sinais").select("id,relevancia_atual").execute().data
    novos_ids = [r["id"] for r in depois if r["id"] not in ids_antes]

    # marca origem + corrige data histórica + congela pico=relevância atual
    # + zera persistência inflada (recomeça em 1) para não sequestrar o ranking real
    for sid in novos_ids:
        try:
            atual = next((r for r in depois if r["id"] == sid), None)
            rel = atual["relevancia_atual"] if atual else 0
            sb.table("sinais").update({
                "origem": "backfill",
                "data_identificacao": ini,          # data histórica real, não hoje
                "relevancia_pico": rel,             # pico = valor de agora (sem inflar)
                "persistencia": 1,                  # contagem real recomeça no vivo
                "ultimo_ciclo_contado": chave,
            }).eq("id", sid).execute()
        except Exception as e:
            print(f"[backfill] aviso: não marquei {sid}: {e}")

    editorial = gerar_editorial(sb, chave, label, dados)
    gerar_dados_portal(dados, sb, chave, label, editorial)
    return len(dados.get("clipping", [])), len(dados.get("novos_sinais", []))


def main():
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    print(f"[backfill] MODO = {MODO} | {SEMANAS_ATRAS} semanas | ordem cronológica (mais antiga primeiro)")

    # ordem CRONOLÓGICA: da mais antiga (5 atrás) para a mais recente (1 atrás)
    # — assim persistência/pico/trajetória se formam na sequência temporal certa.
    ok, falhas = 0, 0
    for n in range(SEMANAS_ATRAS, 0, -1):
        chave, label, ini, fim = periodo_de(n)
        try:
            if MODO == "indicadores":
                nk = rodar_indicadores(sb, chave, label, ini, fim)
                print(f"[backfill] ✓ {chave} ({label}) — {nk} indicadores reais")
            elif MODO == "completo":
                nc, ns = rodar_completo(sb, chave, label, ini, fim)
                print(f"[backfill] ✓ {chave} ({label}) — {nc} notícias, {ns} novos sinais")
            else:
                print(f"[backfill] MODO desconhecido '{MODO}' — use 'indicadores' ou 'completo'")
                return
            ok += 1
        except Exception as e:
            falhas += 1
            print(f"[backfill] ✗ {chave} falhou (segue para a próxima): {e}")

    print(f"[backfill] Concluído: {ok} semanas abastecidas, {falhas} falhas.")
    if MODO == "indicadores":
        print("[backfill] Base íntegra: indicadores reais no histórico; "
              "sinais qualitativos passam a acumular de verdade a partir de agora.")


if __name__ == "__main__":
    main()
