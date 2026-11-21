import os, json, re, sys, hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode, urlparse
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

PARIS = ZoneInfo('Europe/Paris')
NOW = datetime.now(PARIS)
FILE = Path('state.json')
STATE = json.loads(FILE.read_text()) if FILE.exists() else {}
ESPN = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard'

def fetch(url):
    with urlopen(Request(url, headers={'User-Agent':'Discord-NFL-Alerts/1.0'}), timeout=25) as r:
        return r.read()

def post(channel, message, name):
    url = os.environ.get(channel, '')
    if not url:
        raise RuntimeError('Secret manquant : ' + channel)
    if urlparse(url).hostname not in ('discord.com', 'discordapp.com') or not url.startswith('https://'):
        raise ValueError('Webhook Discord invalide')
    for part in chunks(message):
        req = Request(url, data=json.dumps({'content':part, 'username':name, 'allowed_mentions':{'parse':[]}}).encode(), headers={'Content-Type':'application/json','User-Agent':'Discord-NFL-Alerts/1.0'}, method='POST')
        with urlopen(req, timeout=20) as response:
            response.read()

def chunks(message):
    part = ''
    for line in message.splitlines():
        if len(part)+len(line)+1 > 1900 and part:
            yield part
            part = ''
        part += line[:1850]+'\n'
    if part: yield part

def send_once(key, value, channel, text, name):
    if STATE.get(key) != value:
        post(channel,text,name)
        STATE[key] = value
        FILE.write_text(json.dumps(STATE,ensure_ascii=False,indent=2))

def games(start,end):
    data = json.loads(fetch(ESPN+'?'+urlencode({'dates':start.strftime('%Y%m%d')+'-'+end.strftime('%Y%m%d'),'limit':100})))
    return sorted(data.get('events',[]), key=lambda g:g['date'])

def game_info(g):
    c = g['competitions'][0]
    date = datetime.fromisoformat(g['date'].replace('Z','+00:00')).astimezone(PARIS)
    teams = sorted(c['competitors'],key=lambda t:t['homeAway']=='home')
    match = ' – '.join(t['team']['displayName'] for t in teams)
    score = ' – '.join(str(t.get('score','0')) for t in teams)
    status = c.get('status',g.get('status',{})).get('type',{})
    return date,match,score,status

def nfl():
    # Du jeudi au mercredi suivant, en heure de Paris.
    anchor = NOW.date()-timedelta(days=(NOW.weekday()-3)%7)
    current = games(anchor,anchor+timedelta(days=6))
    if NOW.weekday()==3 and current:
        lines = ['🏈 **Programme NFL — heure de Paris**']
        for g in current:
            date, match, _, _ = game_info(g)
            lines.append(f'{date:%d/%m %H:%M} — {match} • NFL Game Pass (DAZN)')
        lines += ['Chaînes françaises détaillées à vérifier : https://www.beinsports.com/fr-fr/guide-tv','Match gratuit : https://www.lequipe.fr/tv/','Tous les matchs : https://www.dazn.com/fr-FR/welcome/nfl']
        send_once('programme:'+str(anchor),True,'NFL_WEBHOOK','\n'.join(lines),'NFL Live')
    # Inclut les rencontres de la veille, y compris les matchs nocturnes.
    for g in games(NOW.date()-timedelta(days=1),NOW.date()+timedelta(days=1)):
        date,match,score,status = game_info(g)
        state=status.get('state'); key='match:'+g['id']
        previous=STATE.get(key,'')
        minutes=(date-NOW).total_seconds()/60
        if state=='pre' and 0 <= minutes <= 25:
            send_once(key,'reminder','NFL_WEBHOOK',f'⏰ **{match}** débute à {date:%H:%M} • DAZN Game Pass. Chaîne TV française à vérifier.','NFL Live')
        elif state=='in':
            send_once(key,'live:'+score,'NFL_WEBHOOK',f'🔴 **{match}** : {score} • {status.get("detail", "En cours")}','NFL Live')
        elif status.get('completed') and not str(previous).startswith('final:') and date > NOW-timedelta(hours=18):
            send_once(key,'final:'+score,'NFL_WEBHOOK',f'🏁 **{match}** : {score} (terminé)','NFL Live')
    if NOW.weekday()==1:
        week=str(NOW.date())
        if STATE.get('classement')==week: return
        data=json.loads(fetch('https://site.api.espn.com/apis/v2/sports/football/nfl/standings?'+urlencode({'season':NOW.year if NOW.month>=8 else NOW.year-1})))
        lines=['📊 **Classements NFL**']
        def walk(node):
            if node.get('standings',{}).get('entries'):
                lines.append('**'+node.get('name','Division')+'**')
                for entry in node['standings']['entries']:
                    stats={s['name']:s.get('displayValue','?') for s in entry['stats']}
                    lines.append(f"{entry['team']['displayName']} — {stats.get('wins','?')}-{stats.get('losses','?')}-{stats.get('ties','0')}")
            for child in node.get('children',[]): walk(child)
        walk(data)
        if len(lines)>1: send_once('classement',week,'NFL_WEBHOOK','\n'.join(lines),'NFL Live')

def offers():
    # Veille de presse publique : alertes à vérifier, pas des offres certifiées.
    for provider in ('Prime Video','Disney+','Netflix','DAZN','NFL Game Pass','Apple TV+','Paramount+','Max','Canal+'):
        query=f'"{provider}" ("essai gratuit" OR "mois offert" OR "jours gratuits") France when:7d'
        url='https://news.google.com/rss/search?'+urlencode({'q':query,'hl':'fr','gl':'FR','ceid':'FR:fr'})
        root=ET.fromstring(fetch(url))
        for item in root.findall('./channel/item')[:5]:
            title=item.findtext('title',''); link=item.findtext('link','')
            if not re.search(r'gratuit|offert',title,re.I) or not link.startswith('https://'): continue
            if not re.search(r'essai|jour|mois|offert|semaine',title,re.I): continue
            key='offre:'+hashlib.sha256(title.casefold().encode()).hexdigest()[:24]
            send_once(key,True,'OFFERS_WEBHOOK',f'🎁 **{provider} — piste à vérifier**\n{title}\n{link}\nVérifie les conditions, la date limite et le renouvellement automatique auprès du fournisseur. Offre non confirmée.','Bons plans streaming')

if __name__=='__main__':
    {'nfl':nfl,'offers':offers}[sys.argv[1]]()
