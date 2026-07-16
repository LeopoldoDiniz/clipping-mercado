"""
UPLOADER DO SEED DETERMINÍSTICO → Supabase (rodar via GitHub Actions, disparo manual).

Lê tools/supabase_seed.json (gerado por tools/seed_supabase_gen.mjs) e popula as tabelas
`sinais` e `observacoes` com a memória de sinais do histórico W1–W29, para que o motor
Gemini continue as trajetórias sem reset a partir de W30.

IDEMPOTENTE e ISOLADO: só remove/insere linhas com origem='backfill_deterministico'.
NUNCA toca nos sinais criados pelo Gemini (origem='real' ou 'backfill'). Rodar de novo
substitui apenas o próprio seed.

Precisa de SUPABASE_URL e SUPABASE_KEY no ambiente (GitHub Secrets). Não usa Gemini.
"""
import os
import json

from supabase import create_client


def _url():
    u = os.environ["SUPABASE_URL"].strip().rstrip("/")
    if u.endswith("/rest/v1"):
        u = u[: -len("/rest/v1")]
    return u.rstrip("/")


def main():
    sb = create_client(_url(), os.environ["SUPABASE_KEY"].strip())

    with open("tools/supabase_seed.json", encoding="utf-8") as f:
        seed = json.load(f)
    print(f"[seed] {len(seed)} sinais a inserir "
          f"({sum(len(s['observacoes']) for s in seed)} observações).")

    # 1) limpa o seed anterior. A tabela 'sinais' não tem coluna 'origem' (o motor vivo
    #    não a usa), então isolamos pelos TÍTULOS dos temas — que não colidem com os
    #    sinais-evento criados pelo Gemini (títulos descritivos distintos). Idempotente.
    titulos = [s["titulo"] for s in seed]
    antigos = sb.table("sinais").select("id").in_("titulo", titulos).execute().data
    ids = [r["id"] for r in antigos]
    if ids:
        sb.table("observacoes").delete().in_("sinal_id", ids).execute()
        sb.table("sinais").delete().in_("id", ids).execute()
        print(f"[seed] removidos {len(ids)} sinais de seed anteriores (idempotência).")

    # 2) insere sinais + observações
    n_sig, n_obs = 0, 0
    for s in seed:
        s = dict(s)
        obs = s.pop("observacoes", [])
        s.pop("_tema", None)
        res = sb.table("sinais").insert(s).execute()
        sid = res.data[0]["id"]
        n_sig += 1
        rows = [{**o, "sinal_id": sid} for o in obs]
        # insere em lotes para não estourar limites de payload
        for i in range(0, len(rows), 100):
            sb.table("observacoes").insert(rows[i:i + 100]).execute()
        n_obs += len(rows)
        print(f"[seed] ✓ {s['titulo']}  ({len(rows)} obs)")

    print(f"[seed] Concluído: {n_sig} sinais, {n_obs} observações. "
          "O motor Gemini continua daqui em W30.")


if __name__ == "__main__":
    main()
