"""Read-only migration check. Never synthesize, mutate the queue, or publish."""
import json
import os
import sys
from pathlib import Path

import requests
from google.oauth2 import service_account
from google.auth.transport.requests import AuthorizedSession


def run():
    config = json.loads(Path(__file__).with_name('config.json').read_text())
    results = []

    def record(check, status, detail):
        results.append(dict(check=check, status=status, detail=detail))
        print(f'{check}: {status} — {detail}', flush=True)

    names = ('GOOGLE_SERVICE_ACCOUNT_JSON', 'METRICOOL_API_TOKEN',
             'OPENAI_API_KEY', 'LUCYLAB_API_KEY')
    present = {name: bool(os.getenv(name, '').strip()) for name in names}
    for name, exists in present.items():
        record(name, 'PRESENT' if exists else 'MISSING',
               'Configured in GitHub Actions' if exists else 'Add repository Actions secret')

    if present['GOOGLE_SERVICE_ACCOUNT_JSON']:
        try:
            info = json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT_JSON'])
            credentials = service_account.Credentials.from_service_account_info(
                info, scopes=['https://www.googleapis.com/auth/spreadsheets'])
            session = AuthorizedSession(credentials)
            root = 'https://sheets.googleapis.com/v4/spreadsheets/' + config['spreadsheet_id']
            response = session.get(root, params={'fields': 'spreadsheetId,sheets.properties.title'}, timeout=30)
            if response.status_code != 200:
                record('Google Sheet read', 'FAIL', f'HTTP {response.status_code}; check API enablement and Sheet sharing')
            else:
                tabs = [s['properties']['title'] for s in response.json().get('sheets', [])]
                if config['sheet_tab'] not in tabs:
                    record('Google Sheet read', 'FAIL', 'Configured queue tab missing')
                else:
                    from urllib.parse import quote
                    response = session.get(root + '/values/' + quote(config['sheet_range'], safe=''), timeout=30)
                    record('Google Sheet read', 'PASS' if response.status_code == 200 else 'FAIL',
                           'Queue range accessible' if response.status_code == 200 else f'HTTP {response.status_code}')
                    record('Google Sheet write', 'NOT_TESTED', 'No queue mutation in preflight; Editor sharing still required')
        except Exception as exc:
            record('Google Sheet read', 'FAIL', f'{type(exc).__name__}; credentials or network check failed')

    if present['METRICOOL_API_TOKEN']:
        try:
            settings = config['metricool']
            response = requests.get('https://app.metricool.com/api/admin/simpleProfiles',
                params={'userId': settings['user_id'], 'blogId': settings['blog_id']},
                headers={'X-Mc-Auth': os.environ['METRICOOL_API_TOKEN']}, timeout=30)
            if response.status_code != 200:
                record('Metricool brand read', 'FAIL', f'HTTP {response.status_code}; check token and API entitlement')
            else:
                data = response.json()
                profiles = data.get('data', []) if isinstance(data, dict) else data
                if isinstance(profiles, dict):
                    profiles = profiles.get('profiles', [])
                matched = any(str(p.get('id', p.get('blogId', ''))) == str(settings['blog_id'])
                              for p in profiles if isinstance(p, dict)) if isinstance(profiles, list) else False
                record('Metricool brand read', 'PASS' if matched else 'FAIL',
                       'Target brand accessible' if matched else 'Target brand not found in profiles response')
        except Exception as exc:
            record('Metricool brand read', 'FAIL', f'{type(exc).__name__}; response or network check failed')

    if present['OPENAI_API_KEY']:
        try:
            response = requests.get('https://api.openai.com/v1/models',
                headers={'Authorization': 'Bearer ' + os.environ['OPENAI_API_KEY']}, timeout=30)
            record('AI authentication', 'PASS' if response.status_code == 200 else 'FAIL',
                   'Authenticated; video understanding and visual QA still require integration tests'
                   if response.status_code == 200 else f'HTTP {response.status_code}')
        except Exception as exc:
            record('AI authentication', 'FAIL', f'{type(exc).__name__}; network check failed')

    record('LucyLab synthesis', 'NOT_TESTED', 'No paid TTS exports created by this check')
    record('HANDU M00–M12 runner', 'NOT_IMPLEMENTED',
           'Repository currently has separate intake and TTS bridges; autonomous production integration is pending')
    record('Automatic publishing', 'DISABLED', 'Must remain disabled until end-to-end M12 and scheduling tests pass')
    blockers = [r for r in results if r['status'] in ('MISSING', 'FAIL', 'NOT_IMPLEMENTED')]
    output = Path('handu_preflight_output')
    output.mkdir(exist_ok=True)
    (output / 'report.json').write_text(json.dumps({'ready': not blockers, 'results': results}, ensure_ascii=False, indent=2))
    summary = '# HANDU GitHub migration preflight\n\n'
    summary += '| Check | Status | Detail |\n|---|---|---|\n'
    summary += '\n'.join(f"| {r['check']} | {r['status']} | {r['detail']} |" for r in results)
    summary += '\n\nNo Sheet writes, paid TTS, AI generation, or Facebook posts were performed.\n'
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
            stream.write(summary)
    return 1 if blockers else 0


if __name__ == '__main__':
    sys.exit(run())
