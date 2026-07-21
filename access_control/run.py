"""Launch the standalone API, native kiosk, or both."""
from __future__ import annotations
import argparse,threading,time
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from app.env import load_dotenv
load_dotenv()
def args():
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=('api','ui','all'),nargs='?',default='all');return parser.parse_args()
def serve(runtime,server_holder=None):
    import uvicorn
    from app.api import create_app
    config=uvicorn.Config(create_app(runtime),host=runtime.config.api_host,port=runtime.config.api_port,log_level=runtime.config.log_level.lower());server=uvicorn.Server(config)
    if server_holder is not None:server_holder.append(server)
    server.run()
def main():
    mode=args().mode
    if mode=='ui':
        from app.ui.main import main as ui_main
        return ui_main()
    from app.bootstrap import build_runtime
    runtime=build_runtime()
    if mode=='api':serve(runtime);return 0
    holder=[];thread=threading.Thread(target=serve,args=(runtime,holder),daemon=True,name='access-api');thread.start()
    deadline=time.monotonic()+10
    while time.monotonic()<deadline and (not holder or not holder[0].started):time.sleep(.05)
    if not holder or not holder[0].started:raise RuntimeError('API failed to start')
    try:
        from app.ui.main import main as ui_main
        return ui_main()
    finally:
        holder[0].should_exit=True;thread.join(timeout=5)
if __name__=='__main__':raise SystemExit(main())
