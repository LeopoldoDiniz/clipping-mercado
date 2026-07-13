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
Valor Econômico (valor.globo.com), Exame (exame.com), InfoMoney (infomoney.com.br),
Estadão/Broadcast (estadao.com.br), Folha - Mercado (folha.uol.com.br), O Globo - Economia (oglobo.globo.com),
Brazil Journal (braziljournal.com), NeoFeed (neofeed.com.br), Money Times (moneytimes.com.br),
CNN Brasil - Macroeconomia (cnnbrasil.com.br), Poder360 (poder360.com.br), Agência Brasil/EBC (agenciabrasil.ebc.com.br),
Tesouro Nacional (gov.br/tesouronacional) ⭐fiscal, Ministério da Fazenda (gov.br/fazenda) ⭐política,
CNC/Pesquisas - PEIC/ICF (pesquisascnc.com.br) ⭐sondagem

## Indústria
CNI / Portal da Indústria (portaldaindustria.com.br), FIESP (fiesp.com.br),
ABDI (gov.br/abdi), ANFAVEA (anfavea.com.br), ABIMAQ (abimaq.org.br),
S&P Global/PMI Brasil (pmi.spglobal.com) ⭐antecedente, Instituto Aço Brasil (acobrasil.org.br) ⭐,
ABIQUIM (abiquim.org.br) ⭐, ABINEE (abinee.org.br) ⭐, ABIT (abit.org.br) ⭐, IEDI (iedi.org.br) ⭐,
FIRJAN (firjan.com.br) ⭐, FIEMG (fiemg.com.br) ⭐, Sindipeças (sindipecas.org.br) ⭐, Abraciclo (abraciclo.com.br) ⭐,
AutoData (autodata.com.br), Automotive Business (automotivebusiness.com.br)

## Comércio
CNC (portaldocomercio.org.br), Fecomércio (fecomercio.com.br), CNDL/SPC (cndl.org.br),
NielsenIQ (nielseniq.com), ABRAS / SuperHiper (abras.com.br), Fenabrave (fenabrave.org.br),
Índice Cielo/ICVA (blog.cielo.com.br) ⭐transacional, Equifax/BoaVista (equifax.com.br) ⭐, SBVC (sbvc.com.br) ⭐,
IBEVAR (ibevar.org.br) ⭐, ABF/franchising (abf.com.br) ⭐, Abrasce/shoppings (abrasce.com.br) ⭐,
ABAD/atacado (abad.com.br) ⭐, APAS/supermercados (apas.com.br) ⭐, IDV (idv.org.br),
Consumidor Moderno (consumidormoderno.com.br), Diário do Comércio/ACSP (dcomercio.com.br),
Novo Varejo (novovarejo.com.br), SuperVarejo (supervarejo.com.br), InfoVarejo (infovarejo.com.br)

## Serviços
Febraban (febraban.org.br), ANEEL (gov.br/aneel), ANATEL (gov.br/anatel),
ABES Software (abessoftware.com.br), EPBR energia (epbr.com.br), MIT Tech Review BR (mittechreview.com.br),
ANBIMA (anbima.com.br) ⭐, CNseg/seguros (cnseg.org.br) ⭐, SUSEP (gov.br/susep) ⭐, ABECS/pagamentos (abecs.org.br) ⭐,
Conexis/telecom (conexis.org.br) ⭐, CCEE/energia (ccee.org.br) ⭐, Brasscom/TIC (brasscom.org.br) ⭐,
TELETIME (teletime.com.br), Tele.Síntese (telesintese.com.br), Convergência Digital (convergenciadigital.com.br),
CanalEnergia (canalenergia.com.br), Mobile Time (mobiletime.com.br)

## Agro
CNA Brasil (cnabrasil.org.br), CEPEA/Esalq (cepea.org.br) ⭐preço, Conab (conab.gov.br) ⭐safra,
Embrapa (embrapa.br), MAPA (gov.br/agricultura), IMEA (imea.com.br), B3 / futuros agro (b3.com.br),
Notícias Agrícolas (noticiasagricolas.com.br), Canal Rural (canalrural.com.br), Globo Rural (globorural.globo.com),
AgFeed (agfeed.com.br), Scot Consultoria (scotconsultoria.com.br),
ABIEC / carne (abiec.com.br), ABPA / aves e suínos (abpa-br.org), ABIOVE / soja (abiove.org.br), UNICA (unica.com.br),
Agrolink (agrolink.com.br), Compre Rural (comprerural.com), The Agribiz (theagribiz.com) ⭐negócio,
Revista Cultivar (revistacultivar.com.br), BeefPoint/AgriPoint (beefpoint.com.br), Sou Agro (souagro.net),
AgriBrasilis (agribrasilis.com), Forbes Agro (forbes.com.br) ⭐, Aprosoja (aprosojabrasil.com.br) ⭐,
ABAG (abag.com.br) ⭐, Sociedade Rural Brasileira (srb.org.br), ABRAPA/algodão (abrapa.com.br) ⭐,
Sistema OCB (somoscooperativismo.coop.br), FPA (fpagropecuaria.org.br) ⭐, ANDA/fertilizantes (anda.org.br) ⭐,
Datagro (datagro.com) ⭐, Safras & Mercado (safras.com.br) ⭐, JBS (jbs.com.br)

## Construção civil
CBIC / Hub de Dados (cbic.org.br) ⭐, SindusCon-SP (sindusconsp.com.br), CUB médio (cub.org.br) ⭐R$/m²,
FGV — INCC (portalibre.fgv.br) ⭐custo, FipeZAP / imóveis (fipe.org.br) ⭐preço, SNIC / cimento (snic.org.br) ⭐atividade,
ABRAINC (abrainc.org.br), Secovi-SP (secovi.com.br), ABRAMAT / materiais (abramat.org.br),
SINAPI / Caixa (caixa.gov.br), ANAMACO (anamaco.com.br), Sienge (sienge.com.br),
ABECIP/crédito imob. (abecip.org.br) ⭐, Ministério das Cidades/MCMV (gov.br/cidades) ⭐, AECweb (aecweb.com.br),
Massa Cinzenta/Cimento Itambé (cimentoitambe.com.br), Grandes Construções (grandesconstrucoes.com.br),
O Empreiteiro (revistaoe.com.br), ABCP/cimento (abcp.org.br), CAU/BR (caubr.gov.br), CONFEA (confea.org.br),
ADEMI-RJ (ademi.org.br) ⭐, MRV/RI (mrv.com.br) ⭐prévias, Cyrela/RI (cyrela.com.br) ⭐, Votorantim Cimentos (votorantimcimentos.com.br)

## E-commerce
ABComm (abcomm.org) ⭐, Neotrust / Confi (neotrust.com.br) ⭐, MCC-ENET (mccenet.com.br) ⭐índice mensal,
NIQ / Webshoppers (nielseniq.com), Conversion (conversion.com.br), E-commerce Brasil (ecommercebrasil.com.br),
Mercado&Consumo (mercadoeconsumo.com.br), Nuvemshop (nuvemshop.com.br), VTEX (vtex.com), Mercado Livre (mercadolivre.com.br),
Shopee (shopee.com.br), Amazon Brasil (amazon.com.br), Magalu (magazineluiza.com.br), Reclame Aqui (reclameaqui.com.br),
E-Commerce News (ecommercenews.com.br), NOVAREJO (portalnovarejo.com.br), Meio&Mensagem/ProXXIma (meioemensagem.com.br),
Câmara Bras. Economia Digital (camara-e.net), Senacon/MJSP (gov.br/mj) ⭐regulatório, Procon-SP (procon.sp.gov.br) ⭐,
Grupo Casas Bahia (grupocasasbahia.com.br), SHEIN Group (sheingroup.com)

# REFERÊNCIAS DE MERCADO (decision-grade) — as ⭐ acima são as réguas que o mercado usa para decidir.
# Ancore a leitura de cada setor no número mais recente delas quando houver:
#   Agro → preços CEPEA (soja/boi/milho/café) e safra Conab;  Construção → INCC/FGV, CUB e FipeZAP;
#   E-commerce → índice MCC-ENET e dados Neotrust/ABComm.  Cite sempre a fonte e a data.
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
- Faça MÚLTIPLAS buscas (entre 30 e 48) para varrer as fontes de TODOS os seis setores,
  não apenas as macro/óbvias. Agro, construção civil e e-commerce têm fontes próprias — use-as.
- Toda fonte que tiver publicado material relevante no período DEVE aparecer em ao menos um item do clipping.
- Garanta que CADA UM dos seis setores tenha de 15 a 20 itens, se houve notícia relevante no período
  (piso de 15 por setor com cobertura; use as fontes especializadas/diárias para dar volume real, sem encher linguiça).
- AGRUPE notícias complementares sobre o mesmo tema em UM item; nesse caso, TODAS as fontes
  do agrupamento entram no array "fontes" do item, cada uma com seu próprio url.
- Notícias independentes viram itens separados. Meta por setor: 15 a 20 itens de clipping (90 a 120 no total).

# FONTES PRIORITÁRIAS (por setor)
{FONTES}

# SETORES (marque cada item com um ou mais) — vale para CLIPPING, PESTEL e SINAIS (longitudinal), não só clipping
- "industria", "comercio", "servicos", "agro", "construcao", "ecommerce"
- "transversal" = afeta todos os setores (ex: SELIC, câmbio, reforma tributária)
- REGRA: se o item é ESPECÍFICO de um setor, ele DEVE conter a tag daquele setor (não deixe só "transversal"):
  * obras/imóveis/INCC/SINAPI/CUB/FipeZAP/lançamentos/construtoras/VGV → "construcao"
  * safra/grãos/soja/milho/boi/CEPEA/Conab/LSPA/agronegócio/fertilizantes → "agro"
  * marketplace/faturamento online/cross-border/Remessa Conforme/last mile/checkout → "ecommerce"
- No PESTEL, cada dimensão deve listar TODOS os setores afetados: use "transversal" para forças macro
  E ACRESCENTE os setores mais impactados (inclua construcao/agro/ecommerce quando a força os atinge —
  ex.: juros altos → transversal + construcao; câmbio → transversal + agro + ecommerce).
- Distribua a cobertura pelos seis setores. Agro (safra, exportações, câmbio, Plano Safra),
  construção civil (INCC, crédito imobiliário, lançamentos, sondagens CBIC/CNI) e e-commerce
  (faturamento, marketplaces, cross-border/Remessa Conforme, logística) são tão relevantes quanto os demais.
  E-commerce NÃO pode ficar sem clipping: busque nas fontes próprias do setor a cada rodada.
- SINAIS (novos_sinais/longitudinal): além de riscos macro, promova a SINAL rastreável os desdobramentos
  REGULATÓRIOS (ANEEL, leilões, Remessa Conforme, reforma tributária, marcos legais) e TRABALHISTAS
  (escala 6x1, jornada, encargos) quando materiais — não os deixe só como notícia solta.

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
  "indicador_ecommerce": {{"valor": "+12,4%", "referencia": "maio/2026", "fonte": "MCC-ENET",
      "sub": "Vendas do e-commerce · variação sobre igual mês do ano anterior"}},
  "porter": {{
    "industria":  {{"rivalidade": 7, "entrantes": 4, "fornecedores": 8, "compradores": 6, "substitutos": 5, "nota": "..."}},
    "comercio":   {{"rivalidade": 8, "entrantes": 7, "fornecedores": 5, "compradores": 8, "substitutos": 7, "nota": "..."}},
    "servicos":   {{"rivalidade": 7, "entrantes": 6, "fornecedores": 5, "compradores": 6, "substitutos": 6, "nota": "..."}},
    "agro":       {{"rivalidade": 6, "entrantes": 3, "fornecedores": 7, "compradores": 7, "substitutos": 3, "nota": "..."}},
    "construcao": {{"rivalidade": 6, "entrantes": 5, "fornecedores": 7, "compradores": 6, "substitutos": 3, "nota": "..."}},
    "ecommerce":  {{"rivalidade": 9, "entrantes": 8, "fornecedores": 6, "compradores": 9, "substitutos": 7, "nota": "..."}}
  }},
  "analise": {{
    "panorama": {{"acoes": [{{"ico": "💸", "txt": "ação macro/transversal prática da semana, ancorada nos dados (número/evento real)"}}]}},
    "setores": {{
      "industria":  {{"prov": "pergunta provocativa da semana no setor", "quote": "leitura em 1 frase com número/fato real", "edi": ["parágrafo curto factual", "parágrafo curto factual"], "acoes": [{{"ico": "⚡", "txt": "ação prática decorrente dos dados"}}]}},
      "comercio":   {{"prov": "...", "quote": "...", "edi": ["..."], "acoes": [{{"ico": "🛒", "txt": "..."}}]}},
      "servicos":   {{"prov": "...", "quote": "...", "edi": ["..."], "acoes": [{{"ico": "🤖", "txt": "..."}}]}},
      "agro":       {{"prov": "...", "quote": "...", "edi": ["..."], "acoes": [{{"ico": "🌾", "txt": "..."}}]}},
      "construcao": {{"prov": "...", "quote": "...", "edi": ["..."], "acoes": [{{"ico": "🏗️", "txt": "..."}}]}},
      "ecommerce":  {{"prov": "...", "quote": "...", "edi": ["..."], "acoes": [{{"ico": "📦", "txt": "..."}}]}}
    }}
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

# INDICADOR DE E-COMMERCE (fonte de MERCADO — não há série oficial gratuita)
- Preencha "indicador_ecommerce" APENAS se uma fonte de mercado (MCC-ENET, ABComm, Neotrust,
  NIQ/Webshoppers) divulgou no período um número mensal de vendas/faturamento do e-commerce.
- "valor" = a variação divulgada (ex.: "+12,4%"); "fonte" = quem divulgou; "referencia" = mês do dado.
- Se NENHUMA fonte de mercado publicou número no período, use "indicador_ecommerce": null. NUNCA estime/invente.

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
- clipping: 15 a 20 itens POR SETOR (Indústria, Comércio, Serviços, Agro, Construção, E-commerce) + transversais,
  totalizando ~90 a 120 itens. Agrupamentos com todas as fontes no array.
- pestel: sempre as 6 dimensões. score de 0 a 10 = intensidade/relevância da dimensão na semana.
  Nos "setores" de cada dimensão, use qualquer combinação dos seis setores + "transversal".
- porter: avaliação ESTRUTURAL das 5 forças competitivas (0 a 10) para os SEIS setores.
  É uma leitura de estrutura de mercado que muda DEVAGAR — seja consistente entre semanas, ajustando
  só quando houver mudança estrutural real (novo entrante relevante, consolidação, choque regulatório).
  "nota" = uma frase explicando a força dominante do setor. Valores 0 (força fraca) a 10 (força intensa).
- analise: leitura ACIONÁVEL da semana, por setor, DERIVADA das notícias/sinais/indicadores desta semana.
  Para cada um dos SEIS setores: "prov" (pergunta provocativa curta), "quote" (1 frase com número/fato real),
  "edi" (1 a 2 parágrafos curtos e factuais, citando eventos/números reais desta semana),
  "acoes" (3-4 ações práticas, cada uma {{"ico": emoji, "txt": frase curta}}). "panorama.acoes" = 4-5 ações
  macro/transversais. Ancore TUDO nos dados desta semana — nunca invente fato que não apareça no clipping/sinais.
- kpis: exatamente 7 indicadores, nesta ordem:
  1. SELIC  2. IPCA ou IPCA-15 (o mais recente)  3. Câmbio (dólar)  4. Desemprego (PNAD)
  5. Varejo (PMC/IBGE)  6. Produção Industrial (PIM-PF/IBGE)  7. IPP (Índice de Preços ao Produtor/IBGE)
  * "label" CURTO (máximo 22 caracteres, ex: "SELIC", "IPCA-15", "Câmbio", "PIM (Indústria)", "IPP").
  * Detalhes, datas e contexto vão em "sub", nunca no label. cor = "up"/"down"/"neutral"
    ("up" = leitura positiva para a economia, "down" = negativa, "neutral" = estável/ambígua).
  * O "sub" do IPCA DEVE seguir este formato exato, com os campos parseáveis pelo painel:
    "Mês · acum. ano X,XX% · 12m Y,YY% · meta M,M% (teto T,T%) · IBGE mmm/aa · Projeção Focus AAAA: Z,ZZ%"
    - "acum. ano" = IPCA acumulado no ano corrente (jan→mês de referência), dado REAL do IBGE.
    - "meta M,M% (teto T,T%)" = meta de inflação VIGENTE definida pelo CMN (Conselho Monetário
      Nacional) e perseguida pelo BCB. NÃO fixe números de memória: consulte a fonte oficial
      (bcb.gov.br/controleinflacao/metainflacao). No regime de meta contínua (desde 2025) o centro é
      3,0% e a tolerância ±1,5 p.p. (teto 4,5%) — mas SEMPRE confirme o valor vigente na fonte, pois
      o CMN pode redefinir a meta e o teto.
    - "Projeção Focus AAAA" = mediana do Boletim Focus/BCB para o IPCA de fechamento do ano vigente
      (número REAL do Focus mais recente; nunca invente). Use o ano corrente em AAAA.
  * SELIC e Câmbio também trazem "Projeção Focus AAAA: ..." no fim do "sub" (mediana Focus para o ano vigente).
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
    assert "30 e 48" in p and "15 a 20 itens" in p and "IPP" in p and "PIM" in p
    assert "NUNCA use como url" in p and "github.io" in p
    assert "agro" in p and "construcao" in p and "ecommerce" in p and '"porter"' in p
    print(f"Prompt montado: {len(p)} caracteres — 6 setores, porter, cobertura, URL e KPIs presentes")
