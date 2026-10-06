#!/usr/bin/env python3
import concurrent.futures, re, socket, urllib.error, urllib.request
from pathlib import Path
from urllib.parse import urlparse

PRODUCTION=Path('plutotv_brasil_v2_categorizada.m3u')
OUTPUT=Path('apxcanais_homologacao.m3u')
REVIEW=Path('apxcanais_revisar.m3u')
REPORT=Path('RELATORIO_HOMOLOGACAO.md')
SOURCES=[
 ('iptv-org Brasil','https://iptv-org.github.io/iptv/countries/br.m3u'),
 ('Free-TV Brasil','https://raw.githubusercontent.com/Free-TV/IPTV/master/playlists/playlist_brazil.m3u8'),
]
TIMEOUT=8; MAX_WORKERS=20; USER_AGENT='APX-Canais-Homologacao/2.1'
TVG_ID_RE=re.compile(r'tvg-id="([^"]*)"'); GROUP_RE=re.compile(r'group-title="([^"]*)"')

BLOCK_TERMS=[
 'agro','agricultura','pecuaria','pecuária','canal do boi','rural',
 'futebol','football','soccer','premiere','sportv','espn','bandsports','basket','basquete','volei','vôlei','tenis','tênis','golf','poker','world poker tour',
 'mma','ufc','boxe','boxing','wrestling','kickboxing','combate',
 'formula 1','fórmula 1','nascar','stock car','autoracing','auto racing','motorsport','motorsports','floracing',
 'relig','gospel','igreja','church','evangel','catolic','católic','biblia','bíblia','crist','jesus','god tv','tbn',
 'partido','parlamento','senado','camara legislativa','câmara legislativa',
 'shopping','shop','telemarket','televendas','vendas',
 'radio','rádio',
 'cultura','arte','artes','museum','museu',
 'anime','boruto',
 'intervention','british screen classics','cbs news 24/7','cnn headlines',
 'gloob','discovery kids','disney junior','hgtv','gnt','arte 1','curta!'
]
MOTO_BIKE_TERMS=['motocross','supercross','enduro','trial','motorcycle','mountain bike','mtb','downhill','bmx','bike','ciclismo','cycling']
REVIEW_TERMS=['24/7','24h','24 h','by a&e','catfish','storage wars']

def fetch(url,limit=None):
    req=urllib.request.Request(url,headers={'User-Agent':USER_AGENT,'Accept':'*/*'})
    with urllib.request.urlopen(req,timeout=TIMEOUT) as r: return r.read(limit) if limit else r.read()

def norm(s): return re.sub(r'\s+',' ',s.lower()).strip()
def clean_name(name):
    x=re.sub(r'\([^)]*\)','',name); x=re.sub(r'\[[^]]*\]','',x)
    x=re.sub(r'[^a-z0-9áàâãéêíóôõúç]+',' ',x.lower()); return ' '.join(x.split())

def parse_m3u(text,source):
    entries=[]; extinf=None; extra=[]
    for raw in text.splitlines():
        line=raw.strip()
        if not line: continue
        if line.startswith('#EXTINF'): extinf=raw; extra=[]; continue
        if extinf and line.startswith('#') and not line.startswith('#EXTINF'): extra.append(raw); continue
        if extinf and line.startswith(('http://','https://')):
            name=extinf.rsplit(',',1)[-1].strip(); tvg=TVG_ID_RE.search(extinf); group=GROUP_RE.search(extinf)
            entries.append({'extinf':extinf,'extra':extra[:],'url':line,'name':name,'name_key':clean_name(name),'tvg_id':tvg.group(1).strip() if tvg else '', 'group':group.group(1).strip() if group else '', 'source':source})
            extinf=None; extra=[]
    return entries

def production_keys(text):
    ids=set(); names=set(); urls=set()
    for e in parse_m3u(text,'produção'):
        if e['tvg_id']: ids.add(e['tvg_id'].lower())
        if e['name_key']: names.add(e['name_key'])
        urls.add(e['url'].split('?',1)[0])
    return ids,names,urls

def classify(e):
    hay=norm(e['name']+' '+e['group']+' '+e['extinf'])
    if any(t in hay for t in MOTO_BIKE_TERMS): return 'keep','moto/bike permitido'
    if any(t in hay for t in BLOCK_TERMS): return 'block','excluído pela curadoria'
    if '[geo-blocked]' in hay: return 'block','geo-blocked'
    if any(t in hay for t in REVIEW_TERMS): return 'review','temático para revisão manual'
    return 'keep','candidato'

def validate_hls(e):
    url=e['url']
    if 'youtube.com/' in url or 'youtu.be/' in url: return False,'YouTube'
    if '.mpd' in url.lower(): return False,'DASH/MPD'
    if (urlparse(url).hostname or '').lower() in {'localhost','127.0.0.1'}: return False,'host local'
    try:
        txt=fetch(url,16384).decode('utf-8',errors='ignore')
        return ('#EXTM3U' in txt[:16384], 'ok' if '#EXTM3U' in txt[:16384] else 'não parece HLS')
    except Exception as ex: return False,type(ex).__name__

def retag(extinf,prefix):
    group=GROUP_RE.search(extinf); current=group.group(1) if group else 'Outros'; new=f'{prefix} - {current}'
    if group: return GROUP_RE.sub(f'group-title="{new}"',extinf)
    comma=extinf.rfind(','); return extinf[:comma]+f' group-title="{new}"'+extinf[comma:] if comma>=0 else extinf

def write_playlist(path,production,entries,prefix):
    out=production.rstrip()+'\n'
    for e in sorted(entries,key=lambda x:(x['group'],x['name'].lower())):
        out+=retag(e['extinf'],prefix)+'\n'
        for x in e['extra']: out+=x+'\n'
        out+=e['url']+'\n'
    path.write_text(out,encoding='utf-8')

def main():
    if not PRODUCTION.exists(): raise SystemExit('Playlist de produção não encontrada.')
    production=PRODUCTION.read_text(encoding='utf-8'); prod_ids,prod_names,prod_urls=production_keys(production)
    candidates=[]; source_counts={}; fetch_errors=[]
    for name,url in SOURCES:
        try:
            parsed=parse_m3u(fetch(url).decode('utf-8',errors='replace'),name); candidates.extend(parsed); source_counts[name]=len(parsed)
        except Exception as ex: source_counts[name]=0; fetch_errors.append(f'{name}: {type(ex).__name__}: {ex}')
    seen_ids,seen_names,seen_urls=set(prod_ids),set(prod_names),set(prod_urls); unique=[]; duplicates=0
    for e in candidates:
        tid=e['tvg_id'].lower() if e['tvg_id'] else ''; nk=e['name_key']; uk=e['url'].split('?',1)[0]
        if (tid and tid in seen_ids) or (nk and nk in seen_names) or uk in seen_urls: duplicates+=1; continue
        if tid: seen_ids.add(tid)
        if nk: seen_names.add(nk)
        seen_urls.add(uk); unique.append(e)
    keep_raw=[]; review_raw=[]; blocked=[]
    for e in unique:
        status,reason=classify(e)
        if status=='block': blocked.append((e,reason))
        elif status=='review': review_raw.append(e)
        else: keep_raw.append(e)
    def validate_many(items):
        good=[]; bad=[]
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            fs={pool.submit(validate_hls,e):e for e in items}
            for f in concurrent.futures.as_completed(fs):
                e=fs[f]; ok,reason=f.result(); good.append(e) if ok else bad.append((e,reason))
        return good,bad
    keep,failed_keep=validate_many(keep_raw); review,failed_review=validate_many(review_raw)
    write_playlist(OUTPUT,production,keep,'Homologação'); write_playlist(REVIEW,production,review,'REVISAR')
    prod_count=len(parse_m3u(production,'produção'))
    report=['# Relatório de Homologação — APX Canais','', '**A playlist oficial não é alterada por esta automação.**','',
      f'- Produção preservada: **{prod_count} canais**',f'- Entradas coletadas: **{len(candidates)}**',f'- Duplicados removidos: **{duplicates}**',
      f'- Excluídos pela curadoria: **{len(blocked)}**',f'- Novos canais aprovados tecnicamente para homologação: **{len(keep)}**',
      f'- Canais temáticos enviados para revisão manual: **{len(review)}**',f'- Links que falharam no teste: **{len(failed_keep)+len(failed_review)}**','',
      '## Regras atuais','- A lista oficial atual é preservada integralmente.','- São consultadas apenas fontes brasileiras/gratuitas nesta etapa.',
      '- Prioridade para conteúdo em português/PT-BR.','- Excluídos: agronegócio, futebol, esportes em geral, lutas, automobilismo de carros, religiosos, políticos/partidários, shopping, rádio, cultura/arte e anime.',
      '- Esporte permitido somente quando claramente ligado a moto, motocross ou bike.','- Canais 24/7 não são excluídos automaticamente; os temáticos ficam na lista REVISAR.',
      '- A automação não promove novos canais diretamente para a produção.','',
      '## Observação sobre idioma','A fonte brasileira aumenta a chance de áudio em português, mas a M3U sozinha não garante dublagem/PT-BR. Canais duvidosos devem ser testados antes da promoção.','',
      '## Fontes']
    for name,_ in SOURCES: report.append(f'- {name}: {source_counts.get(name,0)} entradas')
    if fetch_errors: report += ['', '## Falhas de fonte']+[f'- {x}' for x in fetch_errors]
    REPORT.write_text('\n'.join(report)+'\n',encoding='utf-8')
    print(f'Produção preservada: {prod_count}'); print(f'Homologação: {len(keep)}'); print(f'Revisar: {len(review)}'); print(f'Bloqueados: {len(blocked)}')
if __name__=='__main__': main()
