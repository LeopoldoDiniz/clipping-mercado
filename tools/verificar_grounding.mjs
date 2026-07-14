/**
 * VERIFICADOR DE GROUNDING — a "regra pétrea" do Nexosim.
 * Uma notícia só é REAL se o CONTEÚDO da fonte (não só o status HTTP) confirmar o fato.
 *
 * Uso (a partir da raiz do projeto):
 *   node tools/verificar_grounding.mjs                 # verifica todas as semanas com clipping
 *   node tools/verificar_grounding.mjs W28 W29         # só as semanas indicadas
 *   node tools/verificar_grounding.mjs --apply         # marca ok:false nas fontes inequivocamente mortas/fabricadas
 *
 * Sem --apply, só gera relatório (tools/verif_report.json) e resumo no console. NUNCA mata
 * automaticamente fontes 'nao_confere'/'revisar' (risco de falso-negativo por bloqueio/JS-shell):
 * essas entram na worklist para adjudicação por busca real (agente/humano). Ver tools/README.md.
 */
import fs from 'fs';
import { execFile } from 'child_process';

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36';
const argv = process.argv.slice(2);
const APPLY = argv.includes('--apply');
const wkArgs = argv.filter(a => /^W\d+$/.test(a));

const norm = s => (s||'').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g,'');
const stripHtml = html => norm(String(html)
  .replace(/<script[\s\S]*?<\/script>/gi,' ').replace(/<style[\s\S]*?<\/style>/gi,' ')
  .replace(/<[^>]+>/g,' ').replace(/&nbsp;/g,' ').replace(/&[a-z]+;/gi,' ')).replace(/\s+/g,' ');

const STOP = new Set(('de da do das dos e em no na nos nas o a os as para por com que um uma ao se sua seu seus suas mais sobre entre ser ter ja ate como mas ou the in of and to for numero mes ano anos dia dias apos ante sem pelo pela novo nova ' +
  'janeiro fevereiro marco abril maio junho julho agosto setembro outubro novembro dezembro').split(/\s+/));

function numAnchors(txt){
  const t = txt||''; const out = new Set();
  const push = re => { let m; const r = new RegExp(re,'gi'); while((m=r.exec(t))) out.add(norm(m[0]).replace(/\s+/g,'')); };
  push('\\d{1,3}(?:\\.\\d{3})*,\\d+\\s*%?'); push('\\d+\\s*%'); push('r\\$\\s*\\d[\\d.,]*');
  return [...out].map(a=>a.replace(/^r\$/,'').replace(/%$/,'')).filter(a=>/\d,\d|\d{2,}/.test(a));
}
const titleTokens = t => [...new Set(norm(t).replace(/[^a-z0-9 ]/g,' ').split(/\s+/).filter(w=>w.length>=4&&!STOP.has(w)))];

const cache = new Map();
function fetchUrl(url){
  if(cache.has(url)) return cache.get(url);
  const p = new Promise(res=>{
    const bf = 'tools/.body_' + Math.abs([...url].reduce((h,c)=>(h*31+c.charCodeAt(0))>>>0,7)) + '.tmp';
    execFile('curl',['-s','-o',bf,'-w','%{http_code}','-A',UA,'-L','--max-time','22','--compressed',url],
      {maxBuffer:1<<24},(e,out)=>{ const code=parseInt((out||'').trim(),10)||0; let body='';
        try{body=fs.readFileSync(bf,'utf8');}catch(_){} try{fs.unlinkSync(bf);}catch(_){}
        res({code, text:stripHtml(body), len:body.length}); });
  });
  cache.set(url,p); return p;
}
const ytId = url => (/youtube\.com\/watch\?v=([A-Za-z0-9_-]+)/.exec(url)||/youtu\.be\/([A-Za-z0-9_-]+)/.exec(url)||[])[1]||null;
const ytOembed = url => new Promise(res=>execFile('curl',['-s','-o','/dev/null','-w','%{http_code}','--max-time','15',
  'https://www.youtube.com/oembed?url='+encodeURIComponent(url)+'&format=json'],(e,o)=>res(parseInt((o||'').trim(),10)||0)));

async function pool(items,n,fn){const out=[];let i=0;const run=async()=>{while(i<items.length){const k=i++;out[k]=await fn(items[k]);}};await Promise.all(Array.from({length:Math.min(n,items.length)},run));return out;}

function classify(item, fetched, ytCode){
  if(fetched.code<200||fetched.code>=400) return {status:'morta', http:fetched.code};
  if(ytCode!=null && ytCode!==200) return {status:'fabricada', http:fetched.code, nota:'youtube '+ytCode};
  const body=fetched.text, anchors=numAnchors(item.titulo+' '+(item.texto||'')), toks=titleTokens(item.titulo);
  const numHit=anchors.filter(a=>body.includes(a)).length, tokHit=toks.filter(w=>body.includes(w)).length;
  const tokRatio=toks.length?tokHit/toks.length:0;
  const shell=fetched.len<1500||/just a moment|cloudflare|enable javascript|attention required/i.test(body);
  let status;
  if(numHit>=1 && tokRatio>=0.34) status='ok';
  else if(numHit>=1 || tokRatio>=0.5) status='ok';
  else if(shell) status='revisar';
  else if(tokRatio>=0.25) status='revisar';
  else status='nao_confere';
  return {status, http:fetched.code, numHit, tokHit, tokTot:toks.length, tokRatio:+tokRatio.toFixed(2), shell};
}
const ARTE = /\[cite:|in previous search|\{\{|lorem ipsum|placeholder/i;

async function verifyWeek(wk){
  const fp='data/2026-'+wk+'.json';
  const d=JSON.parse(fs.readFileSync(fp,'utf8'));
  const items=d.clipping||[];
  const urls=[...new Set(items.flatMap(c=>(c.fontes||[]).map(f=>f.url).filter(Boolean)))];
  const fetchedMap=new Map(); await pool(urls,8,async u=>fetchedMap.set(u,await fetchUrl(u)));
  const ytMap=new Map(); await pool(urls.filter(ytId),6,async u=>ytMap.set(u,await ytOembed(u)));
  let touched=false;
  const rep=items.map((c,idx)=>{
    const srcs=(c.fontes||[]).map(s=>{
      if(!s.url) return {nome:s.nome, url:null, status:'sem_url'};
      const cl=classify(c, fetchedMap.get(s.url), ytMap.has(s.url)?ytMap.get(s.url):null);
      if(APPLY && (cl.status==='morta'||cl.status==='fabricada') && s.ok!==false){ s.ok=false; touched=true; }
      return {nome:s.nome, url:s.url, okFlag:s.ok, ...cl};
    });
    const temOk=srcs.some(s=>s.status==='ok'), temRev=srcs.some(s=>s.status==='revisar');
    return {i:idx, titulo:c.titulo, itemStatus: temOk?'verificado':temRev?'revisar':'sem_fonte_confiavel',
      arte:ARTE.test(c.titulo+' '+(c.texto||'')), srcs};
  });
  if(APPLY && touched) fs.writeFileSync(fp, JSON.stringify(d,null,2),'utf8');
  const sum={verificado:0,revisar:0,sem_fonte_confiavel:0,artefatos:0};
  rep.forEach(r=>{sum[r.itemStatus]++; if(r.arte)sum.artefatos++;});
  return {wk, total:items.length, sum, itens:rep};
}

const weeks = wkArgs.length ? wkArgs
  : fs.readdirSync('data').filter(f=>/^2026-W\d+\.json$/.test(f))
      .filter(f=>(JSON.parse(fs.readFileSync('data/'+f,'utf8')).clipping||[]).length>0)
      .map(f=>f.match(/W\d+/)[0]);

const all=[];
for(const wk of weeks){ process.stderr.write('verificando '+wk+'...\n'); all.push(await verifyWeek(wk)); }
fs.writeFileSync('tools/verif_report.json', JSON.stringify({weeks:all},null,2),'utf8');
console.log('\n=== RESUMO DE VERIFICAÇÃO'+(APPLY?' (com --apply)':'')+' ===');
for(const w of all) console.log(`${w.wk}: ${w.total} itens | verificado=${w.sum.verificado} revisar=${w.sum.revisar} SEM_FONTE=${w.sum.sem_fonte_confiavel} artefatos=${w.sum.artefatos}`);
const tot=all.reduce((a,w)=>{for(const k in w.sum)a[k]=(a[k]||0)+w.sum[k];a.total+=w.total;return a;},{total:0});
console.log(`TOTAL: ${tot.total} itens | verificado=${tot.verificado} revisar=${tot.revisar} SEM_FONTE=${tot.sem_fonte_confiavel} artefatos=${tot.artefatos}`);
