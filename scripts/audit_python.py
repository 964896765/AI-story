"""Check the pinned Python versions against PyPI's release advisories."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from time import sleep
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
PIN = re.compile(r'([a-zA-Z0-9_.-]+)==([a-zA-Z0-9_.+-]+)')


def query(pin):
    name, version = pin.groups()
    url = f'https://pypi.org/pypi/{name}/{version}/json'
    for attempt in range(3):
        try:
            with urlopen(url, timeout=15) as response:
                data = json.load(response)
            return {'name': name, 'version': version, 'advisories': [
                {key: advisory.get(key) for key in ('id', 'aliases', 'link', 'fixed_in')}
                for advisory in data['vulnerabilities'] if not advisory.get('withdrawn')
            ]}
        except (OSError, KeyError, ValueError) as exc:
            if attempt==2:
                return {'name': name, 'version': version, 'error': type(exc).__name__}
            sleep(attempt+1)


def main():
    pins = []
    for line in (ROOT/'backend/requirements.lock').read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if not (pin := PIN.fullmatch(line)):
            raise SystemExit('Only exact version pins can be audited: ' + line)
        pins.append(pin)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(query, pins))
    report = {'source': 'PyPI release JSON', 'checked_at': datetime.now(timezone.utc).isoformat(),
              'checked': len(results), 'unavailable': sum('error' in row for row in results),
              'active_advisories': sum(len(row.get('advisories', [])) for row in results),
              'packages': results}
    target = ROOT/'data/tmp/p14-python-audit.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print({key: value for key, value in report.items() if key!='packages'})
    return bool(report['unavailable'] or report['active_advisories'])


if __name__ == '__main__':
    sys.exit(main())
