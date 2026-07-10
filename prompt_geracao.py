"""
PROMPT DE GERAÇÃO — Clipping de Mercado
Este é o "cérebro" do sistema: a instrução que orienta o Gemini a produzir
o clipping semanal completo, no formato JSON exato que o portal espera.
"""

# Fontes validadas por setor — o Gemini prioriza busca nelas (grounding).
FONTES = """
## Macro / transversais
IBGE (ibge.gov.br), Banco Central/Focus (bcb.gov.br), FGV/IBRE (portalibre.fgv.br),
IPEA (ipeadata.gov.br), MDIC/Comex Stat (gov.br/mdic), Receita Federal (gov.br/receitafederal),
CADE (gov.br/cade), Sebrae (sebrae.com.br), Agência Senado (www12.senado.leg.br),
Agência Câmara (camara.leg.br), Serasa Experian (serasaexperian.com.br),
Valor Econômico (valor.globo.com), Exame (exame.com), InfoMoney (infomoney.com.br)

## Indústria
CNI / Portal da Indústria (portaldaindustria.com.br), FIESP (fiesp.com.br),
ABDI (gov.br/abdi), ANFAVEA (anfavea.com.br), ABIMAQ (abimaq.org.br)

## Comércio
CNC (portaldocomercio.org.br), Fecomércio (fecomercio.com.br), CNDL/SPC (cndl.org.br),
NielsenIQ (nielseniq.com), ABRAS / SuperHiper (abras.com.br), Fenabrave (fenabrave.org.br)

## Serviços
Febraban (febraban.org.br), ANEEL (gov.br/aneel), ANATEL (gov.br/anatel),
ABES Software (abessoftware.com.br), EPBR energia (epbr.com.br), MIT Tech Review BR (mittechreview.com.br)

## Agro
CNA Brasil (cnabrasil.org.br), CEPEA/Esalq (cepea.org.br), Conab (conab.gov.br),
Embrapa (embrapa.br), MAPA (gov.br/agricultura), IMEA (imea.com.br),
Notícias Agrícolas (noticiasagricolas.com.br), Canal Rural (canalrural.com.br),
ABIEC / carne (abiec.com.br), ABPA / aves e suínos (abpa-br.org), ABIOVE / soja (abiove.org.br), UNICA (unica.com.br)

## Construção civil
CBIC (cbic.org.br), SindusCon-SP (sindusconsp.com.br), ABRAINC (abrainc.org.br),
Secovi-SP (secovi.com.br), ABRAMAT / materiais (abramat.org.br), SNIC / cimento (snic.org.br),
SINAPI / Caixa (caixa.gov.br), FGV — INCC (portalibre.fgv.br), ANAMACO (anamaco.com.br)

## E-commerce
ABComm (abcomm.org), Neotrust (neotrust.com.br), MCC-ENET (mccenet.com.br),
NIQ / Webshoppers (nielseniq.com), Conversion (conversion.com.br), E-commerce Brasil (ecommercebrasil.com.br),
Nuvemshop (nuvemshop.com.br), VTEX (vtex.com), Mercado Livre (mercadolivre.com.br),
Shopee (shopee.com.br), Amazon Brasil (amazon.com.br), Magalu (magazineluiza.com.br), Reclame Aqui (reclameaqui.com.br)
""".strip()


def montar_prompt(periodo_label, data_inicio, data_fim, historico_sinais):
    """
    periodo_label: ex "Semana 27 · Julho 2026"
    data_inicio, data_fim: intervalo da semana
    historico_sinais: lista de sinais ativos vindos do Supabase (para a revisão longitudinal)
    """

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
que atende PMEs dos setores de INDÚSTRIA, COMÉRCIO, SERVIÇOS, AGRO, CONSTRUÇÃO CIVIL e E-COMMERCE.

# TAREFA
Pesquise nas fontes abaixo as notícias e dados econômicos relevantes do período
{periodo_label} ({data_inicio} a {data_fim}) e produza uma análise estruturada,
cobrindo os SEIS setores de forma equilibrada.

# COBERTURA OBRIGATÓRIA DAS FONTES
- Faça MÚLTIPLAS buscas (entre 16 e 28) para varrer as fontes de TODOS os seis setores,
  não apenas as macro/óbvias. Agro, construção civil e e-commerce têm fontes próprias — use-as.
- Toda fonte que tiver publicado material relevante no período DEVE aparecer em ao menos um item do clipping.
- Garanta que CADA UM dos seis setores tenha ao menos 1–2 itens, se houve notícia relevante no período.
- AGRUPE notícias complementares sobre o mesmo tema em UM item; nesse caso, TODAS as fontes
  do agrupamento entram no array "fontes" do item, cada uma com seu próprio url.
- Notícias independentes viram itens separados. Meta: entre 14 e 24 itens de clipping.

# FONTES PRIORITÁRIAS (por setor)
{FONTES}

# SETORES (marque cada item com um ou mais)
- "industria", "comercio", "servicos", "agro", "construcao", "ecommerce"
- "transversal" = afeta todos os setores (ex: SELIC, câmbio, reforma tributária)
- Distribua a cobertura pelos seis setores. Agro (safra, exportações, câmbio, Plano Safra),
  construção civil (INCC, crédito imobiliário, lançamentos, sondagens CBIC/CNI) e e-commerce
  (faturamento, marketplaces, cross-border/Remessa Conforme, logística) são tão relevantes quanto os demais.

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
    {{"setores": ["industria"], "titulo": "...", "texto": "...",
      "fontes": [
        {{"nome": "IBGE / PIM", "url": "https://agenciadenoticias.ibge.gov.br/..."}},
        {{"nome": "CNI", "url": "https://noticias.portaldaindustria.com.br/..."}}
      ]}}
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
    {{"label": "SELIC", "valor": "14,25%", "cor": "neutral", "sub": "detalhe/contexto aqui"}}
  ],
  "porter": {{
    "industria":  {{"rivalidade": 7, "entrantes": 4, "fornecedores": 8, "compradores": 6, "substitutos": 5, "nota": "..."}},
    "comercio":   {{"rivalidade": 8, "entrantes": 7, "fornecedores": 5, "compradores": 8, "substitutos": 7, "nota": "..."}},
    "servicos":   {{"rivalidade": 7, "entrantes": 6, "fornecedores": 5, "compradores": 6, "substitutos": 6, "nota": "..."}},
    "agro":       {{"rivalidade": 6, "entrantes": 3, "fornecedores": 7, "compradores": 7, "substitutos": 3, "nota": "..."}},
    "construcao": {{"rivalidade": 6, "entrantes": 5, "fornecedores": 7, "compradores": 6, "substitutos": 3, "nota": "..."}},
    "ecommerce":  {{"rivalidade": 9, "entrantes": 8, "fornecedores": 6, "compradores": 9, "substitutos": 7, "nota": "..."}}
  }},
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

# REGRAS DE URL (CRÍTICAS — VIOLAÇÃO INVALIDA O ITEM)
- Todo url deve apontar para a matéria/release REAL no domínio OFICIAL da fonte
  (os domínios estão listados junto às fontes acima).
- Se não tiver o link exato da matéria, use a página oficial de notícias/imprensa daquela fonte.
- NUNCA use como url: github.io, vercel.app, netlify, páginas do próprio portal de clipping,
  links de redirecionamento de busca, ou resultados de pesquisa do Google.

# REGRAS GERAIS
- SÍNTESE OBRIGATÓRIA em TODOS os campos de texto — o painel mostra highlights curtos, ninguém lê parágrafos:
  * clipping "texto": MÁXIMO 35 palavras (1 a 2 frases factuais, com número/data).
  * pestel "texto": MÁXIMO 30 palavras (o essencial da força na semana).
  * novos_sinais "texto" e atualizacoes_sinais "texto_observacao": MÁXIMO 30 palavras.
  * porter "nota": UMA frase curta.
  Corte adjetivos e rodeios. Cada frase carrega informação; nada de generalidades.
- clipping: 14 a 24 itens, cobrindo os SEIS setores + transversal. Agrupamentos com todas as fontes no array.
- pestel: sempre as 6 dimensões. score de 0 a 10 = intensidade/relevância da dimensão na semana.
  Nos "setores" de cada dimensão, use qualquer combinação dos seis setores + "transversal".
- porter: avaliação ESTRUTURAL das 5 forças competitivas (0 a 10) para os SEIS setores.
  É uma leitura de estrutura de mercado que muda DEVAGAR — seja consistente entre semanas, ajustando
  só quando houver mudança estrutural real (novo entrante relevante, consolidação, choque regulatório).
  "nota" = uma frase explicando a força dominante do setor. Valores 0 (força fraca) a 10 (força intensa).
- kpis: exatamente 7 indicadores, nesta ordem:
  1. SELIC  2. IPCA ou IPCA-15 (o mais recente)  3. Câmbio (dólar)  4. Desemprego (PNAD)
  5. Varejo (PMC/IBGE)  6. Produção Industrial (PIM-PF/IBGE)  7. IPP (Índice de Preços ao Produtor/IBGE)
  * "label" CURTO (máximo 22 caracteres, ex: "SELIC", "IPCA-15", "Câmbio", "PIM (Indústria)", "IPP").
  * Detalhes, datas e contexto vão em "sub", nunca no label. cor = "up"/"down"/"neutral"
    ("up" = leitura positiva para a economia, "down" = negativa, "neutral" = estável/ambígua).
- novos_sinais: riscos/oportunidades identificados AGORA que não estão no histórico. severidade e iminencia de 0 a 10.
- atualizacoes_sinais: para cada sinal do histórico que teve desdobramento OU reapareceu. Use o ID exato.
- Seja factual e específico (números, datas, fontes). Nada de generalidades vagas.
- Texto em português do Brasil, tom analítico e objetivo.
"""


# Teste rápido de montagem (não chama a API)
if __name__ == "__main__":
    exemplo_hist = [
        {"id": "abc-123", "tipo": "risco", "dimensao": "E", "setores": ["industria", "transversal"],
         "titulo": "Câmbio alto", "status": "em_curso",
         "relevancia_atual": 68.0, "ultimo_periodo": "2026-W26"}
    ]
    p = montar_prompt("Semana 28 · Julho 2026", "2026-07-06", "2026-07-10", exemplo_hist)
    assert "16 e 28" in p and "14 a 24 itens" in p and "IPP" in p and "PIM" in p
    assert "NUNCA use como url" in p and "github.io" in p
    assert "agro" in p and "construcao" in p and "ecommerce" in p and '"porter"' in p
    print(f"Prompt montado: {len(p)} caracteres — 6 setores, porter, cobertura, URL e KPIs presentes")
