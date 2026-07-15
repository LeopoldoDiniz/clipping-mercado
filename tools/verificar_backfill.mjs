/**
 * VERIFICADOR DE BACKFILL (as-of) — companheiro do verificar_grounding.mjs.
 * Para reconstruir semanas históricas: além de conteúdo, confere a DATA DE PUBLICAÇÃO
 * e calcula a semana ISO real do item — barra anacronismo (dado "de janeiro" publicado em março).
 *
 * Uso:
 *   node tools/verificar_backfill.mjs tools/_cands.json
 * Entrada: JSON array de candidatos { setores:[], titulo, texto, url, need?:[] }.
 * Saída: tools/backfill_report.json + resumo. Cada item recebe pubDate, isoWeek, contentOk, verdict.
 *  - verdict 'ok'  → conteúdo confere (ou PDF/fonte oficial 200) E tem data de publicação.
 *  - 'sem_data'    → não deu p/ extrair data (decidir manualmente pela release conhecida).
 *  - 'conteudo'    → 200 mas conteúdo não confere.
 *  - 'morta'       → HTTP falhou.
 * O item é atribuído à semana isoWeek — quem monta decide se bate com a janela desejada.
 */
import { execFile, execFileSync } from 'child_process';
import fs from 'fs';

const UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36';
const norm=s=>(s||'').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g,'');
const strip=h=>norm(String(h).replace(/<script[\s\S]*?<\/script>/gi,' ').replace(/<style[\s\S]*?<\/style>/gi,' ').replace(/<[^>]+>/g,' ')).replace(/\s+/g,' ');
const OFICIAL=/(^|\.)(gov\.br|bcb\.gov\.br|ibge\.gov\.br|conab\.gov\.br|fgv\.br|portalibre\.fgv\.br|planalto\.gov\.br)(\/|$|:)/i;

function numAnchors(txt){const t=txt||'',out=new Set();
  const push=re=>{let m;const r=new RegExp(re,'gi');while((m=r.exec(t)))out.add(norm(m[0]).replace(/\s+/g,''));};
  push('\\d{1,3}(?:\\.\\d{3})*,\\d+\\s*%?');push('\\d+\\s*%');push('r\\$\\s*\\d[\\d.,]*');push('us\\$\\s*\\d[\\d.,]*');
  return [...out].map(a=>a.replace(/^(r|us)\$/,'').replace(/%$/,'')).filter(a=>/\d,\d|\d{2,}/.test(a));}
const STOP=new Set('de da do das dos e em no na nos nas o a os as para por com que um uma ao se sua seu mais sobre entre ser ter ja ate como mas ou fica vai bate maior menor ano anos mes dezembro janeiro fevereiro marco abril maio junho julho agosto setembro outubro novembro'.split(' '));
const titleTokens=t=>[...new Set(norm(t).replace(/[^a-z0-9 ]/g,' ').split(/\s+/).filter(w=>w.length>=4&&!STOP.has(w)))];

function pubDate(html,url){
  const H=String(html);
  let m=/"datePublished"\s*:\s*"(\d{4}-\d{2}-\d{2})/i.exec(H)||
        /property=["']article:published_time["']\s+content=["'](\d{4}-\d{2}-\d{2})/i.exec(H)||
        /name=["'](date|pubdate|publishdate)["']\s+content=["'](\d{4}-\d{2}-\d{2})/i.exec(H)||
        /itemprop=["']datePublished["'][^>]*content=["'](\d{4}-\d{2}-\d{2})/i.exec(H);
  if(m) return m[m.length-1];
  m=/publicad[oa]\s+em[:\s]+(\d{2})\/(\d{2})\/(\d{4})/i.exec(H); if(m) return `${m[3]}-${m[2]}-${m[1]}`;
  m=/\/(20\d\d)[-\/](\d{2})[-\/](\d{2})(\/|$|-)/.exec(url); if(m) return `${m[1]}-${m[2]}-${m[3]}`;
  m=/R(20\d\d)(\d{2})(\d{2})\.pdf/i.exec(url); if(m) return `${m[1]}-${m[2]}-${m[3]}`;
  return null; // mês-na-URL não basta p/ semana; melhor null e decidir manual
}
function isoWeek(dateStr){
  if(!dateStr) return null;
  const [y,mo,d]=dateStr.split('-').map(Number);
  const dt=new Date(Date.UTC(y,mo-1,d));
  const day=(dt.getUTCDay()+6)%7; dt.setUTCDate(dt.getUTCDate()-day+3);
  const year=dt.getUTCFullYear();
  const firstThu=new Date(Date.UTC(year,0,4)); const fd=(firstThu.getUTCDay()+6)%7; firstThu.setUTCDate(firstThu.getUTCDate()-fd+3);
  return {year, week: 1+Math.round((dt-firstThu)/(7*864e5))};
}
function fetchUrl(url){return new Promise(res=>{const bf='tools/.bf_'+Math.abs([...url].reduce((h,c)=>(h*31+c.charCodeAt(0))>>>0,7))+'.tmp';
  execFile('curl',['-s','-o',bf,'-w','%{http_code} %{content_type}','-A',UA,'-L','--max-time','25','--compressed',url],{maxBuffer:1<<25},(e,out)=>{
    const parts=(out||'').trim().split(' ');const code=parseInt(parts[0],10)||0;const ct=parts.slice(1).join(' ');
    let raw='',text='',pdf=false,pdfOk=false;
    try{const buf=fs.readFileSync(bf);raw=buf.toString('latin1');pdf=/application\/pdf/i.test(ct)||buf.slice(0,5).toString('latin1')==='%PDF';
      if(pdf){try{text=norm(execFileSync('pdftotext',['-q','-nopgbrk',bf,'-'],{maxBuffer:1<<26}).toString('utf8')).replace(/\s+/g,' ');pdfOk=text.length>0;}catch(_){}}
      else text=strip(raw);}catch(_){}
    try{fs.unlinkSync(bf);}catch(_){}
    res({code,ct,raw,text,pdf,pdfOk});});});}
async function pool(items,n,fn){const out=[];let i=0;const run=async()=>{while(i<items.length){const k=i++;out[k]=await fn(items[k],k);}};await Promise.all(Array.from({length:Math.min(n,items.length)},run));return out;}

const inPath=process.argv[2]||'tools/_cands.json';
const cands=JSON.parse(fs.readFileSync(inPath,'utf8'));
const out=await pool(cands,8,async c=>{
  const f=await fetchUrl(c.url);
  const extracted=pubDate(c.pdf?'':f.raw, c.url);
  const date=extracted || c.date || null; // fallback: data informada na descoberta (o agente já checou)
  const dateSrc=extracted?'extraída':(c.date?'informada':'—');
  const iw=isoWeek(date);
  let contentOk, why;
  if(f.code<200||f.code>=400){contentOk=false;why='morta http='+f.code;}
  else if(f.pdf){contentOk = f.pdfOk ? (c.need||[]).every(t=>f.text.includes(norm(t))) : OFICIAL.test(c.url); why=f.pdfOk?'pdf-texto':'pdf-estrutural';}
  else if(OFICIAL.test(c.url)){contentOk=true; why='oficial-200';} // fonte primária no domínio oficial
  else { const anchors=numAnchors(c.titulo+' '+(c.texto||'')),toks=titleTokens(c.titulo);
    const nh=anchors.filter(a=>f.text.includes(a)).length, tr=toks.length?toks.filter(w=>f.text.includes(w)).length/toks.length:0;
    contentOk = (c.need&&c.need.length? c.need.filter(t=>f.text.includes(norm(t))).length>=1 : (nh>=1||tr>=0.4)); why='match nh='+nh+' tr='+tr.toFixed(2);}
  const verdict = !contentOk ? (f.code>=200&&f.code<400?'conteudo':'morta') : (date?'ok':'sem_data');
  return {setores:c.setores, titulo:c.titulo, texto:c.texto, url:c.url, nome:c.nome, code:f.code, pubDate:date, dateSrc, iso:iw?`${iw.year}-W${iw.week}`:null, verdict, why};
});
fs.writeFileSync('tools/backfill_report.json', JSON.stringify(out,null,2));
for(const r of out) console.log(String(r.verdict).padEnd(9)+' '+String(r.iso||'sem-data').padEnd(9)+' pub='+String(r.pubDate||'?').padEnd(11)+' '+r.why.padEnd(16)+' '+String(r.titulo).slice(0,42));
const byV=out.reduce((a,r)=>{a[r.verdict]=(a[r.verdict]||0)+1;return a;},{});
console.log('\n'+JSON.stringify(byV)+'  | report: tools/backfill_report.json');
