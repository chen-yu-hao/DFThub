"""Run a tiny real train/test fit using only installed resources and a temp data dir."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

from dfthub.paths import PROGRAM_DIR

with tempfile.TemporaryDirectory(prefix='dfthub-workflow-') as temp:
    root = Path(temp)
    input_dir = root / 'Work/smoke/job/input'
    output = root / 'Work/smoke/job/output/weight_0'
    input_dir.mkdir(parents=True)
    output.mkdir(parents=True)
    def geometry(path, bonds):
        with tarfile.open(path, 'w:gz') as archive:
            for index, bond in enumerate(bonds):
                raw = f'2\n0 1\nH 0 0 0\nH 0 0 {bond}\n'.encode()
                member = tarfile.TarInfo(f'H2_{index}.xyz')
                member.size = len(raw)
                archive.addfile(member, io.BytesIO(raw))
    geometry(input_dir / 'smoke.tgz', [.74, .85, 1.1])
    (input_dir / 'smoke.ref').write_text('1 H2_1 -1 H2_0 4.0 1\n1 H2_2 -1 H2_0 25.0 1\n')
    test = input_dir / 'test_set'
    test.mkdir()
    geometry(test / 'test.tgz', [.74, .9, 1.2])
    (test / 'test.ref').write_text('1 H2_1 -1 H2_0 8.0 1\n1 H2_2 -1 H2_0 35.0 1\n')
    (test / 'manifest.json').write_text(json.dumps({'geometry':'test.tgz', 'reference':'test.ref', 'dataset':'test'}))
    (input_dir / 'basis.txt').write_text('sto-3g\n')
    (output / 'weight.csv').write_text('Database,Description,Type,Source,Number,Inverse Weight\nsmoke,smoke,Input,uploaded,1,0.02\n')
    env = dict(os.environ, DFTHUB_DATA_DIR=str(root), DFTHUB_DEMO_ROOT=str(root / 'optimizer'),
               DFTHUB_SCHEDULER_DIR=str(root / 'scheduler'), DFTHUB_GRID='0',
               DFTHUB_CPU_THREADS='2', DFTHUB_TASK_THREADS='2', DFTHUB_OPTIMIZER_THREADS='1',
               DFTHUB_MEMORY_MB='2048', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    command = [sys.executable, str(PROGRAM_DIR / 'main.py'), '--input', str(input_dir / 'smoke.tgz'),
               '--output', str(output), '--weight', str(output / 'weight.csv'), '--basis', 'sto-3g']
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=600)
    if result.returncode:
        print(result.stdout, result.stderr)
        for log in output.rglob('*.log'):
            print(log.name, log.read_text()[-6000:])
        raise SystemExit(result.returncode)
    for name in ['NEW-params.txt','Mue','OriginalMue','TEST_INPUT','TEST_INPUT_ref','TestMue','CF22D_optimized.py']:
        assert (output / name).is_file(), name
    status = json.loads((output / 'OptimizationStatus.json').read_text())
    assert status['converged'], status
    assert not (output / 'optimizer_snapshot/Database_updated/fit/TEST_INPUT').exists()
    print(json.dumps({'passed':True,'optimization_iterations':status['iterations'], 'train_test_fit':'passed'}))
