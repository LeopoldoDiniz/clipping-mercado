"""
BACKFILL DE KPIS OFICIAIS — reescreve os indicadores macro de TODO o histórico
(data/*.json) com os valores OFICIAIS (BCB/IBGE) válidos na sexta-feira de cada
semana, incluindo o acumulado no ano. Corrige de uma vez a base inteira, até a
semana mais antiga, SEM usar o Gemini.

Não precisa de secrets (usa só APIs públicas). Rode no GitHub Actions
(workflow kpis_backfill.yml) ou localmente: `python backfill_kpis.py`.
"""
import os
import re
import glob
import json
from datetime import date

from kpis_oficiais import validar_kpis


def _sexta(chave):
    a, s = chave.split("-W")
    return date.fromisocalendar(int(a), int(s), 5)


def _ordem(chave):
    try:
        a, s = chave.split("-W")
        return int(a) * 100 + int(s)
    except (ValueError, AttributeError):
        return -1


def main():
    arquivos = []
    for fn in glob.glob("data/*.json"):
        base = os.path.basename(fn)
        m = re.match(r"(\d{4}-W\d+)\.json$", base)
        if m:
            arquivos.append((m.group(1), fn))
    if not arquivos:
        print("[kpis-backfill] nenhum arquivo de semana encontrado em data/.")
        return

    arquivos.sort(key=lambda t: _ordem(t[0]))  # cronológico
    ultimo_chave, ultimo_conteudo = None, None

    for chave, fn in arquivos:
        with open(fn, encoding="utf-8") as f:
            j = json.load(f)
        kpis = validar_kpis(j.get("kpis", []), ref=_sexta(chave), verbose=True)
        if kpis:
            j["kpis"] = kpis
            with open(fn, "w", encoding="utf-8") as f:
                json.dump(j, f, ensure_ascii=False, indent=2)
            print(f"[kpis-backfill] ✓ {chave}: {len(kpis)} indicadores oficiais")
        else:
            print(f"[kpis-backfill] ⚠ {chave}: APIs indisponíveis, mantido como estava")
        if ultimo_chave is None or _ordem(chave) >= _ordem(ultimo_chave):
            ultimo_chave, ultimo_conteudo = chave, j

    # ultimo.json aponta para a semana mais recente
    if ultimo_conteudo is not None:
        with open("data/ultimo.json", "w", encoding="utf-8") as f:
            json.dump(ultimo_conteudo, f, ensure_ascii=False, indent=2)
        print(f"[kpis-backfill] ultimo.json atualizado para {ultimo_chave}.")

    print("[kpis-backfill] Concluído. Faça commit da pasta data/ (o workflow já faz).")


if __name__ == "__main__":
    main()
