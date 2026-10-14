#!/usr/bin/env python3
"""Run Galileo's four-panel comic flow against the live vLLM and SillyTavern stack."""
import base64, collections, datetime, html, json, os, random, struct, sys, time
import http.cookiejar, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIGHT_DIR = os.path.join(os.environ.get('BRIGHT_COMPOSER_DIR', os.path.join(ROOT, 'bright_composer')), 'bright')
SETTINGS = os.path.join(ROOT, 'sillytavern/data/default-user/settings.json')
CARD = os.path.join(ROOT, 'sillytavern/data/default-user/characters/Galileo.png')
ST_BASE = 'http://127.0.0.1:8010'
VLLM = 'http://127.0.0.1:8001/v1/chat/completions'
PERSONAS = [
    ('bimba', '12 anni', 'astronomia', 'un piccolo telescopio', 'il tetto dell\'Universita di notte', 'una nube temporalesca', 'una mappa stellare perduta'),
    ('ragazzo', '16 anni', 'robotica', 'un braccio robotico portatile', 'il Centro Piaggio', 'un automa fuori controllo', 'il progetto del primo robot pisano'),
    ('ragazza', '17 anni', 'biologia marina', 'una lente d\'ingrandimento', 'la costa di Marina di Pisa', 'la marea in arrivo', 'un organismo mai catalogato'),
    ('adulto', '35 anni', 'storia dell\'arte', 'un taccuino da disegno', 'una sala del museo di San Matteo', 'un quadro scomparso', 'un bozzetto attribuito a un maestro perduto'),
    ('bimbo', '10 anni', 'fisica', 'un pendolo', 'la Torre Pendente', 'un terremoto improvviso', 'la prova di una legge del moto'),
    ('ragazza', '14 anni', 'informatica', 'un vecchio computer Olivetti', 'il museo degli strumenti di calcolo', 'un programma misterioso', 'un messaggio dal passato'),
    ('ragazzo', '15 anni', 'archeologia', 'un pennello da scavo', 'gli scavi sotto il Duomo', 'un passaggio che crolla', 'una tavoletta scientifica romana'),
    ('adulta', '42 anni', 'medicina', 'uno stetoscopio', 'un laboratorio universitario', 'un esperimento da fermare', 'una cura rivoluzionaria'),
    ('bimba', '11 anni', 'geologia', 'una bussola luminosa', 'le colline pisane', 'una frana imminente', 'un cristallo con una storia antichissima'),
    ('adulto', '29 anni', 'letteratura', 'una penna stilografica', 'la biblioteca antica', 'un manoscritto cifrato', 'la pagina finale di un libro perduto'),
]
TOOLS = [{"type":"function", "function": {"name":"GenerateImage", "description":"Generate a four-panel comic from a story. Include shared story state and exactly four distinct consecutive scene prompts.", "parameters": {"type":"object", "properties": {"story": {"type":"object", "properties": {"gender":{"type":"string","default":"unspecified"},"age":{"type":"string","default":"adult"},"subject":{"type":"string","default":"curious researcher"},"tool":{"type":"string","default":"a simple notebook"},"location":{"type":"string","default":"an Italian university setting at night"},"danger":{"type":"string","default":"a mysterious obstacle"},"treasure":{"type":"string","default":"a meaningful discovery"}}}, "panels": {"type":"array", "minItems":4, "maxItems":4, "items": {"type":"object", "properties": {"number":{"type":"integer"}, "prompt":{"type":"string"}}, "required":["number","prompt"]}}}, "required":["panels"]}}}]
_cj = http.cookiejar.CookieJar(); _op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cj)); _token = None

def st_post(path, body, timeout=900):
    global _token
    if _token is None: _token = json.load(_op.open(ST_BASE + '/csrf-token'))['token']
    req = urllib.request.Request(ST_BASE + path, data=json.dumps(body).encode(), method='POST', headers={'Content-Type':'application/json','X-CSRF-Token':_token})
    try:
        r = _op.open(req, timeout=timeout); return r.status, r.read()
    except urllib.error.HTTPError as e: return e.code, e.read()

def read_card():
    d=open(CARD,'rb').read(); i=8
    while i<len(d):
        n=struct.unpack('>I',d[i:i+4])[0]; b=d[i+8:i+8+n]
        if d[i+4:i+8]==b'tEXt' and b.split(b'\0',1)[0]==b'chara': return json.loads(base64.b64decode(b.split(b'\0',1)[1])).get('data')
        i += 12+n
    raise RuntimeError('no chara chunk')

def ask(card, o, answers):
    a=answers
    msgs=[{'role':'system','content':card['system_prompt']+'\n\n'+card['description']+'\n\n'+card['scenario']},{'role':'assistant','content':card['first_mes']},
      {'role':'user','content':a[0]}, {'role':'assistant','content':'"Bene. Ora so come raffigurarvi. Quale campo del sapere vi appassiona, e quale obiettivo vorreste raggiungere?"'},
      {'role':'user','content':a[1]}, {'role':'assistant','content':'"Scelta degna. Quale oggetto o strumento speciale portereste con voi?"'},
      {'role':'user','content':a[2]}, {'role':'assistant','content':'"Lo strumento e pronto. Dove si svolgera l\'avventura, quale pericolo affronteremo, e quale tesoro cercheremo?"'},
      {'role':'user','content':a[3]}]
    body={'model':o['custom_model'],'messages':msgs,'tools':TOOLS,'tool_choice':{'type':'function','function':{'name':'GenerateImage'}},'max_tokens':o['openai_max_tokens'],'temperature':min(float(o['temp_openai']),0.2),'top_p':1,'frequency_penalty':0,'presence_penalty':0,'stream':False,'chat_template_kwargs':{'enable_thinking':False}}
    req=urllib.request.Request(VLLM,data=json.dumps(body).encode(),method='POST',headers={'Content-Type':'application/json'})
    data=json.load(urllib.request.urlopen(req,timeout=900)); choice=data['choices'][0]; msg=choice.get('message',{})
    calls=msg.get('tool_calls') or []; raw=calls[0]['function']['arguments'] if calls else ''
    if not calls: raise RuntimeError('no tool call: ' + msg.get('content','')[-1000:])
    return msg.get('content',''), json.loads(raw)

def render(sd, prompt, seed):
    wf=open(os.path.join(ROOT,'sillytavern/data/default-user/user/workflows',sd['comfy_workflow'])).read()
    for key,val in [('prompt',prompt),('negative_prompt',sd.get('negative_prompt','')),('seed',seed),('denoise',sd.get('denoising_strength',1.0)),('clip_skip',-sd.get('clip_skip',1))]: wf=wf.replace('"%%%s%%"'%key,json.dumps(val)).replace('"%%%s%%"'%key,json.dumps(val))
    for ph in ('model','vae','sampler','scheduler','steps','scale','width','height'): wf=wf.replace('"%%%s%%"'%ph,json.dumps(sd.get(ph)))
    code,body=st_post('/api/sd/comfy/generate',{'url':sd['comfy_url'],'prompt':'{\n "prompt": '+json.dumps(json.loads(wf))+'\n}'})
    if code!=200: raise RuntimeError(body.decode()[:400])
    data=json.loads(body); return base64.b64decode(data['data'])

def main():
    count=int(sys.argv[1]) if len(sys.argv)>1 else 20
    s=json.load(open(SETTINGS)); o=s['oai_settings']; sd=s['extension_settings']['sd']; card=read_card(); stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S'); out=os.path.join(ROOT,'batches',f'galileo-panels-{stamp}'); os.makedirs(os.path.join(out,'images')); os.makedirs(BRIGHT_DIR, exist_ok=True)
    rows=[]; started=time.time()
    for n in range(count):
        persona=PERSONAS[n%len(PERSONAS)]; gender,age,field,tool,place,danger,treasure=persona; tag=f'{n+1:02d}'; t=time.time(); answers=[f'{gender}, {age}',f'{field}; voglio comprendere un fenomeno e dimostrarlo con rigore',tool,f'{place}; dovremo affrontare {danger}; cercheremo {treasure}']
        try:
            narration,payload=ask(card,o,answers)
            panels=payload.get('panels',[]) if payload else []
            if len(panels)!=4 or any(not isinstance(x.get('prompt'),str) or not x['prompt'].strip() for x in panels): raise RuntimeError(f'invalid panel payload: {json.dumps(payload,ensure_ascii=False)[:500]}')
            prompts=[x['prompt'].strip() for x in panels]
            if len({x.lower() for x in prompts})!=4: raise RuntimeError('duplicate panel prompts')
            files=[]; bright_stage=os.path.join(BRIGHT_DIR, f'{stamp}-{tag}.staging'); bright_batch=os.path.join(BRIGHT_DIR, f'{stamp}-{tag}'); os.makedirs(bright_stage)
            for pidx,prompt in enumerate(prompts,1):
                full=(sd.get('prompt_prefix','').replace('{prompt}',prompt) if '{prompt}' in sd.get('prompt_prefix','') else sd.get('prompt_prefix','')+', '+prompt).strip(', ')
                data=render(sd,full,random.randrange(2**53-1)); fn=f'images/{tag}-panel-{pidx}.png'; open(os.path.join(out,fn),'wb').write(data); open(os.path.join(bright_stage, f'{pidx}.png'),'wb').write(data); files.append(fn)
            os.replace(bright_stage, bright_batch)
            rows.append({'number':tag,'answers':answers,'status':'ok','files':files,'panels':prompts,'narration':narration}); print(f'{tag} OK 4 panels {time.time()-t:.0f}s',flush=True)
        except Exception as e:
            rows.append({'number':tag,'answers':answers,'status':'fail','error':str(e),'narration':locals().get('narration','')}); print(f'{tag} FAIL {e}',flush=True)
    json.dump({'stamp':stamp,'profile':sd,'rows':rows},open(os.path.join(out,'manifest.json'),'w'),indent=2,ensure_ascii=False)
    cards=[]
    for r in rows:
        imgs=''.join(f'<a href="{html.escape(x)}"><img src="{html.escape(x)}" loading="lazy"></a>' for x in r.get('files',[])) if r['status']=='ok' else f'<pre>{html.escape(r.get("error",""))}</pre>'
        cards.append(f'<article><h2>Story {r["number"]} — {r["status"]}</h2><div class="panels">{imgs}</div><p>{html.escape(" | ".join(r["answers"]))}</p><details><summary>prompts</summary><pre>{html.escape("\\n\\n".join(r.get("panels",[])))}</pre></details><details><summary>narration</summary><pre>{html.escape(r.get("narration", ""))}</pre></details></article>')
    doc=('<!doctype html><meta charset=\"utf-8\"><title>Galileo panel test</title><style>body{font:14px system-ui;margin:24px;background:#eee}article{background:white;margin:0 0 24px;padding:16px;border-radius:10px}.panels{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.panels img{width:100%;display:block}pre{white-space:pre-wrap}p{color:#555}</style><h1>Galileo four-panel test</h1><p>' + str(sum(r['status']=='ok' for r in rows)) + '/' + str(count) + ' stories completed in ' + f'{(time.time()-started)/60:.1f}' + ' minutes.</p>' + ''.join(cards))
    open(os.path.join(out,'index.html'),'w').write(doc); print(f'REVIEW {os.path.join(out,"index.html")}',flush=True)
if __name__=='__main__': main()
