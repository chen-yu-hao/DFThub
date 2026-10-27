import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


class InstalledServiceTests(unittest.TestCase):
    def test_installed_engine_and_offline_pages(self):
        with tempfile.TemporaryDirectory() as root:
            env = dict(os.environ, DFTHUB_DATA_DIR=root, DFTHUB_WORKERS='0', DFTHUB_MAIL_SUPPRESS='1')
            code = '''
import socket
def blocked(*a, **k):
    raise AssertionError('Unexpected network access')
socket.create_connection = blocked
socket.socket.connect = blocked
from dfthub.doctor import check
assert not check()['errors'], check()
from dfthub.server import create_app
client = create_app().test_client()
for path in ['/', '/workspace/', '/analyze/', '/guide/', '/energy/', '/api_dft/docs', '/vendor/swagger/swagger-ui-bundle.js']:
    response = client.get(path)
    assert response.status_code == 200, (path, response.status_code)
    if path.endswith('/'):
        assert b'fonts.googleapis.com' not in response.data
assert client.get('/api_dft/unknown').status_code == 404
assert client.get('/not-a-page').status_code == 404
assert client.get('/workspace?job=abc').headers['Location'] == '/workspace/?job=abc'
assert client.get('/api_dft/download/Work/template').status_code == 200
'''
            subprocess.run([sys.executable, '-c', code], env=env, cwd=root, check=True)

    def test_data_initialization_preserves_existing_files(self):
        from dfthub.paths import initialize_data
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'DFTHUB_DATA_DIR': root}):
            directory = initialize_data()
            (directory / 'submit_count.txt').write_text('42')
            marker = directory / 'Work/keep'
            marker.write_text('keep')
            initialize_data()
            self.assertEqual((directory / 'submit_count.txt').read_text(), '42')
            self.assertEqual(marker.read_text(), 'keep')

    def test_upstream_package_conflict_is_rejected(self):
        from dfthub import doctor
        original = doctor.md.distribution
        def dist(name):
            return object() if name == 'pyscf' else original(name)
        with patch.object(doctor.md, 'distribution', side_effect=dist):
            errors = doctor.engine_check()['errors']
        self.assertTrue(any('Conflicting upstream' in e for e in errors))

    def test_registry_cleans_dead_process_and_preserves_current(self):
        from dfthub.pipeline import compute_scheduler as scheduler
        with tempfile.TemporaryDirectory() as root, patch.object(scheduler, 'STATE_DIR', Path(root)):
            live = scheduler._process(os.getpid())
            dead = dict(live, pid=999999999)
            (Path(root) / 'tasks.json').write_text(json.dumps([dead, live]))
            with scheduler._registry() as records:
                self.assertEqual(records, [live])

    def test_parallel_tasks_are_serialized_with_a_single_cpu_budget(self):
        with tempfile.TemporaryDirectory() as root:
            code = '''
import sys, time
from pathlib import Path
from dfthub.pipeline.compute_scheduler import task_slot
with task_slot(sys.argv[1], 1, 'dft'):
    Path(sys.argv[1]).write_text(str(time.monotonic()))
    time.sleep(.3)
    Path(sys.argv[1] + '.end').write_text(str(time.monotonic()))
'''
            env = dict(os.environ, DFTHUB_SCHEDULER_DIR=root+'/scheduler', DFTHUB_CPU_THREADS='1', DFTHUB_TASK_THREADS='1')
            children = [subprocess.Popen([sys.executable, '-c', code, root+'/'+str(i)], env=env) for i in range(2)]
            for child in children:
                self.assertEqual(child.wait(timeout=15), 0)
            intervals = sorted((float(Path(root,str(i)).read_text()), float(Path(root,str(i)+'.end').read_text())) for i in range(2))
            self.assertLessEqual(intervals[0][1], intervals[1][0])


if __name__ == '__main__':
    unittest.main()
