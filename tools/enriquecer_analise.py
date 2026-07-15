"""
ENRIQUECIMENTO RETROATIVO CONTROLADO (W1–W21) — camada qualitativa via Gemini.

Preenche pestel / porter (5 Forças) / analise / editorial das semanas de backfill,
SINTETIZANDO a partir do CLIPPING JÁ VERIFICADO + KPIs oficiais de cada semana.

Salvaguardas (0 alucinação de FATO):
  - O Gemini roda SEM ferramenta de busca (não acessa a internet) → não pode
    re-buscar nem inventar notícia; só interpreta o que é fornecido.
  - Prompt proíbe explicitamente números/eventos/fontes fora do material dado.
  - GATE de grounding nas saídas: todo número FACTUAL citado na análise/editorial
    tem de aparecer no clipping/KPIs da própria semana; se algum não aparecer, a
    semana é PULADA (não sobrescreve) e vai para tools/enriquecer_report.json.
  - Preserva clipping, kpis, kpis_setoriais, pressoes_ipca. Escreve só a camada
    analítica. Roda em ordem cronológica (editorial dá continuidade ao anterior).

Uso (CI): GEMINI_API_KEY no ambiente → python tools/enriquecer_analise.py
Dry-run local (sem API): DRY_RUN=1 python tools/enriquecer_analise.py  (imprime o prompt de 1 semana)
"""
import os
import re
import json
import time
from datetime import datetime

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
MODELO = "gemini-2.5-flash"
MODELO_FALLBACK = "gemini-2.5-flash-lite"
DRY_RUN = os.environ.get("DRY_RUN") == "1"
SETORES = ["industria", "comercio", "servicos", "agro", "construcao", "ecommerce"]

def _parse_semanas(spec):
    """ENRIQ_SEMANAS: '' (todas W1-21) | '11' | '1-21' | '1,5,11'."""
    spec = (spec or "").strip()
    if not spec:
        return list(range(1, 22))
    out = []
    for parte in spec.split(","):
        parte = parte.strip()
        if "-" in parte:
            a, b = parte.split("-")
            out += list(range(int(a), int(b) + 1))
        elif parte:
            out.append(int(parte))
    return [n for n in out if 1 <= n <= 21]

SEMANAS = _parse_semanas(os.environ.get("ENRIQ_SEMANAS"))

# ── util ─────────────────────────────────────────────────────────────────────
def norm(s):
    return (s or "").lower().translate(str.maketrans(
        "áàâãäéèêëíìîïóòôõöúùûüç", "aaaaaeeeeiiiiooooouuuuc")).replace(" ", "")

def extrair_json(texto):
    texto = re.sub(r"^```(?:json)?|```$", "", (texto or "").strip(), flags=re.MULTILINE).strip()
    ini, fim = texto.find("{"), texto.rfind("}")
    if ini == -1 or fim == -1:
        raise ValueError("resposta sem JSON")
    return json.loads(texto[ini:fim + 1])

_NUM = re.compile(r"\d{1,3}(?:\.\d{3})*,\d+|\d+,\d+|\d+%|r\$\s*\d[\d.,]*|us\$\s*\d[\d.,]*|\d{3,}", re.I)
def anchors(t):
    out = set()
    for m in _NUM.finditer(t or ""):
        a = norm(m.group(0)).replace("r$", "").replace("us$", "").replace("%", "")
        if re.search(r"\d,\d|\d{2,}", a):
            out.add(a)
    return out

# ── coleta de texto da semana (o "verdadeiro" que ancora a análise) ──────────
def clip_text(d):
    return " ".join((c.get("titulo", "") + " " + c.get("texto", "")) for c in d.get("clipping", []))

def kpis_text(d):
    parts = []
    for k in d.get("kpis", []):
        parts.append(f"{k.get('label','')} {k.get('valor','')} {k.get('sub','')}")
    for k in d.get("kpis_setoriais", []):
        parts.append(f"{k.get('label','')} {k.get('valor','')} {k.get('sub','')}")
    p = d.get("pressoes_ipca") or {}
    for g in p.get("grupos", []):
        parts.append(f"{g.get('nome','')} {g.get('val','')}")
    return " ".join(parts)

# strings de saída que carregam NÚMERO factual (porter/scores 0-10 ficam de fora do gate)
def narrativa_saida(dados):
    s = []
    for p in dados.get("pestel", []):
        s += [p.get("tema", ""), p.get("texto", "")]
    for _, v in (dados.get("porter", {}) or {}).items():
        s.append(v.get("nota", ""))
    an = dados.get("analise", {}) or {}
    for a in (an.get("panorama", {}) or {}).get("acoes", []):
        s.append(a.get("txt", ""))
    for _, sv in (an.get("setores", {}) or {}).items():
        s += [sv.get("prov", ""), sv.get("quote", "")] + list(sv.get("edi", []))
        s += [a.get("txt", "") for a in sv.get("acoes", [])]
    s.append(dados.get("editorial", "") if isinstance(dados.get("editorial"), str) else "")
    return " ".join(x for x in s if x)

# ── prompt ───────────────────────────────────────────────────────────────────
def montar_prompt(label, d, editorial_anterior):
    clip = "\n".join(
        f"- [{','.join(c.get('setores', ['transversal']))}] {c.get('titulo','')} — {c.get('texto','')}"
        for c in d.get("clipping", []))
    kpis = "\n".join(f"- {k.get('label','')}: {k.get('valor','')} ({k.get('sub','')})"
                     for k in d.get("kpis", []))
    setoriais = "\n".join(f"- {k.get('label','')}: {k.get('valor','')} ({k.get('sub','')})"
                          for k in d.get("kpis_setoriais", []))
    cont = (f'No editorial da semana anterior escrevemos: "{editorial_anterior}". '
            "Dê continuidade (confirme/ajuste/contraste)." if editorial_anterior
            else "Esta é a primeira semana; estabeleça a leitura de base.")
    return f"""Você é o analista-chefe de inteligência de mercado da Nexos, produzindo a
camada ANALÍTICA da semana {label} de forma RETROATIVA.

⚠️ VOCÊ NÃO TEM ACESSO À INTERNET. Use EXCLUSIVAMENTE o clipping e os indicadores
abaixo. É PROIBIDO citar número, evento, empresa ou fonte que NÃO esteja neste
material. Isto é INTERPRETAÇÃO dos fatos dados — não coleta. Se um setor não tiver
notícia própria, faça a leitura transversal a partir do quadro macro fornecido,
sem inventar fatos setoriais.

# CLIPPING VERIFICADO DA SEMANA (única base factual permitida)
{clip or "(sem itens)"}

# INDICADORES MACRO OFICIAIS
{kpis or "(n/d)"}

# INDICADORES SETORIAIS
{setoriais or "(n/d)"}

# CONTINUIDADE
{cont}

Responda SOMENTE com JSON válido, sem markdown, EXATAMENTE nesta forma:
{{
  "pestel": [
    {{"dim":"P","nome":"Político","tema":"...","texto":"...","score":6.0,"setores":["transversal"]}},
    {{"dim":"E","nome":"Econômico","tema":"...","texto":"...","score":7.5,"setores":["transversal"]}},
    {{"dim":"S","nome":"Social","tema":"...","texto":"...","score":6.0,"setores":["comercio","servicos"]}},
    {{"dim":"T","nome":"Tecnológico","tema":"...","texto":"...","score":5.0,"setores":["servicos"]}},
    {{"dim":"A","nome":"Ambiental","tema":"...","texto":"...","score":5.0,"setores":["agro"]}},
    {{"dim":"L","nome":"Legal","tema":"...","texto":"...","score":5.0,"setores":["transversal"]}}
  ],
  "porter": {{
    "industria":{{"rivalidade":7,"entrantes":4,"fornecedores":8,"compradores":6,"substitutos":5,"nota":"..."}},
    "comercio":{{"rivalidade":8,"entrantes":7,"fornecedores":5,"compradores":8,"substitutos":7,"nota":"..."}},
    "servicos":{{"rivalidade":7,"entrantes":6,"fornecedores":5,"compradores":6,"substitutos":6,"nota":"..."}},
    "agro":{{"rivalidade":6,"entrantes":3,"fornecedores":7,"compradores":7,"substitutos":3,"nota":"..."}},
    "construcao":{{"rivalidade":6,"entrantes":5,"fornecedores":7,"compradores":6,"substitutos":3,"nota":"..."}},
    "ecommerce":{{"rivalidade":9,"entrantes":8,"fornecedores":6,"compradores":9,"substitutos":7,"nota":"..."}}
  }},
  "analise": {{
    "panorama": {{"acoes":[{{"ico":"💸","txt":"ação macro prática ancorada num número/evento REAL do material"}}]}},
    "setores": {{
      "industria":{{"prov":"...","quote":"1 frase com número/fato REAL do material","edi":["parágrafo curto factual"],"acoes":[{{"ico":"⚡","txt":"..."}}]}},
      "comercio":{{"prov":"...","quote":"...","edi":["..."],"acoes":[{{"ico":"🛒","txt":"..."}}]}},
      "servicos":{{"prov":"...","quote":"...","edi":["..."],"acoes":[{{"ico":"🤖","txt":"..."}}]}},
      "agro":{{"prov":"...","quote":"...","edi":["..."],"acoes":[{{"ico":"🌾","txt":"..."}}]}},
      "construcao":{{"prov":"...","quote":"...","edi":["..."],"acoes":[{{"ico":"🏗️","txt":"..."}}]}},
      "ecommerce":{{"prov":"...","quote":"...","edi":["..."],"acoes":[{{"ico":"📦","txt":"..."}}]}}
    }}
  }},
  "editorial": "texto corrido de 240 a 320 palavras, formal e sem jargão, cobrindo o quadro macro (Selic, IPCA, câmbio, atividade) com os NÚMEROS REAIS do material, o que mudou, uma leitura por bloco setorial e o ponto de atenção. Só fatos do material."
}}
Regras: pestel sempre as 6 dimensões (score 0–10); porter os 6 setores (0–10); analise os 6 setores. Todo número citado DEVE existir no material acima."""

# ── Gemini ───────────────────────────────────────────────────────────────────
def _gerar(client, prompt, config):
    from google.genai import types
    try:
        return client.models.generate_content(model=MODELO, contents=prompt, config=config)
    except Exception as e:
        s = str(e).lower()
        if any(t in s for t in ("resource_exhausted", "429", "quota")) and any(
                t in s for t in ("perday", "per day", "daily")):
            return client.models.generate_content(model=MODELO_FALLBACK, contents=prompt, config=config)
        raise

def main():
    if DRY_RUN:
        n = 11
        with open(f"data/2026-W{n:02d}.json", encoding="utf-8") as f:
            d = json.load(f)
        print(montar_prompt(d.get("label", f"W{n}"), d, "(anterior)"))
        return

    from google import genai
    from google.genai import types
    client = genai.Client(api_key=GEMINI_KEY)
    cfg = types.GenerateContentConfig(temperature=0.4, max_output_tokens=32768)  # SEM tools = sem busca

    prev_ed, report, ok, pulados = "", [], 0, 0
    for n in SEMANAS:
        path = f"data/2026-W{n:02d}.json"
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if not d.get("clipping"):
            continue
        prompt = montar_prompt(d.get("label", f"W{n}"), d, prev_ed)
        try:
            resp = _gerar(client, prompt, cfg)
            dados = extrair_json(resp.text)
        except Exception as e:
            report.append({"semana": f"W{n}", "status": "erro", "detalhe": str(e)[:200]})
            print(f"[enriq] W{n}: erro ({str(e)[:120]}) — pulado")
            pulados += 1
            continue

        base = norm(clip_text(d) + " " + kpis_text(d))
        faltantes = sorted(a for a in anchors(narrativa_saida(dados)) if a not in base)
        if faltantes:
            report.append({"semana": f"W{n}", "status": "gate_reprovado",
                           "numeros_sem_lastro": faltantes[:20]})
            print(f"[enriq] W{n}: GATE reprovou {len(faltantes)} número(s) sem lastro — NÃO sobrescrito. {faltantes[:8]}")
            pulados += 1
            continue

        # merge só da camada analítica, preservando o resto
        d["pestel"] = dados.get("pestel", [])
        d["porter"] = dados.get("porter", {})
        d["analise"] = dados.get("analise", {})
        ed = dados.get("editorial", "")
        if isinstance(ed, str) and ed.strip():
            d["editorial"] = {"texto": ed.strip(), "origem": "gemini_retroativo",
                              "gerado_em": datetime.utcnow().isoformat()}
            prev_ed = ed.strip()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        ok += 1
        print(f"[enriq] W{n}: ✓ enriquecido (pestel/porter/analise/editorial)")
        time.sleep(2)  # respeita rate limit da cota gratuita

    with open("tools/enriquecer_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n[enriq] Concluído: {ok} enriquecidas, {pulados} puladas. Ver tools/enriquecer_report.json")

if __name__ == "__main__":
    main()
