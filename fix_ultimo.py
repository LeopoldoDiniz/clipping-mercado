"""
FIX_ULTIMO — solução definitiva e determinística.

Não depende do motor, do Gemini nem do Supabase. Apenas OLHA a pasta data/,
encontra todos os arquivos de semana (AAAA-Www.json), escolhe o MAIS RECENTE
(maior ano+semana) e reescreve:
  - data/ultimo.json  = cópia exata do arquivo da semana mais recente
  - data/index.json   = índice de todas as semanas encontradas (ordenado)

Rode uma vez pelo GitHub Actions. Corrige o "ultimo.json congelado" de forma
garantida, seja qual for a causa (backfill, lógica condicional, etc.).
"""
import os
import re
import json
import glob


def ordem_da_chave(chave):
    """'2026-W26' -> 202626 (para comparar qual semana é a mais recente)."""
    m = re.match(r"(\d{4})-W(\d+)", chave or "")
    if not m:
        return -1
    return int(m.group(1)) * 100 + int(m.group(2))


def main():
    if not os.path.isdir("data"):
        print("[fix] ERRO: pasta data/ não existe. Nada a fazer.")
        return

    # 1. Encontra todos os arquivos de semana (ignora ultimo.json e index.json)
    arquivos = []
    for caminho in glob.glob("data/*.json"):
        nome = os.path.basename(caminho)
        if nome in ("ultimo.json", "index.json"):
            continue
        m = re.match(r"(\d{4}-W\d+)\.json$", nome)
        if m:
            arquivos.append((m.group(1), caminho))

    if not arquivos:
        print("[fix] ERRO: nenhum arquivo de semana (AAAA-Www.json) encontrado em data/.")
        return

    # 2. Ordena por recência (mais recente primeiro)
    arquivos.sort(key=lambda x: ordem_da_chave(x[0]), reverse=True)
    print(f"[fix] {len(arquivos)} semanas encontradas: {[c for c, _ in arquivos]}")

    chave_mais_recente, caminho_mais_recente = arquivos[0]
    print(f"[fix] Semana mais recente: {chave_mais_recente}")

    # 3. Reescreve ultimo.json = cópia exata da semana mais recente
    with open(caminho_mais_recente, encoding="utf-8") as f:
        conteudo = json.load(f)
    with open("data/ultimo.json", "w", encoding="utf-8") as f:
        json.dump(conteudo, f, ensure_ascii=False, indent=2)
    tem_editorial = bool((conteudo.get("editorial") or {}).get("texto"))
    print(f"[fix] ultimo.json reescrito para {chave_mais_recente} "
          f"(editorial: {'presente' if tem_editorial else 'ausente'}).")

    # 4. Reconstrói index.json com todas as semanas
    meses = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
             "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
    semanas = []
    for chave, caminho in arquivos:
        # tenta pegar o label de dentro do próprio arquivo
        try:
            with open(caminho, encoding="utf-8") as f:
                d = json.load(f)
            label = d.get("label", chave)
        except (json.JSONDecodeError, OSError):
            label = chave
        semanas.append({
            "chave": chave, "label": label,
            "arquivo": f"{chave}.json", "ordem": ordem_da_chave(chave),
        })
    semanas.sort(key=lambda s: s["ordem"], reverse=True)
    with open("data/index.json", "w", encoding="utf-8") as f:
        json.dump({"semanas": semanas}, f, ensure_ascii=False, indent=2)
    print(f"[fix] index.json reconstruído com {len(semanas)} semanas.")
    print("[fix] Concluído. Faça commit da pasta data/ (o workflow já faz isso).")


if __name__ == "__main__":
    main()
