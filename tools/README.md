# Regra pétrea de grounding — notícias 100% reais, 0 alucinação

O Nexosim deriva **todas** as análises (PESTEL, Riscos & Oportunidades, Cadeia de Impacto,
5 Forças, Trajetórias, Indicadores) das notícias semanais acumuladas. Se a base tiver
notícia alucinada, toda a inteligência acima dela fica contaminada. Por isso vale uma
**regra inegociável**:

> **Uma notícia só entra — ou permanece — na base se tiver pelo menos uma fonte cujo
> CONTEÚDO (não apenas o status HTTP) confirme o fato citado.**

`HTTP 200 não prova nada`: o erro mais perigoso é o link que abre normalmente e mesmo
assim é falso (ex.: YouTube com id inventado devolve 200; página genérica/“home” devolve
200 sem a matéria). A prova é o **conteúdo**: a página existe *e afirma o fato* (número,
data e entidade batem).

## Os 5 tipos de fonte suspeita (e como o verificador pega cada um)

| Tipo | Detecção |
|------|----------|
| 1. URL morta (404/000/DNS) | status HTTP |
| 2. URL viva, página errada (200 mas não cita o fato) | match de conteúdo: tokens do título + número no corpo |
| 3. 200 falso de plataforma (recurso não existe) | checagem específica (YouTube oembed, etc.) |
| 4. Fato inventado (número que nenhuma fonte afirma) | idem #2 — a página cita **aquele** número? |
| 5. Lixo de geração (`[cite:]`, placeholder) | regex de artefatos |

## Como rodar

```bash
node tools/verificar_grounding.mjs            # relatório de todas as semanas com clipping
node tools/verificar_grounding.mjs W29        # só uma semana
node tools/verificar_grounding.mjs --apply    # + marca ok:false nas fontes MORTAS/FABRICADAS
```

Gera `tools/verif_report.json`. Classificação por fonte:
`ok` (conteúdo confere) · `revisar` (200 mas fraco/bloqueado — pode ser JS-shell) ·
`nao_confere` (200 mas conteúdo não bate) · `morta` (HTTP falhou) · `fabricada` (plataforma nega) ·
`sem_url`. Item fica `verificado` se tiver ≥1 fonte `ok`.

## Política de aplicação (conservadora)

- `--apply` só marca `ok:false` em fontes **`morta`** e **`fabricada`** — inequívocas.
- **Nunca** mata `nao_confere`/`revisar` automaticamente: há falso-negativo por bloqueio a
  bot / página em JavaScript. Esses vão para **adjudicação por busca real** (recuperar uma
  fonte cujo conteúdo confirme o fato — sempre reverificando a URL antes de gravar).
- Um item que não obtém nenhuma fonte `ok` fica com as fontes marcadas e o painel o exibe
  como **“⚠ fonte fora do ar”**, não-clicável — honesto, nunca fabricado.

## Duas camadas de defesa

1. **Prevenção (no motor):** `prompt_geracao.py` proíbe “montar” URL por dedução de slug/data;
   só cita link que apareceu literalmente na busca (“melhor pouco e real”).
2. **Verificação (na ingestão):** este verificador roda em **toda semana nova** antes de
   publicar, e periodicamente sobre a base (links apodrecem com o tempo).
