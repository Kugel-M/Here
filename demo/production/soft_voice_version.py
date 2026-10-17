"""Generate a local neural-voice edition, preserving the original delivery."""
from pathlib import Path
import json, shutil, subprocess, tempfile
import numpy as np
import soundfile as sf
import onnxruntime as rt
from kokoro_onnx import Kokoro

OLD=Path(__file__).resolve().parents[1]
WORK=OLD.parents[1]
NEW=WORK/'output/Indoor_Navigation_Demo_EN_SoftVoice_20261017'
(WORK/'tmp/voice_temp').mkdir(parents=True,exist_ok=True)
tempfile.tempdir=str(WORK/'tmp/voice_temp')
rt.set_default_logger_severity(3)
for sub in ['source','captures','audio','qa']:(NEW/sub).mkdir(parents=True,exist_ok=True)
for file in (OLD/'captures').iterdir():
    if file.is_file():shutil.copy2(file,NEW/'captures'/file.name)
for name in ['render_demo.py','scenes.json']:
    shutil.copy2(OLD/'source'/name,NEW/'source'/name)
scenes=json.loads((NEW/'source/scenes.json').read_text(encoding='utf-8-sig'))
kokoro=Kokoro(str(WORK/'tmp/kokoro_models/kokoro-v1.0.fp16.onnx'),str(WORK/'tmp/kokoro_models/voices-v1.0.bin'))
ff=WORK/'tmp/video_tools/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe'
stats=[]
for s in scenes:
    raw=NEW/'audio'/f"{s['id']}_24k.wav"
    target=NEW/'audio'/f"{s['id']}.wav"
    if not target.exists():
        audio,rate=kokoro.create(s['voice'],voice='af_heart',speed=.96,lang='en-us')
        # Normalize each segment gently, retaining the voice's natural dynamics.
        peak=float(np.max(np.abs(audio)))
        if peak>0:audio=audio*min(.86/peak,1.6)
        sf.write(str(raw),audio,rate,subtype='PCM_16')
        subprocess.run([str(ff),'-y','-v','error','-i',str(raw),'-ar','22050','-ac','1','-c:a','pcm_s16le',str(target)],check=True)
    audio,rate=sf.read(str(target))
    stats.append({'segment':s['id'],'seconds':len(audio)/rate,'peak':float(np.max(np.abs(audio)))})
    print(s['id'],round(len(audio)/rate,2),'seconds',flush=True)
(NEW/'source/voice_provenance.json').write_text(json.dumps({'engine':'Kokoro ONNX','voice':'af_heart','speed':.96,'processing':'Entirely local; project narration was not transmitted to a speech service.','runtime':'Separate tmp/demo_voice_env environment','model_source':'https://github.com/thewh1teagle/kokoro-onnx','license':'Kokoro model Apache-2.0; runtime MIT','segments':stats},indent=2),encoding='utf-8')
print('Speech generation complete:',NEW,flush=True)
