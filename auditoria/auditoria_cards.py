"""Auditoria INDEPENDENTE dos 7 cards (não usa kpis_oficiais nem motor).
Critério: valor oficial atual (com revisões) do último mês cuja divulgação, pelo calendário
oficial do IBGE, ocorreu até a data de referência da semana (sexta; W46 = hoje)."""
import json, glob, os, re, gzip, urllib.request
from datetime import date, timedelta

def get(url):
    raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "auditoria", "Cache-Control": "no-cache", "Pragma": "no-cache"}), timeout=40).read()
    if raw[:2] == bytes([0x1F, 0x8B]): raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))

MESES = ["jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"]
def sidra(t, v, extra=""):
    j = get(f"https://apisidra.ibge.gov.br/values/t/{t}/n1/all/v/{v}/p/last%2048{extra}/h/n")
    out = {}
    for x in j:
        if x["V"] in ("...", "..", "-"): continue
        cod = x["D3C"]  # AAAAMM
        out[(int(cod[:4]), int(cod[4:]))] = float(x["V"])
    return out
def sgs(c):
    j = get(f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{c}/dados?formato=json&dataInicial=02/01/2025&dataFinal={date.today():%d/%m/%Y}")
    return sorted((date(int(o["data"][6:]), int(o["data"][3:5]), int(o["data"][:2])), float(o["valor"])) for o in j)

S = {
 "ipca": (sidra(1737, 63), sidra(1737, 69)),
 "desemprego": (sidra(6381, 4099), None),
 "varejo": (sidra(8880, 11708, "/c11046/56734"), sidra(8880, 11710, "/c11046/56734")),
 "pim": (sidra(8888, 11601, "/c544/129314"), sidra(8888, 11603, "/c544/129314")),
 "ipp": (sidra(6903, 1396), sidra(6903, 1395)),
}
SELIC, CAMBIO = sgs(432), sgs(1)
cal_j = get(f"https://servicodados.ibge.gov.br/api/v3/calendario/?de=01-01-2024&ate=12-31-2026&qtd=5000")["items"]
NOMES = {"ipca": "Índice Nacional de Preços ao Consumidor Amplo", "pim": "PIM-PF Brasil#pimpf1",
         "varejo": "Pesquisa Mensal de Comércio", "desemprego": "Divulgação mensal#pnadc1",
         "ipp": "Índice de Preços ao Produtor - Indústrias Extrativas e de Transformação"}
CAL = {f: {} for f in NOMES}
for it in cal_j:
    for f, n in NOMES.items():
        if it["nome_produto"].strip() == n:
            d, m, a = it["data_divulgacao"][:10].split("/")
            CAL[f][(it["ano_referencia_inicio"], it["mes_referencia_inicio"])] = date(int(a), int(m), int(d))

def num(s): return float(re.sub(r"[^\d,\-]", "", s).replace(",", "."))
def fam(label):
    L = label.lower()
    for k, f in (("selic","selic"),("ipca","ipca"),("câmbio","cambio"),("desemprego","desemprego"),("varejo","varejo"),("pim","pim"),("ipp","ipp")):
        if k in L: return f

ok, err = 0, []
for fn in sorted(glob.glob("data/2026-W*.json")):
    ch = os.path.basename(fn)[:-5]
    a, s = ch.split("-W")
    ref = min(date.today(), date.fromisocalendar(int(a), int(s), 7)) if ch >= "2026-W46" else date.fromisocalendar(int(a), int(s), 5)
    for c in json.load(open(fn, encoding="utf-8"))["kpis"]:
        f = fam(c["label"]); v = num(c["valor"]); prob = []
        if f in ("selic", "cambio"):
            ser = SELIC if f == "selic" else CAMBIO
            d_esp, v_esp = max(o for o in ser if o[0] <= ref)
            mm = re.search(r"(\d{2})/(\d{2})/(\d{4})", c["sub"])
            d_card = date(int(mm.group(3)), int(mm.group(2)), int(mm.group(1)))
            if d_card != d_esp: prob.append(f"data {d_card} ≠ {d_esp}")
            if abs(v - v_esp) > 0.005: prob.append(f"valor {v} ≠ {v_esp}")
        else:
            mens, acum = S[f]
            meses = [k for k in mens if CAL[f].get(k, date(2100, 1, 1)) <= ref]
            k_esp = max(meses)
            if f == "desemprego":
                mm = re.search(r"(\w{3})-(\w{3})-(\w{3}) (\d{4})", c["sub"])
                k_card = (int(mm.group(4)), MESES.index(mm.group(3)) + 1)
            else:
                mm = re.search(r"IBGE (\w{3})/(\d{2})", c["sub"])
                k_card = (2000 + int(mm.group(2)), MESES.index(mm.group(1)) + 1)
            if k_card != k_esp: prob.append(f"mês {k_card} ≠ {k_esp}")
            casas = 2 if f in ("ipca", "ipp") else 1
            if abs(v - round(mens[k_esp], casas)) > 0.0001: prob.append(f"valor {v} ≠ {mens[k_esp]}")
            ma = re.search(r"acum\. ano (-?[\d,]+)%", c["sub"])
            if acum is not None:
                if not ma: prob.append("sem acum. ano")
                elif abs(num(ma.group(1)) - round(acum[k_esp], casas)) > 0.0001:
                    prob.append(f"acum {ma.group(1)} ≠ {acum[k_esp]}")
        if prob: err.append((ch, c["label"], c["valor"], "; ".join(prob)))
        else: ok += 1
print(f"cards: {ok + len(err)} | batem: {ok} | divergem: {len(err)}")
for e in err: print("  ", *e, sep=" | ")
