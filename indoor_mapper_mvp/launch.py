"""Desktop entry point with a durable startup error log."""
from pathlib import Path
import os
import traceback
import sys

base=Path(__file__).resolve().parent
os.chdir(base)
try:
    from app import main
    sys.exit(main())
except Exception:
    error=traceback.format_exc()
    logfile=base/'startup_error.log'
    logfile.write_text(error,encoding='utf-8')
    print(error,file=sys.stderr)
    print('Startup failed. Details: '+str(logfile),file=sys.stderr)
    sys.exit(1)
