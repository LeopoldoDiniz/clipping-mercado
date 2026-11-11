# Rotina diária do Nexos (execução na nuvem)

Roda todo dia às 07h (Brasília), inclusive sábado e domingo. Às segundas, além da rodada do dia,
**fecha a semana anterior** (memória de temas + editorial preditivo). Trabalhe sempre na raiz do
repositório, com `PYTHONIOENCODING=utf-8`. Não altere código (`*.py`, `index.html`): só dados.

## 0. Datas
- `HOJE=$(TZ=America/Sao_Paulo date +%F)`; semana ISO de hoje = `W_CUR` (ex.: `2026-W47`).
- `W_PREV` = semana ISO anterior. Segunda-feira = `TZ=America/Sao_Paulo date +%u` igual a 1.
- Janela de busca: o que foi publicado desde a rodada anterior (ontem 07h até agora).
  Cada notícia vai para a semana ISO da **data de publicação** (domingo pertence à semana que termina nele).

## 0.1 Checagem de acesso (antes de tudo)
Teste as fontes de que a rotina depende e guarde o resultado para o resumo:
```bash
for u in "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados/ultimos/1?formato=json" \
         "https://apisidra.ibge.gov.br/values/t/1737/n1/all/v/63/p/last%201" \
         "https://servicodados.ibge.gov.br/api/v3/calendario/?qtd=1"; do
  curl -s -o /dev/null -w "%{http_code} $u\n" --max-time 30 "$u" || echo "FALHA $u"; done
curl -s -o /dev/null -w "%{http_code} FGV\n" --max-time 30 --ciphers 'DEFAULT@SECLEVEL=1' \
  "https://portalibre.fgv.br/calendario-de-divulgacao" || echo "FALHA FGV"
```
Depois abra com **WebFetch** uma página de notícia qualquer (ex.: a primeira URL da busca do passo 1).
- Código 200 = ok. Qualquer outro código, `FALHA` ou erro do WebFetch = acesso bloqueado.
- Fonte oficial bloqueada: siga a rotina (o motor usa o último valor oficial e o calendário versionado).
- WebFetch bloqueado: siga, mas só aceite notícia cujo resultado de busca já traga data e número.
- O resumo final **abre** com a linha `Acesso: BCB ok | SIDRA ok | calendário IBGE ok | FGV ok | notícias ok`
  (troque `ok` pelo código ou erro que falhou).

## 1. Busca de notícias
- Use o modo de busca mais completo disponível (busca ampliada): o modo padrão não encontra publicações de 1–2 dias.
- Cubra os seis setores: indústria, comércio, serviços, agro, construção, e-commerce (+ transversal: Selic,
  câmbio, fiscal, inflação). Fontes prioritárias: `prompt_geracao.py` (constante `FONTES`).
- Só entra item com **data de publicação dentro da janela** e **URL vista no resultado da busca**.
  Descarte: número com ano ambíguo, item interpretativo sem fonte, repetição de notícia já em
  `trabalho/<semana>/coleta.json`.
- Texto de cada item: no máximo 35 palavras, factual, com número/data.

## 2. Incremento do dia — `trabalho/<semana>/incremento.json`
Um arquivo por semana que recebeu notícia nova (na segunda, normalmente `W_PREV` com as de domingo e
`W_CUR` com as de segunda cedo). Formato:
```json
{
  "clipping": [
    {"setores": ["industria"], "titulo": "...", "texto": "...", "palavra": "PIM",
     "fontes": [{"nome": "IBGE", "url": "https://..."}]}
  ],
  "leituras_temas": {
    "atividade": {"tipo": "risco", "status": "em_curso", "texto": "<=30 palavras, com número/data", "fontes": ["IBGE"]}
  },
  "novos_temas": []
}
```
- `setores`: industria, comercio, servicos, agro, construcao, ecommerce, transversal.
- **palavra** (obrigatória, interna, não aparece no portal): UMA palavra que resume a notícia.
  - A mais específica possível (gasolina, arroba, IPP). Proibidas: preços, mercado, setor, economia,
    vendas, Brasil, inflação, juros.
  - Nomeia o SUJEITO da notícia (quem age ou o que foi medido), não o motivo.
  - Use as palavras do `dicionario` de `temas.json` sempre que couberem. Palavra nova: acrescente
    `"tema": "<id>"` no item. Assunto sem tema que se repete: crie em `novos_temas`
    (`{"id","nome","dimensao":"P|E|S|T|A|L","tipo":"risco|oportunidade"}`). Você decide; não precisa de aprovação.
- **leituras_temas**: para cada tema que teve notícia relevante, a leitura da semana até agora
  (`tipo` risco/oportunidade; `status` monitorar/em_curso/materializado; `materializado` = o risco ou
  a oportunidade de fato aconteceu). A leitura mais recente do tema na semana prevalece.

Depois: `python motor.py atualizar <semana>`. Se der ERRO, corrija o incremento e rode de novo.

## 3. Gatilhos → análise
Se o `atualizar` imprimir `GATILHO <setor>` (ou `trabalho/<semana>/gatilhos.json` listar setores),
grave `trabalho/<semana>/analise.json` reescrevendo **só** esses setores, a partir das notícias e
indicadores da semana:
```json
{"setores": {"industria": {"prov": "pergunta curta", "quote": "1 frase com número real",
  "edi": ["1 a 2 parágrafos factuais"], "acoes": [{"ico": "🏭", "txt": "ação prática"}]}},
 "panorama": {"acoes": [{"ico": "📌", "txt": "..."}]}}
```
(`panorama` só se o gatilho for do panorama.) Sem gatilho, não grave análise.
Então: `python motor.py previa <semana>`.

## 4. Segunda-feira: fechamento de `W_PREV` (antes da prévia de `W_CUR`)
1. Faça os passos 1–3 para `W_PREV` com as notícias de domingo (se houver).
2. Garanta que todo tema com notícia na semana (`temas_noticias.json`, chave `W_PREV`) tenha leitura em
   `trabalho/W_PREV/coleta.json` → `leituras_temas`. Faltando, inclua via incremento (só leituras) e `atualizar`.
3. `python motor.py fechar W_PREV` → gera `trabalho/W_PREV/prompt_editorial.md`.
4. Grave `trabalho/W_PREV/agenda.md`: divulgações e eventos com data CONFIRMADA nas próximas semanas
   (IBGE, Copom, Focus, datas do varejo), um por linha `- dd/mm (dia): evento (fonte). contexto.`
5. Escreva `trabalho/W_PREV/editorial.txt` seguindo à risca o `prompt_editorial.md` (preditivo: abre com
   perspectiva; depois por setor; fecha com resumo; 280 a 360 palavras; toda projeção marcada como tal).
6. `python motor.py publicar W_PREV`.
7. Depois, faça os passos 1–3 para `W_CUR` (notícias de segunda cedo; se não houver nenhuma, rode só
   `python motor.py atualizar W_CUR` e `python motor.py previa W_CUR` para abrir a semana).

Retomada: se `trabalho/W_PREV/processado.json` já existe mas `data/W_PREV.json` ainda está
`"status": "em_andamento"`, pule o `fechar` e continue do passo 4.

## 5. Conferência e publicação
- Indicadores oficiais: se o motor imprimir `FONTE INDISPONÍVEL`, NÃO edite números à mão — o motor
  mantém o último valor oficial já publicado na semana. Apenas registre no resumo quais fontes falharam.
- Nenhum comando pode ter terminado com `ERRO`. Se algo falhar e você não conseguir corrigir só com
  dados, **não faça push**: relate o erro.
- `git add -A && git commit -m "Rotina <HOJE>: <resumo>"` com a linha final
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` e `git push origin main`
  (se rejeitado, `git pull --rebase origin main` e push de novo). O Vercel publica sozinho.
- Resumo final em português: a linha `Acesso:` do passo 0.1, notícias novas por semana, palavras/temas novos, gatilhos e setores
  reescritos, se houve fechamento, e avisos do motor.
