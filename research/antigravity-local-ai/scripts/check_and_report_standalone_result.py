#!/usr/bin/env python3
"""
SOGH Antigravity - Check and Post Standalone Real Inference Result to Issue #199
"""

import os
import sys
import json
import urllib.request
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
RESULT_FILE = BASE_DIR / "handoff" / "STANDALONE_INFERENCE_RESULT.json"

def get_token():
    p = subprocess.Popen(['git', 'credential', 'fill'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, _ = p.communicate('protocol=https\nhost=github.com\n\n')
    for line in out.splitlines():
        if line.startswith('password='):
            return line.split('=', 1)[1].strip()
    return None

def main():
    if not RESULT_FILE.is_file():
        print("No standalone inference result found.")
        sys.exit(0)

    with open(RESULT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    print("Found Standalone Inference Result:")
    print(f"Timestamp: {data.get('timestamp')}")
    print(f"Success: {data.get('success')}")
    print(f"Elapsed: {data.get('elapsed_seconds')}s")

    token = get_token()
    if not token:
        print("ERROR: Git token not found")
        sys.exit(1)

    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json',
        'User-Agent': 'Antigravity-Agent',
        'Content-Type': 'application/json'
    }

    body = f"""[SOGH AI FINAL REPORT v1]
agent: Google Antigravity
timestamp: {data.get('timestamp')}
master_sha_observed: a485d31e7698df5f474cdd1bded8417894f3aa24
work_branch: master
execution_mode: STANDALONE_PHYSICAL_EXECUTION (Antigravity closed / Memory Maximized)
success: {data.get('success')}
elapsed_seconds: {data.get('elapsed_seconds')}
exit_code: {data.get('exit_code')}

## 実機推論実行結果 (Physical Execution on ASUS TUF Gaming FX505DY)
ユーザーの全権承認および「Antigravity終了によるRAM最大化」運用に基づき、スタンドアロン環境でQwen3-1.7Bの実機推論を実施しました。

- **実行モデル**: `Qwen3-1.7B-Q4_K_M.gguf` (2 threads, ctx 512, tokens 32, GPU layers 0)
- **事前空きRAM**: {data.get('ram_before_mb', 0):.1f} MB
- **温度状態**: {data.get('thermal_reading', {}).get('status')} ({data.get('thermal_reading', {}).get('temp_c', 0):.1f} °C, Direct Die: {data.get('thermal_reading', {}).get('is_direct_die')})
- **エラー/遮断理由**: {data.get('error', 'None')}

### 出力スニペット
```text
{data.get('stdout_snippet', '')}
```
"""

    payload = json.dumps({"body": body}).encode('utf-8')
    req = urllib.request.Request('https://api.github.com/repos/masatosprojects/SOGH-collab/issues/199/comments', data=payload, headers=headers)
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode('utf-8'))
        print(f"Posted to #199: Comment ID {res['id']}")

if __name__ == "__main__":
    main()
