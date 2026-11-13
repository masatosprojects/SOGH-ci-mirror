"""Apply the reviewed patch to NEW code-only isolation; never open a database."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--source-root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    here = Path(__file__).resolve().parent
    source, output = a.source_root.resolve(), a.output.resolve()
    if output.exists() or source == output or source in output.parents:
        raise SystemExit('Choose a NEW isolation directory outside the source tree')
    expected = json.loads((here / 'preconditions.json').read_text(encoding='utf-8'))
    for name, digest in expected.items():
        raw = (source / name).read_bytes().replace(b'\r\n', b'\n')
        if hashlib.sha256(raw).hexdigest() != digest:
            raise SystemExit('Precondition mismatch: ' + name + '; review changes first')
    output.mkdir(parents=True)
    status = output / '.work-isolation-status.json'
    step = 'copy_code'
    status.write_text(json.dumps({'state':'in_progress','step':step}),encoding='utf-8')
    try:
        for name in ('admissions_pipeline', 'admission_ai', 'scripts', 'tests', 'config'):
            shutil.copytree(source / name, output / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        for file in source.glob('*.py'):
            shutil.copyfile(file, output / file.name)
        if (source / 'config.example.toml').exists():
            shutil.copyfile(source / 'config.example.toml', output / 'config.example.toml')
        for name in expected:
            file = output / name
            file.write_bytes(file.read_bytes().replace(b'\r\n', b'\n'))
        patch = str(here / 'work-current-stage1.patch')
        step = 'patch_check'
        subprocess.run(['git', '-c', 'core.autocrlf=false', 'apply', '--check', patch], cwd=output, check=True)
        step = 'patch_apply'
        subprocess.run(['git', '-c', 'core.autocrlf=false', 'apply', patch], cwd=output, check=True)
    except BaseException as error:
        status.write_text(json.dumps({'state':'failed','step':step,'error_type':type(error).__name__}),encoding='utf-8')
        raise
    status.write_text(json.dumps({'state':'completed','patch_sha256':hashlib.sha256(Path(patch).read_bytes()).hexdigest(),
        'output_sha256':{n:hashlib.sha256((output/n).read_bytes()).hexdigest() for n in expected}},indent=2),encoding='utf-8')
    print('Patched code-only isolation created. No database was opened.')


if __name__ == '__main__':
    main()
