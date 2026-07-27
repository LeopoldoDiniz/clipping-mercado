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

from kpis_oficiais import validar_kpis, INDISPONIVEL, _familia


def _preservar_oficiais(novos, antigos):
    """Se a fonte não respondeu para um indicador agora, NÃO apaga o que já estava
    lá — desde que o antigo tenha procedência oficial ('fonte' preenchida).

    A assimetria é proposital: valor antigo COM fonte é dado oficial já conferido e
    merece sobreviver a uma indisponibilidade passageira; valor antigo SEM fonte é
    resquício do Gemini e deve ser varrido, que é justamente o objetivo desta
    passada. Sem esta função, um BCB fora do ar durante o backfill transformaria o
    histórico inteiro em travessões."""
    por_fam = {}
    for a in (antigos or []):
        por_fam.setdefault(_familia(a.get("label", "")), a)

    saida, preservados = [], []
    for k in novos:
        if str(k.get("valor")) == INDISPONIVEL:
            velho = por_fam.get(_familia(k.get("label", "")))
            if velho and velho.get("fonte"):
                saida.append(dict(velho))
                preservados.append(k.get("label"))
                continue
        saida.append(k)
    return saida, preservados


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
    print(f"[kpis-backfill] {len(arquivos)} semanas. Buscando séries oficiais BCB/IBGE "
          f"(1ª semana busca; as demais reusam do cache)...")
    ultimo_chave, ultimo_conteudo = None, None

    for chave, fn in arquivos:
        with open(fn, encoding="utf-8") as f:
            j = json.load(f)
        antigos = j.get("kpis", [])
        kpis, preservados = _preservar_oficiais(
            validar_kpis(antigos, ref=_sexta(chave), verbose=True), antigos)
        if kpis:
            # Quantos números sem procedência havia antes: é a medida do estrago
            # que esta passada está desfazendo.
            sem_fonte = sum(1 for a in antigos if not a.get("fonte"))
            j["kpis"] = kpis
            with open(fn, "w", encoding="utf-8") as f:
                json.dump(j, f, ensure_ascii=False, indent=2)
            nota = f" · {sem_fonte} sem fonte antes" if sem_fonte else ""
            if preservados:
                nota += f" · preservados por indisponibilidade: {', '.join(preservados)}"
            print(f"[kpis-backfill] ✓ {chave}: {len(kpis)} indicadores oficiais{nota}")
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
