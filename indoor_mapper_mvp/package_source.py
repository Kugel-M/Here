"""Package source without local environment, private captures or map data."""
from pathlib import Path
import zipfile

root=Path(__file__).resolve().parent
target=root.parent/'output/室内三维重建与视觉定位_MVP_源码.zip'
target.parent.mkdir(exist_ok=True)
excluded={'.venv','__pycache__','projects','test_artifacts','tmp','certs'}
with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(root.rglob('*')):
        rel=path.relative_to(root)
        if not path.is_file() or any(part in excluded for part in rel.parts) or path.name in {'ui_state.json','mobile_connection.json','mobile_access.json','mobile_server.log','mobile_server_error.log'}:continue
        archive.write(path,Path(root.name)/rel)
print(target)
