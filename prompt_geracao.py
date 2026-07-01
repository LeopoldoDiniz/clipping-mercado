"""
PROMPT DE GERAÇÃO — Clipping de Mercado
Este é o "cérebro" do sistema: a instrução que orienta o Gemini a produzir
o clipping semanal completo, no formato JSON exato que o portal espera.
"""

# As 28 fontes validadas — o Gemini prioriza busca nelas
FONTES = """
IBGE (ibge.gov.br), Banco Central/Focus (bcb.gov.br), FGV/IBRE (portalibre.fgv.br),
IPEA (ipeadata.gov.br), CNI (portaldaindustria.com.br), MDIC (gov.br/mdic),
ANP (gov.br/anp), FIESP (fiesp.com.br), CNC (portaldocomercio.org.br),
Fecomércio MG (fecomercio-mg.org.br), CNDL/SPC (cndl.org.br), NielsenIQ,
Sebrae (sebrae.com.br), Agência Sebrae, Febraban (febraban.org.br),
Agência Senado (senado.leg.br), Agência Câmara (camara.leg.br),
Receita Federal (gov.br/receitafederal), CADE (cade.gov.br),
MIT Technology Review Brasil, ANEEL (gov.br/aneel), MMA (gov.br/mma),
B3 Sustentabilidade (b3.com.br), Valor Econômico (valor.globo.com),
Exame (exame.com), InfoMoney (infomoney.com.br), EPBR (epbr.com.br)
""".strip()


def montar_prompt(periodo_label, data_inicio, data_fim, historico_sinais):
    """
    periodo_label: ex "Semana 27 · Julho 2026"
    data_inicio, data_fim: intervalo da semana
    historico_sinais: lista de sinais ativos vindos do Supabase (para a revisão longitudinal)
    """

    # Formata o histórico de sinais para o Gemini avaliar a evolução
    if historico_sinais:
        hist_texto = "\n".join([
            f"- [{s['id']}] ({s['tipo']}, dim {s['dimensao']}, setores {s['setores']}) "
            f"\"{s['titulo']}\" | status atual: {s['status']} | "
            f"relevância: {s['relevancia_atual']} | visto pela última vez em: {s['ultimo_periodo']}"
            for s in historico_sinais
        ])
    else:
        hist_texto = "(Nenhum sinal anterior — esta é uma das primeiras execuções.)"

    return f"""Você é um analista sênior de inteligência de mercado da Formatar Consultoria,
em Divinópolis/MG, produzindo o clipping estratégico da semana para uma consultoria
que atende PMEs dos setores de INDÚSTRIA, COMÉRCIO e SERVIÇOS.

# TAREFA
Pesquise nas fontes confiáveis abaixo as notícias e dados econômicos mais relevantes
do período {periodo_label} ({data_inicio} a {data_fim}) e produza uma análise estruturada.
Faça MÚLTIPLAS buscas para cobrir bem cada setor e cada dimensão PESTEL, cruzando fontes
independentes para confirmar cada sinal (isso alimenta a "corroboração").

# FONTES PRIORITÁRIAS
{FONTES}

# SETORES (marque cada item com um ou mais)
- "industria", "comercio", "servicos"
- "transversal" = afeta todos os setores (ex: SELIC, câmbio, reforma tributária)

# HISTÓRICO DE SINAIS ATIVOS (para a revisão longitudinal)
Avalie CADA sinal abaixo à luz das notícias novas desta semana. Para cada um, decida:
- Houve desdobramento? (nova observação)
- O status mudou? (monitorar → em_curso → materializado)
- Ele reapareceu nas fontes desta semana? (se sim, persistência aumenta; se não, marque visto=false)

{hist_texto}

# FORMATO DE SAÍDA
Responda SOMENTE com um objeto JSON válido, sem texto antes ou depois, sem markdown.
Estrutura exata:

{{
  "clipping": [
    {{"setores": ["industria"], "fonte": "IBGE / PIM", "titulo": "...", "texto": "...", "url": "https://..."}}
  ],
  "pestel": [
    {{"dim": "P", "nome": "Político", "tema": "...", "texto": "...", "score": 6.5, "setores": ["transversal"]}},
    {{"dim": "E", "nome": "Econômico", "tema": "...", "texto": "...", "score": 7.8, "setores": ["transversal"]}},
    {{"dim": "S", "nome": "Social", "tema": "...", "texto": "...", "score": 8.0, "setores": ["comercio","servicos"]}},
    {{"dim": "T", "nome": "Tecnológico", "tema": "...", "texto": "...", "score": 7.0, "setores": ["industria","servicos"]}},
    {{"dim": "A", "nome": "Ambiental", "tema": "...", "texto": "...", "score": 5.5, "setores": ["industria"]}},
    {{"dim": "L", "nome": "Legal", "tema": "...", "texto": "...", "score": 6.0, "setores": ["industria","servicos"]}}
  ],
  "kpis": [
    {{"label": "SELIC (Focus)", "valor": "10,5%", "cor": "neutral", "sub": "Estável"}}
  ],
  "novos_sinais": [
    {{"tipo": "risco", "titulo": "...", "dimensao": "E", "setores": ["transversal"],
      "texto": "...", "fontes": ["Valor","BCB"],
      "severidade": 8.0, "iminencia": 7.0, "materializado": false}}
  ],
  "atualizacoes_sinais": [
    {{"id": "SINAL_ID_DO_HISTORICO", "reapareceu": true, "texto_observacao": "...",
      "novo_status": "materializado", "fontes": ["IBGE"],
      "severidade": 8.0, "iminencia": 7.5, "materializado": true}}
  ]
}}

# REGRAS
- clipping: 4 a 8 itens, cobrindo os três setores. Cada um com URL real da fonte.
- pestel: sempre as 6 dimensões. score de 0 a 10 = intensidade/relevância da dimensão na semana.
- kpis: 5 indicadores macro (SELIC, IPCA, câmbio, desemprego, varejo). cor = "up"/"down"/"neutral".
- novos_sinais: riscos/oportunidades identificados AGORA que não estão no histórico. severidade e iminencia de 0 a 10.
- atualizacoes_sinais: para cada sinal do histórico que teve desdobramento OU reapareceu. Use o ID exato.
- Seja factual e específico (números, datas, fontes). Nada de generalidades vagas.
- Texto em português do Brasil, tom analítico e objetivo.
"""


# Teste rápido de montagem (não chama a API)
if __name__ == "__main__":
    exemplo_hist = [
        {"id": "SIG-001", "tipo": "risco", "dimensao": "E", "setores": ["industria", "transversal"],
         "titulo": "Pressão cambial > R$5,30", "status": "em_curso",
         "relevancia_atual": 68.0, "ultimo_periodo": "2026-W26"}
    ]
    p = montar_prompt("Semana 27 · Julho 2026", "2026-07-06", "2026-07-10", exemplo_hist)
    print(p[:1200])
    print("\n...[prompt completo montado com sucesso]...")
    print(f"\nTamanho do prompt: {len(p)} caracteres")
