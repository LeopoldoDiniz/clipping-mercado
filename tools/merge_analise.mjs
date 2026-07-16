/**
 * MERGE + GATE da camada analítica autoral (Claude) para semanas de backfill.
 * Lê um JSON { "W11": {pestel,porter,analise,editorial}, ... }, e para cada semana:
 *  - roda o MESMO gate de grounding do enriquecer_analise.py (todo número factual da
 *    análise/editorial tem de existir no clipping/KPIs da semana);
 *  - se passar, grava pestel/porter/analise + editorial (origem 'analise_claude'),
 *    preservando clipping/kpis/setoriais/pressoes; se falhar, NÃO grava e lista os números.
 *
 * Uso: node tools/merge_analise.mjs <arquivo.json>
 */
import fs from 'fs';

const norm = s => (s||'').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g,'').replace(/ /g,'');
const NUM = /\d{1,3}(?:\.\d{3})*,\d+|\d+,\d+|\d+%|r\$\s*\d[\d.,]*|us\$\s*\d[\d.,]*|\d{3,}/gi;
function anchors(t){
  const out=new Set(); let m;
  const r=new RegExp(NUM.source,'gi');
  while((m=r.exec(t||''))){
    const a=norm(m[0]).replace('r$','').replace('us$','').replace('%','').replace(/^[.,]+|[.,]+$/g,'');
    if(/\d,\d|\d{2,}/.test(a)) out.add(a);
  }
  return out;
}
const clipText = d => (d.clipping||[]).map(c=>c.titulo+' '+(c.texto||'')).join(' ');
function kpisText(d){
  const p=[];
  for(const k of d.kpis||[]) p.push(`${k.label} ${k.valor} ${k.sub}`);
  for(const k of d.kpis_setoriais||[]) p.push(`${k.label} ${k.valor} ${k.sub}`);
  for(const g of (d.pressoes_ipca||{}).grupos||[]) p.push(`${g.nome} ${g.val}`);
  return p.join(' ');
}
function narrativa(a){
  const s=[];
  for(const p of a.pestel||[]){s.push(p.tema,p.texto);}
  for(const k of Object.keys(a.porter||{})) s.push((a.porter[k]||{}).nota);
  const an=a.analise||{};
  for(const ac of (an.panorama||{}).acoes||[]) s.push(ac.txt);
  for(const k of Object.keys(an.setores||{})){const sv=an.setores[k]||{}; s.push(sv.prov,sv.quote,...(sv.edi||[]),...(sv.acoes||[]).map(x=>x.txt));}
  s.push(typeof a.editorial==='string'?a.editorial:'');
  return s.filter(Boolean).join(' ');
}

const inPath=process.argv[2];
const manual=JSON.parse(fs.readFileSync(inPath,'utf8'));
let ok=0, reprovados=[];
for(const wk of Object.keys(manual)){
  const n=+wk.replace(/\D/g,'');
  const fp=`data/2026-W${String(n).padStart(2,'0')}.json`;
  if(!fs.existsSync(fp)){console.log(`  ! ${wk}: arquivo inexistente`);continue;}
  const d=JSON.parse(fs.readFileSync(fp,'utf8'));
  const a=manual[wk];
  const base=norm(clipText(d)+' '+kpisText(d));
  const falt=[...anchors(narrativa(a))].filter(x=>!base.includes(x));
  if(falt.length){reprovados.push({wk,falt});console.log(`  ✗ ${wk}: GATE reprovou ${falt.length} número(s): ${JSON.stringify(falt)}`);continue;}
  d.pestel=a.pestel||d.pestel;
  d.porter=a.porter||d.porter;
  d.analise=a.analise||d.analise;
  if(typeof a.editorial==='string'&&a.editorial.trim())
    d.editorial={texto:a.editorial.trim(),origem:'analise_claude'};
  fs.writeFileSync(fp, JSON.stringify(d,null,2)+'\n','utf8');
  console.log(`  ✓ ${wk}: gravado (gate ok)`);
  ok++;
}
console.log(`\n${ok} gravadas, ${reprovados.length} reprovadas.`);
if(reprovados.length) console.log('Reprovadas (corrigir os números):', JSON.stringify(reprovados));
