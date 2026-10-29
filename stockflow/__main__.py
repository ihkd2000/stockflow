"""Command-line entry point: python -m stockflow serve"""
import argparse
from .db import init_db, init_commerce_db, init_counts_db

def main():
    parser = argparse.ArgumentParser(prog='python -m stockflow')
    commands = parser.add_subparsers(dest='command', required=True)
    serve = commands.add_parser('serve', help='Start the local web application')
    serve.add_argument('--host', default='127.0.0.1')
    serve.add_argument('--port', type=int, default=8000)
    commands.add_parser('init-db', help='Create local database tables')
    args = parser.parse_args()
    if args.command == 'init-db':
        init_db()
        init_commerce_db()
        init_counts_db()
        print('StockFlow database initialized')
    else:
        import uvicorn
        uvicorn.run('stockflow.api:app', host=args.host, port=args.port)

if __name__ == '__main__':
    main()
