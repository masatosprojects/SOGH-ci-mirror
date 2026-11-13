"""Optional Playwright smoke: localhost only; synthetic inputs and screenshots."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

p = argparse.ArgumentParser()
p.add_argument('--url', default='http://127.0.0.1:8766')
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
if not a.url.startswith('http://127.0.0.1:'):
    raise SystemExit('Loopback URL required')
a.output.mkdir(parents=True, exist_ok=True)
errors, external = [], []
with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, channel='msedge')
    page = browser.new_page(viewport={'width': 1365, 'height': 1000})
    page.on('pageerror', lambda error: errors.append(str(error)))
    def route(request_route):
        if request_route.request.url.startswith(a.url + '/'):
            request_route.continue_()
        else:
            external.append(request_route.request.url)
            request_route.abort()
    page.route('**/*', route)
    page.goto(a.url)
    page.locator('#cases button').first.wait_for()
    assert page.locator('#cases button').count() == 3
    page.locator('#cases button').first.click()
    page.locator('#start').wait_for(state='visible')
    page.screenshot(path=str(a.output / 'demo-desktop.png'), full_page=True)
    page.locator('#start').click()
    page.locator('#sample').click()
    page.locator('#send').click()
    page.locator('.answer').wait_for()
    page.locator('#end').click()
    page.locator('#feedback').wait_for(state='visible')
    assert page.locator('.feedback-card').count() == 5
    page.locator('#retry').click()
    page.locator('#answer-form').wait_for(state='visible')
    page.locator('#end').click()
    page.locator('#comparison h3').wait_for()
    page.locator('#clear').click()
    page.locator('#report-tab').click()
    assert page.locator('#format option').count() == 6
    page.locator('#format').select_option('individual')
    assert page.locator('#format').input_value() == 'individual'
    assert not page.locator('#public').is_checked()
    page.locator('#report-form button[type=submit]').click()
    page.locator('#report-result h3').wait_for()
    assert '保存・公開はしていません' in page.locator('#report-result').inner_text()
    page.set_viewport_size({'width': 390, 'height': 844})
    page.screenshot(path=str(a.output / 'demo-mobile.png'), full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    assert not page.evaluate('localStorage.length')
    assert not errors and not external, (errors, external)
    browser.close()
(a.output / 'browser-result.json').write_text(json.dumps({'status': 'SELF_VALIDATED',
    'data_kind': 'SYNTHETIC_ONLY', 'scenario_count': 2, 'javascript_errors': errors,
    'external_requests': external, 'real_user_validation': 'NOT_RUN'}, indent=2), encoding='utf-8')
print('2 browser scenarios passed; 0 JavaScript errors; 0 external requests')
