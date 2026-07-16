/**
 * GERADOR DO SEED DETERMINÍSTICO DE SINAIS (W1–W29) para o Supabase.
 *
 * Objetivo: dar ao motor Gemini (que assume no fluxo vivo a partir de W30) uma MEMÓRIA
 * de sinais do histórico jan–jul, derivada do CLIPPING JÁ VERIFICADO — sem LLM, auditável.
 * NÃO escreve no Supabase: só emite tools/supabase_seed.json para o uploader (CI) consumir.
 *
 * Método: agrupa o clipping por TEMA (mesmo vocabulário do portal, TAGVOC), cronologicamente.
 * Cada tema que aparece vira 1 "sinal" com trajetória (persistência/relevância pela MESMA
 * fórmula do motor.py) e uma "observação" por semana em que apareceu. Severidade/iminência
 * são heurísticas (marcadas origem='backfill_deterministico'); o Gemini as refina ao vivo.
 *
 * Uso: node tools/seed_supabase_gen.mjs
 */
import fs from 'fs';

// ── vocabulário e classificadores (espelho do index.html) ────────────────────
const TAGVOC={tarifas:/tarifa|eua|estados unidos|comércio exterior|exporta/i,energia:/energia|aneel|elétric|tarifári/i,juros:/selic|juro|copom|crédito|financ/i,cambio:/câmbio|dólar|balança comercial/i,safra:/safra|grão|soja|milho|agronegócio|conab|leite|caf[ée]|carne|boi|pecuár/i,consumo:/consumo|varejo|venda|confiança|endivida/i,digital:/digital|tecnologia|\bia\b|automação|autoatendimento|e-commerce|marketplace/i,escala6x1:/6x1|jornada de trabalho|escala/i,remessa:/remessa conforme|cross-border|importados de baixo/i,construcao:/construção|obra|incc|sinapi|imobiliári/i,inflacao:/ipca|igp|\bipc\b|inflaç|deflaç/i,atividade:/\bpim\b|\bpmi\b|produç[ãa]o industrial|industrial|\bpib\b|atividade econ/i,emprego:/caged|pnad|desemprego|desocupa|\bemprego|vagas?\b/i,servicos:/\bpms\b|serviç/i,combustiveis:/diesel|petról|combustív|gasolina|\banp\b|barril/i};
const TEMA_LABELS={tarifas:"Tarifas e comércio exterior (EUA)",energia:"Custo de energia (ANEEL/tarifa)",juros:"Juros, Selic e crédito",cambio:"Câmbio e balança",safra:"Safra e agro",consumo:"Consumo e varejo",digital:"Digitalização e IA",escala6x1:"Escala 6x1 e jornada",remessa:"Remessa Conforme e importados",construcao:"Construção e custos",inflacao:"Inflação (IPCA/IGP)",atividade:"Atividade e indústria (PIM/PMI)",emprego:"Emprego e renda (CAGED/PNAD)",servicos:"Serviços (PMS)",combustiveis:"Combustíveis e petróleo"};
const _RISCO=/queda|caiu?|recuo|recua|crise|encarece|inadimpl|press[ãa]o|dificuldade|desacelera|contra[çc][ãa]o|d[ée]ficit|preju[íi]zo|demiss|greve|atraso|escassez|restri[çc]|tombo|piora|\brisco|amea[çc]|endivida|redu[çz]|sobretaxa|abaixo d[ae]|negativ|\bperda|desemprego|encolhe|desafio|tens[ãa]o|choque|pressionad/i;
const _OPP=/cresce|crescimento|avan[çc]|otimis|expans[ãa]o|investiment|aporte|oportunidade|lan[çc]a|inova[çc]|recorde|aquecid|impulsiona|recupera[çc]|\bmelhora|super[áa]vit|acelera[çc]|amplia|expande|\bforte|sobe\b|positiv|beneficia|aquece|dispara|elev(a|ou)/i;
const _STRONG=/recorde|forte|crise|disparad?|bilh[õo]|maior|hist[óo]ric|colaps|salto|tombo|dispara|choque/i;
const tipoDe=t=>{const rc=(t.match(new RegExp(_RISCO.source,"gi"))||[]).length,oc=(t.match(new RegExp(_OPP.source,"gi"))||[]).length;return rc>=oc?"risco":"oportunidade";};
const dimDe=t=>{if(/tarifa|governo|política|eua|congresso|\bmp\b|medida provisória|plano safra/i.test(t))return"P";if(/\blei\b|jornada|6x1|tribut|remessa conforme|regula|judicial|\bcmn\b/i.test(t))return"L";if(/tecnologia|digital|\bia\b|automação|e-commerce|marketplace|autoatendimento/i.test(t))return"T";if(/energia|aneel|clima|leilão|ambient|sustentab/i.test(t))return"A";if(/consumo|emprego|renda|confiança|endivida|desemprego|social/i.test(t))return"S";return"E";};

// ── fórmula de relevância (idêntica ao motor.py) ─────────────────────────────
const calcRel=(sev,imin,persist,corrob,mat,ciclos)=>{
  const base=sev*0.35+imin*0.25+Math.min(persist,10)*0.20+Math.min(corrob,10)*0.20;
  const decay=Math.max(1-ciclos*0.10,0.4);
  return Math.round(Math.min(base*10*(mat?1.25:1)*decay,100)*100)/100;
};
const LIMIAR_DORMIR=25.0, CICLOS_DORMIR=3;
// segunda-feira ISO da semana N de 2026 (W01 = 2025-12-29)
const segunda=n=>{const d=new Date(Date.UTC(2025,11,29)+ (n-1)*7*864e5);return d.toISOString().slice(0,10);};
const NOW_WK=29; // "agora" do seed = última semana com dados

// ── carrega clipping por semana ──────────────────────────────────────────────
const semanas=[];
for(let n=1;n<=29;n++){const f=`data/2026-W${String(n).padStart(2,"0")}.json`;if(!fs.existsSync(f))continue;
  const d=JSON.parse(fs.readFileSync(f,"utf8"));
  semanas.push({n, key:`2026-W${n}`, clip:(d.clipping||[]).map(c=>({t:c.titulo,txt:c.texto||"",setores:(c.setores||[]).length?c.setores:["transversal"],fontes:(c.fontes||[]).filter(f=>f.url)}))});}

// ── monta um sinal por tema ──────────────────────────────────────────────────
const seed=[];
for(const key of Object.keys(TAGVOC)){
  const re=TAGVOC[key];
  const hits=[]; // {n,key, cls:[clip...]}
  for(const s of semanas){const cl=s.clip.filter(c=>re.test(c.t+" "+c.txt)); if(cl.length)hits.push({n:s.n,key:s.key,cls:cl});}
  if(!hits.length)continue;
  const all=hits.flatMap(h=>h.cls);
  const strongFrac=all.filter(c=>_STRONG.test(c.t+" "+c.txt)).length/all.length;
  const riscoFrac=all.filter(c=>tipoDe(c.t+" "+c.txt)==="risco").length/all.length;
  const tipo=riscoFrac>=0.5?"risco":"oportunidade";
  const dimCount={};all.forEach(c=>{const dd=dimDe(c.t+" "+c.txt);dimCount[dd]=(dimCount[dd]||0)+1;});
  const dimensao=Object.keys(dimCount).sort((a,b)=>dimCount[b]-dimCount[a])[0];
  const setores=[...new Set(all.flatMap(c=>c.setores))];
  const persist=hits.length;
  const corrob=Math.min(10, all.reduce((a,c)=>a+(c.fontes.length||1),0));
  const severidade=Math.round(Math.max(3,Math.min(9, 4.5+3*strongFrac+(tipo==="risco"?0.5:0)))*10)/10;
  const iminencia=5.0;
  const lastN=hits[hits.length-1].n;
  const ciclos=Math.max(0, NOW_WK-lastN- (persist>=6?100:0) <0?0: (NOW_WK-lastN>2? Math.min(NOW_WK-lastN-2, 10):0)); // temas recorrentes (mensais) ~0; pontuais decaem
  const materializado=false;
  const relAtual=calcRel(severidade,iminencia,persist,corrob,materializado,ciclos);
  const relPico=calcRel(severidade,iminencia,persist,corrob,materializado,0);
  let status = (relAtual<LIMIAR_DORMIR&&ciclos>=CICLOS_DORMIR)?"dormindo":(lastN>=NOW_WK-2?"em_curso":"monitorar");
  // observações: uma por semana em que o tema apareceu
  const observacoes=hits.map(h=>{
    const rel=Math.min(100,Math.round(h.cls.reduce((a,c)=>a+(1+(_STRONG.test(c.t+c.txt)?0.8:0)),0)*20));
    const fontes=[...new Map(h.cls.flatMap(c=>c.fontes).map(f=>[f.url,{nome:f.nome||"Fonte",url:f.url}])).values()];
    return {periodo:h.key, texto:`${h.cls.length} notícia(s) do tema nesta semana. Ex.: ${h.cls[0].t}${h.cls.length>1?` (+${h.cls.length-1})`:''}.`,
      status_resultante:status, relevancia_resultante:rel, fontes, delta:0};
  });
  seed.push({
    tipo, titulo:TEMA_LABELS[key], dimensao, setores,
    data_identificacao:segunda(hits[0].n), status,
    severidade, iminencia, persistencia:persist, corroboracao:corrob,
    materializado, ciclos_sem_aparecer:ciclos,
    relevancia_atual:relAtual, relevancia_pico:relPico, data_pico:segunda(lastN),
    ultimo_periodo:hits[hits.length-1].key, ultimo_ciclo_contado:hits[hits.length-1].key,
    _tema:key, observacoes,
  });
}
fs.writeFileSync("tools/supabase_seed.json", JSON.stringify(seed,null,2));
console.log(`Gerados ${seed.length} sinais · ${seed.reduce((a,s)=>a+s.observacoes.length,0)} observações → tools/supabase_seed.json\n`);
for(const s of seed.sort((a,b)=>b.relevancia_atual-a.relevancia_atual))
  console.log(`  ${s.tipo.padEnd(12)} ${s.dimensao} rel=${String(s.relevancia_atual).padStart(6)} pico=${String(s.relevancia_pico).padStart(6)} persist=${String(s.persistencia).padStart(2)} corrob=${String(s.corroboracao).padStart(2)} ciclos=${s.ciclos_sem_aparecer} ${s.status.padEnd(9)} | ${s.titulo}`);
