"""Start the loopback workspace: python -m se02.web --port 8763."""
import argparse
import sys
from se02.config import load_config
from se02.domain import DomainError
from .manager import JobManager
from .server import make_server


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m se02.web')
    parser.add_argument('--port',type=int,default=8763)
    parser.add_argument('--config')
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        print('Port must be between 1 and 65535.',file=sys.stderr)
        return 2
    manager = None
    server = None
    try:
        settings = load_config(config_path=args.config)
        manager = JobManager(root='runs/web',settings=settings)
        server = make_server('127.0.0.1',args.port,manager)
        print(f'SE02 workspace: http://127.0.0.1:{server.server_port}',flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    except (DomainError,OSError,ValueError):
        print('Cannot start local workspace. Check configuration and local port/storage.',file=sys.stderr)
        return 2
    finally:
        if server:
            server.server_close()
        if manager:
            manager.close()
    return 0

if __name__=='__main__':
    raise SystemExit(main())
