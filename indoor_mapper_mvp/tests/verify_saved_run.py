"""Verify recorded real pipeline outputs; does not rerun expensive SfM."""
from pathlib import Path
import json
import sqlite3
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mapper.engine import model_signature


def main():
    base=Path(__file__).resolve().parents[1]
    project=base/'projects/video_mvp_test'
    results=[json.loads(f.read_text(encoding='utf-8')) for f in (project/'queries').glob('*/result.json')]
    failures=[r for r in results if r['status']=='failed']
    assert len(failures)>=2 and all('pose' not in r for r in failures)
    successes=[r for r in results if r['status']=='success' and r['pose'].get('model_signature')]
    assert successes
    for r in successes:
        pose=r['pose']
        assert pose['model_signature']==model_signature(project/'sparse'/pose['model_id'])
        assert pose['quality']['num_2d3d']>=30
    with sqlite3.connect(project/'database.db') as con:
        names=[r[0] for r in con.execute('SELECT name FROM images')]
        assert len(names)==247 and not any(n.startswith('query') for n in names)
    from PIL import Image
    import numpy as np
    preview=np.array(Image.open(base/'test_artifacts/independent_photo_pose_final.png'))
    red=int(np.sum((preview[:,:,0]>180)&(preview[:,:,1]<80)&(preview[:,:,2]<80)))
    blue=int(np.sum((preview[:,:,2]>150)&(preview[:,:,0]<120)))
    assert red>10 and blue>10,(red,blue)
    print('Saved runs verified: failures have no pose; original DB contains no query; map signatures and viewer colors pass.')
    print('Viewer pixels:',red,'red;',blue,'blue')


if __name__=='__main__':main()
