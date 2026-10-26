"""Local, read-only research dashboard. Never loads credentials or calls a provider."""
import argparse
import csv
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / 'results/study'
NAMES = ['No cache', 'Static threshold', 'VectorQ', 'Selectivity-aware threshold', 'Reverse threshold', 'Extra audits', 'Exact key']


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


class Dashboard:
    def __init__(self):
        self.runs = {}
        for folder in ['test', 'live']:
            for path in sorted((STUDY / folder / 'raw').glob('*.jsonl')):
                rows = [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines() if s.strip()]
                summary = next((r for r in reversed(rows) if r['kind'] == 'summary'), None)
                if summary:
                    settings=rows[0]['config']['policies']
                    frozen=read_json(STUDY / 'frozen_configuration.json')['payload']['policy_settings']
                    changes={k:v for k,v in settings.items() if v!=frozen.get(k)}
                    summary=dict(summary, variant='main settings' if not changes else ', '.join(f'{k}={v}' for k,v in changes.items()), policy_settings=settings)
                    self.runs[summary['run_id']] = (summary, rows)

    def api(self, path, query):
        if path == '/api/calibration':
            return read_json(STUDY / 'calibration/analysis.json')
        if path == '/api/overview':
            return dict(analysis=read_json(STUDY / 'analysis.json'),
                        live=list(csv.DictReader((STUDY / 'tables/live_runs.csv').open(encoding='utf-8'))),
                        freeze=read_json(STUDY / 'frozen_configuration.json'),
                        budget=read_json(STUDY / 'live_runtime_budget.json'),
                        config=read_json(ROOT / 'config/study.json'), names=NAMES,
                        figures=[p.name for p in sorted((STUDY / 'figures').glob('*.png'))],
                        downloads=[p.name for p in sorted((STUDY / 'tables').glob('*.csv'))])
        if path == '/api/runs':
            return [s for s, _ in self.runs.values()]
        if path == '/api/run':
            run_id = query.get('id', [''])[0]
            if run_id not in self.runs:
                raise ValueError('Unknown run')
            summary, rows = self.runs[run_id]
            qid = query.get('query', [''])[0]
            decision = query.get('decision', [''])[0]
            events = [r for r in rows if r['kind'] == 'event' and r.get('pass_kind') == 'measure'
                      and (not qid or r['query_id'] == qid)
                      and (not decision or r['decision'] == decision)]
            offset = int(query.get('offset', ['0'])[0])
            if offset < 0:
                raise ValueError('Invalid offset')
            return dict(summary=summary, queries=[r for r in rows if r['kind'] == 'query'
                        and r.get('pass_kind') == 'measure'], total=len(events), offset=offset,
                        events=events[offset:offset + 100])
        raise ValueError('Unknown API endpoint')


def make_handler(dashboard):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlsplit(self.path)
            try:
                if parsed.path.startswith('/api/'):
                    body = json.dumps(dashboard.api(parsed.path, parse_qs(parsed.query)), allow_nan=False).encode()
                    content_type = 'application/json; charset=utf-8'
                else:
                    # Explicit assets only: never serve the workspace or .env.
                    assets = {'/': ROOT / 'ui/index.html', '/app.js': ROOT / 'ui/app.js',
                              '/style.css': ROOT / 'ui/style.css', '/paper': ROOT / 'conference_paper.docx',
                              '/report': ROOT / 'research_report.pdf', '/readme': ROOT / 'README.md'}
                    assets.update({'/figures/' + p.name: p for p in (STUDY / 'figures').glob('*.png')})
                    assets.update({'/tables/' + p.name: p for p in (STUDY / 'tables').glob('*.csv')})
                    target = assets.get(parsed.path)
                    if target is None or not target.is_file():
                        self.send_error(404); return
                    body = target.read_bytes()
                    content_type = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
                                    '.css': 'text/css; charset=utf-8', '.png': 'image/png', '.pdf': 'application/pdf',
                                    '.csv': 'text/csv; charset=utf-8', '.md': 'text/plain; charset=utf-8',
                                    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}[target.suffix]
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; object-src 'none'; frame-ancestors 'none'")
                self.send_header('Cache-Control', 'no-store')
                self.end_headers(); self.wfile.write(body)
            except (ValueError, KeyError):
                self.send_error(400, 'Invalid request')

        def log_message(self, *args):
            pass
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(Dashboard()))
    print(f'Dashboard ready at http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
