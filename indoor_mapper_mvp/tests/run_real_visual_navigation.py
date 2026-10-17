import json,urllib.request,time
from pathlib import Path
info=json.load(open('mobile_connection.json',encoding='utf-8'));base=info['urls'][0].split('/?')[0];token=info['urls'][0].split('token=')[1]
def call(path,body=None,raw=False):
 data=body if raw else json.dumps(body).encode() if body is not None else None
 request=urllib.request.Request(base+path+('&' if '?' in path else '?')+'token='+token,data=data,headers={'Content-Type':'image/jpeg' if raw else 'application/json'})
 return json.load(urllib.request.urlopen(request,timeout=40))
project=Path(info['project']);photo=next((project/'queries/20261011_061014_cf4924/images').glob('*.jpg'))
job=call('/api/localize',photo.read_bytes(),True);print('REAL_PHOTO_JOB',job['id'],flush=True)
for _ in range(160):
 state=call('/api/job?id='+job['id'])
 if state['status']=='done':break
 time.sleep(2)
else:raise RuntimeError('Localization timed out')
print('LOCALIZE',state['result']['status'],flush=True)
if state['result']['status']!='success':raise RuntimeError(state['result'].get('reason'))
nav=call('/api/navigation/start',{'job_id':job['id'],'destination':'参考点1'})
print('NAVIGATION',nav['status'],'steps',len(nav['steps']),'historical',nav['historical'],flush=True)
Path('test_artifacts/navigation_live_run.json').write_text(json.dumps({'job_id':job['id'],'result':state['result'],'navigation':nav},ensure_ascii=False,indent=2),encoding='utf-8')
