"""
FIX_EDITORIAL — gera o editorial de semanas que ficaram sem ele (editorial: null),
SEM refazer a coleta de notícias (economiza cota do Gemini).

Lê os arquivos data/*.json, e para cada um que tiver editorial ausente/nulo,
gera o editorial a partir dos dados JÁ coletados (clipping, pestel, kpis, sinais)
e do editorial da semana anterior — a mesma lógica longitudinal do motor.

Rode uma vez pelo Actions. É idempotente: semanas que já têm editorial são puladas.
"""
import os
import re
import json
import glob

import motor
from motor import gerar_editorial, create_client, SUPABASE_URL, SUPABASE_KEY


def ordem(chave):
    m = re.match(r"(\d{4})-W(\d+)", chave or "")
    return int(m.group(1)) * 100 + int(m.group(2)) if m else -1


def main():
    if not os.path.isdir("data"):
        print("[fix-ed] pasta data/ não existe.")
        return

    # coleta os arquivos de semana, em ordem cronológica (mais antiga primeiro,
    # para o editorial de cada uma poder referenciar o da anterior)
    arquivos = []
    for caminho in glob.glob("data/*.json"):
        nome = os.path.basename(caminho)
        if nome in ("ultimo.json", "index.json"):
            continue
        m = re.match(r"(\d{4}-W\d+)\.json$", nome)
        if m:
            arquivos.append((m.group(1), caminho))
    arquivos.sort(key=lambda x: ordem(x[0]))

    if not arquivos:
        print("[fix-ed] nenhum arquivo de semana encontrado.")
        return

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    gerados, pulados, falhas = 0, 0, 0

    for chave, caminho in arquivos:
        with open(caminho, encoding="utf-8") as f:
            dados = json.load(f)

        # já tem editorial? pula (idempotente)
        if (dados.get("editorial") or {}).get("texto"):
            pulados += 1
            print(f"[fix-ed] {chave}: já tem editorial, pulando.")
            continue

        # monta o pacote de dados que o gerar_editorial espera.
        # os "novos_sinais" não são reprocessados — usamos os sinais longitudinais já salvos.
        pacote = {
            "kpis": dados.get("kpis", []),
            "novos_sinais": [],
            "clipping": dados.get("clipping", []),
        }
        label = dados.get("label", chave)
        print(f"[fix-ed] {chave}: gerando editorial a partir dos dados existentes...")
        try:
            editorial = gerar_editorial(sb, chave, label, pacote)
        except Exception as e:
            editorial = None
            print(f"[fix-ed] {chave}: erro ao gerar: {e}")

        if editorial and editorial.get("texto"):
            dados["editorial"] = editorial
            with open(caminho, "w", encoding="utf-8") as f:
                json.dump(dados, f, ensure_ascii=False, indent=2)
            gerados += 1
            print(f"[fix-ed] {chave}: editorial gerado e salvo "
                  f"({editorial['n_sinais_considerados']} sinais).")
        else:
            falhas += 1
            print(f"[fix-ed] {chave}: editorial não gerado (segue).")

    # atualiza ultimo.json com a versão mais recente (que agora pode ter editorial)
    if arquivos:
        chave_recente = max(arquivos, key=lambda x: ordem(x[0]))[0]
        caminho_recente = f"data/{chave_recente}.json"
        if os.path.exists(caminho_recente):
            with open(caminho_recente, encoding="utf-8") as f:
                conteudo = json.load(f)
            with open("data/ultimo.json", "w", encoding="utf-8") as f:
                json.dump(conteudo, f, ensure_ascii=False, indent=2)
            print(f"[fix-ed] ultimo.json atualizado para {chave_recente}.")

    print(f"[fix-ed] Concluído: {gerados} gerados, {pulados} já tinham, {falhas} falhas.")


if __name__ == "__main__":
    main()
