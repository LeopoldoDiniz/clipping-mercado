"""Auditoria INDEPENDENTE dos indicadores setoriais e das pressões do IPCA (não usa kpis_oficiais)."""
import json, glob, os, re, gzip, ssl, urllib.request
from datetime import date

def raw(url, ctx=None):
    r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60, context=ctx).read()
    return (gzip.decompress(r) if r[:2] == bytes([0x1F, 0x8B]) else r).decode("utf-8")
def sidra(path):
    out = {}
    for x in json.loads(raw(f"https://apisidra.ibge.gov.br/values{path}/h/n")):
        if x["V"] in ("...", "..", "-"): continue
        out[(int(x["D3C"][:4]), int(x["D3C"][4:]))] = float(x["V"])
    return out
M = ["jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"]
pms, pms_a = sidra("/t/5906/n1/all/v/11623/p/last%2048/c11046/56726"), sidra("/t/5906/n1/all/v/11625/p/last%2048/c11046/56726")
sin = sidra("/t/2296/n1/all/v/48/p/last%2048")
lspa = sidra("/t/6588/n1/all/v/35/p/last%2048/c48/39428")
incc = {}
for o in json.loads(raw(f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.192/dados/ultimos/20?formato=json")):
    incc[(int(o["data"][6:]), int(o["data"][3:5]))] = float(o["valor"])
NOMES = {"pms": "Pesquisa Mensal de Serviços", "sinapi": "Sistema Nacional de Pesquisa de Custos e Índices da Construção Civil",
         "lspa": "Levantamento Sistemático da Produção Agrícola", "ipca": "Índice Nacional de Preços ao Consumidor Amplo"}
CAL = {k: {} for k in NOMES}
for it in json.loads(raw("https://servicodados.ibge.gov.br/api/v3/calendario/?de=01-01-2024&ate=12-31-2026&qtd=5000"))["items"]:
    for k, n in NOMES.items():
        if it["nome_produto"].strip() == n:
            d, mo, a = it["data_divulgacao"][:10].split("/")
            CAL[k][(it["ano_referencia_inicio"], it["mes_referencia_inicio"])] = date(int(a), int(mo), int(d))
ctx = ssl.create_default_context(); ctx.set_ciphers("DEFAULT@SECLEVEL=1")
h = raw("https://portalibre.fgv.br/calendario-de-divulgacao?field_divulgacao_data_value=2024-01-01&field_divulgacao_data_value_1=2026-12-31", ctx)
CAL["incc"] = {}
for d, mo, a, t in re.findall(r'field-divulgacao-data"><div class="field-content">(\d\d)/(\d\d)/(\d{4})</div>.*?views-field-title"><span class="field-content">(.*?)</span>', h, flags=re.S):
    m = re.search(r"([^\W\d_]+)/(\d{4})\s*$", t.strip())
    if "INCC-DI" in t and m: CAL["incc"][(int(m.group(2)), M.index(m.group(1)[:3].lower()) + 1)] = date(int(a), int(mo), int(d))

def esperado(serie, cal, ref):
    return max(k for k in serie if cal.get(k, date(2100, 1, 1)) <= ref)
def num(s): return float(re.sub(r"[^\d,\-]", "", s).replace(",", "."))
ok, err = 0, []
for fn in sorted(glob.glob("data/2026-W*.json")):
    ch = os.path.basename(fn)[:-5]; a, s = ch.split("-W")
    ref = min(date.today(), date.fromisocalendar(int(a), int(s), 7)) if ch >= "2026-W46" else date.fromisocalendar(int(a), int(s), 5)
    d = json.load(open(fn, encoding="utf-8"))
    for c in d.get("kpis_setoriais") or []:
        if c.get("mkt"): continue
        L = c["label"]; p = []
        fam = "pms" if "PMS" in L else "sinapi" if "SINAPI" in L else "lspa" if "LSPA" in L else "incc" if "INCC" in L else None
        ser = {"pms": pms, "sinapi": sin, "lspa": lspa, "incc": incc}[fam]
        k = esperado(ser, CAL[fam], ref)
        mm = re.search(r"(\w{3})/(\d{2})$", c["ref"]); kc = (2000 + int(mm.group(2)), M.index(mm.group(1)) + 1)
        if kc != k: p.append(f"mês {kc}≠{k}")
        v = num(c["valor"])
        if fam == "pms" and abs(v - round(ser[k], 1)) > 1e-4: p.append(f"valor {v}≠{ser[k]}")
        if fam == "pms":
            ma = re.search(r"acum\. ano \+?(-?[\d,]+)%", c["sub"])
            if ma and abs(num(ma.group(1)) - round(pms_a[k], 1)) > 1e-4: p.append(f"acum {ma.group(1)}≠{pms_a[k]}")
        if fam == "sinapi" and abs(v - round(ser[k])) > 1: p.append(f"valor {v}≠{ser[k]}")
        if fam == "lspa" and abs(v - round(ser[k] / 1e6, 1)) > 1e-4: p.append(f"valor {v}≠{ser[k]/1e6}")
        if fam == "incc" and abs(v - round(ser[k], 2)) > 1e-4: p.append(f"valor {v}≠{ser[k]}")
        if p: err.append((ch, L, c["valor"], "; ".join(p)))
        else: ok += 1
    pi = d.get("pressoes_ipca")
    if pi:
        k = max(kk for kk in CAL["ipca"] if CAL["ipca"][kk] <= ref)
        if (pi["ano"], pi["mes"]) != k: err.append((ch, "Pressões IPCA", pi["ref"], f"mês {(pi['ano'], pi['mes'])}≠{k}"))
        else: ok += 1
print(f"itens: {ok + len(err)} | batem: {ok} | divergem: {len(err)}")
for e in err: print("  ", *e, sep=" | ")
