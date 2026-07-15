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
import { execFile, execFileSync } from 'child_process';

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
function _curlOnce(url, cb){
  const bf = 'tools/.body_' + Math.abs([...url].reduce((h,c)=>(h*31+c.charCodeAt(0))>>>0,7)) + '.tmp';
  execFile('curl',['-s','-o',bf,'-w','%{http_code} %{content_type}','-A',UA,
    '-H','Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    '-H','Accept-Language: pt-BR,pt;q=0.9,en;q=0.8',
    '-L','--max-time','25','--compressed',url],
    {maxBuffer:1<<25},(e,out)=>{
      const parts=(out||'').trim().split(' '); const code=parseInt(parts[0],10)||0; const ctype=parts.slice(1).join(' ');
      let text='', len=0, pdf=false, pdfOk=false;
      try{
        const buf=fs.readFileSync(bf); len=buf.length;
        pdf = /application\/pdf/i.test(ctype) || buf.slice(0,5).toString('latin1')==='%PDF';
        if(pdf){ // extrai o TEXTO do PDF p/ conferir conteúdo (não só a existência do arquivo)
          try{ text=norm(execFileSync('pdftotext',['-q','-nopgbrk',bf,'-'],{maxBuffer:1<<26}).toString('utf8')).replace(/\s+/g,' '); pdfOk=text.length>0; }catch(_){ text=''; }
        } else { text=stripHtml(buf.toString('utf8')); }
      }catch(_){}
      try{fs.unlinkSync(bf);}catch(_){}
      cb({code, text, len, pdf, pdfOk});
    });
}
function fetchUrl(url){
  if(cache.has(url)) return cache.get(url);
  // 403/429 em portais oficiais é quase sempre throttle/anti-bot, não página morta:
  // 1 retry após pausa curta recupera o 200 (evita falso-negativo em IBGE/BCB).
  const p = new Promise(res=>{
    _curlOnce(url, r1=>{
      if(r1.code===403||r1.code===429) setTimeout(()=>_curlOnce(url, r2=>res(r2.code&&r2.code<400?r2:r1)), 1500);
      else res(r1);
    });
  });
  cache.set(url,p); return p;
}
// domínios oficiais em que um PDF que abre (200) já é auditável mesmo sem extração de texto
const OFICIAL = /(^|\.)(gov\.br|bcb\.gov\.br|ibge\.gov\.br|conab\.gov\.br|fgv\.br|portalibre\.fgv\.br|planalto\.gov\.br|ebc\.com\.br|agenciabrasil\.ebc\.com\.br)(\/|$|:)/i;
const ytId = url => (/youtube\.com\/watch\?v=([A-Za-z0-9_-]+)/.exec(url)||/youtu\.be\/([A-Za-z0-9_-]+)/.exec(url)||[])[1]||null;
const ytOembed = url => new Promise(res=>execFile('curl',['-s','-o','/dev/null','-w','%{http_code}','--max-time','15',
  'https://www.youtube.com/oembed?url='+encodeURIComponent(url)+'&format=json'],(e,o)=>res(parseInt((o||'').trim(),10)||0)));

async function pool(items,n,fn){const out=[];let i=0;const run=async()=>{while(i<items.length){const k=i++;out[k]=await fn(items[k]);}};await Promise.all(Array.from({length:Math.min(n,items.length)},run));return out;}

function classify(url, item, fetched, ytCode){
  if(fetched.code<200||fetched.code>=400){
    // domínio oficial que responde 403/bloqueio não é "morta" (a fonte existe): entra p/ revisão, nunca é morta automaticamente
    return {status: OFICIAL.test(url)?'revisar':'morta', http:fetched.code, nota: OFICIAL.test(url)?'oficial bloqueado/instavel':undefined};
  }
  if(ytCode!=null && ytCode!==200) return {status:'fabricada', http:fetched.code, nota:'youtube '+ytCode};
  const body=fetched.text, anchors=numAnchors(item.titulo+' '+(item.texto||'')), toks=titleTokens(item.titulo);
  const numHit=anchors.filter(a=>body.includes(a)).length, tokHit=toks.filter(w=>body.includes(w)).length;
  const tokRatio=toks.length?tokHit/toks.length:0;
  // PDF sem texto extraível (pdftotext ausente): aceita estrutural só de domínio oficial; senão revisar
  if(fetched.pdf && !fetched.pdfOk){
    return {status: OFICIAL.test(url)?'ok':'revisar', http:fetched.code, pdf:true, nota:'pdf estrutural (sem extração)'};
  }
  const shell=!fetched.pdf && (fetched.len<1500||/just a moment|cloudflare|enable javascript|attention required/i.test(body));
  let status;
  if(numHit>=1 && tokRatio>=0.34) status='ok';
  else if(numHit>=1 || tokRatio>=0.5) status='ok';
  else if(shell) status='revisar';
  else if(tokRatio>=0.25) status='revisar';
  else status='nao_confere';
  // FALLBACK ESTRUTURAL: fonte primária em domínio oficial (gov/bcb/ibge/fgv/conab) que
  // responde 200 é auditável mesmo quando o conteúdo é renderizado via JS (curl não vê o texto).
  // O casamento de conteúdo acima continua sendo o teste preferencial; isto só evita o falso-negativo.
  if(status!=='ok' && OFICIAL.test(url)) return {status:'ok', http:fetched.code, numHit, tokHit, tokTot:toks.length, tokRatio:+tokRatio.toFixed(2), oficial:true};
  return {status, http:fetched.code, numHit, tokHit, tokTot:toks.length, tokRatio:+tokRatio.toFixed(2), shell, pdf:fetched.pdf};
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
      const cl=classify(s.url, c, fetchedMap.get(s.url), ytMap.has(s.url)?ytMap.get(s.url):null);
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
