"""Shared admission, CPU quotas and molecular thread budgets for DFThub."""
import contextlib
import fcntl
import json
import os
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import psutil
from dfthub.paths import data_dir

def cpu_capacity():
    count = os.cpu_count() or 1
    try:
        count = min(count, len(psutil.Process().cpu_affinity()))
    except (AttributeError, psutil.Error):
        pass
    try:
        quota, period = Path('/sys/fs/cgroup/cpu.max').read_text().split()
        if quota != 'max':
            count = min(count, max(1, int(quota) // int(period)))
    except (OSError, ValueError):
        pass
    return count

def memory_capacity():
    vm = psutil.virtual_memory()
    memory = min(vm.total, vm.available)
    try:
        limit = Path('/sys/fs/cgroup/memory.max').read_text().strip()
        if limit != 'max':
            memory = min(memory, int(limit))
    except (OSError, ValueError):
        pass
    return max(256, int(memory * .7 / 1024**2))

MAX_DFT_TASKS = max(1, int(os.environ.get('DFTHUB_DFT_TASKS', '2')))
MAX_OPTIMIZER_TASKS = max(1, int(os.environ.get('DFTHUB_OPTIMIZER_TASKS', '2')))
TOTAL_CPU_THREADS = max(1, int(os.environ.get('DFTHUB_CPU_THREADS', str(cpu_capacity()))))
TASK_THREADS = min(TOTAL_CPU_THREADS, max(1, int(os.environ.get('DFTHUB_TASK_THREADS', str(min(16, TOTAL_CPU_THREADS))))))
OPTIMIZER_THREADS = min(TOTAL_CPU_THREADS, max(1, int(os.environ.get('DFTHUB_OPTIMIZER_THREADS', '4'))))
TOTAL_MEMORY_MB = max(256, int(os.environ.get('DFTHUB_MEMORY_MB', str(memory_capacity()))))
MOLECULAR_MEMORY_MB = max(256, TOTAL_MEMORY_MB // min(MAX_DFT_TASKS, max(1, TOTAL_CPU_THREADS // TASK_THREADS)))
PROGRAM_DIR = Path(__file__).resolve().parent
STATE_DIR = Path(os.environ.get('DFTHUB_SCHEDULER_DIR', str(data_dir() / 'scheduler')))
BOOT_ID = str(psutil.boot_time())

THREAD_VARIABLES = ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
                    'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS')


def threads_for_natom(natom, max_threads=16):
    return min(4 if natom <= 8 else 8 if natom <= 16 else 16, max_threads)


def threads_for_basis(nao, max_threads=16):
    """Spherical AO count captures diffuse/large bases even on small molecules."""
    if nao < 1:
        raise ValueError('Basis size must be positive')
    return min(4 if nao <= 80 else 8 if nao <= 160 else 16, max_threads)


def basis_size(xyz, preset):
    from pyscf import gto
    from dfthub.pipeline.basis_presets import load_basis_preset
    lines = Path(xyz).read_text().strip().splitlines()
    try:
        charge, multiplicity = map(int, lines[1].split()[:2])
    except ValueError:
        charge, multiplicity = 0, 1
    atom = '\n'.join(lines[2:2 + int(lines[0].split()[0])])
    basis, ecp = load_basis_preset(atom, preset)
    return gto.M(atom=atom, basis=basis, ecp=ecp, charge=charge,
                 spin=multiplicity - 1, verbose=0).nao_nr()


def thread_environment(threads):
    env = dict(os.environ)
    env.update({key: str(threads) for key in THREAD_VARIABLES})
    env['OMP_MAX_ACTIVE_LEVELS'] = '1'
    return env


def molecule_environment(threads):
    env = thread_environment(threads)
    env['DFTHUB_MAXMEM'] = str(max(256, MOLECULAR_MEMORY_MB * threads // TASK_THREADS))
    return env


class ThreadBudget:
    def __init__(self, total=TASK_THREADS):
        if total < 1 or total > TASK_THREADS:
            raise ValueError(f'Thread budget must be between 1 and {TASK_THREADS}')
        self.total = total
        self.available = total
        self.condition = threading.Condition()

    @contextlib.contextmanager
    def reserve(self, threads):
        if not 1 <= threads <= self.total:
            raise ValueError('Molecule exceeds the task thread budget')
        with self.condition:
            self.condition.wait_for(lambda: self.available >= threads)
            self.available -= threads
        try:
            yield
        finally:
            with self.condition:
                self.available += threads
                self.condition.notify_all()


def molecular_pool(items, natom, run, total=TASK_THREADS, max_threads=16, *, nao=None):
    """Yield (item, result, error) as independent molecule processes finish."""
    budget = ThreadBudget(total)
    items = list(items)
    if not items:
        return

    def execute(item):
        threads = min(threads_for_basis(nao(item), max_threads) if nao is not None
                      else threads_for_natom(natom(item), max_threads), total)
        with budget.reserve(threads):
            return run(item, threads)

    with ThreadPoolExecutor(max_workers=min(len(items), max(1, total // 4))) as pool:
        futures = {pool.submit(execute, item): item for item in items}
        for future in as_completed(futures):
            try:
                result, error = future.result(), None
            except Exception as exc:
                result, error = None, exc
            yield futures[future], result, error


def _process(pid):
    try:
        p = psutil.Process(pid)
        if p.status() == psutil.STATUS_ZOMBIE:
            return None
        return {'pid': p.pid, 'parent': p.ppid(), 'start': p.create_time(), 'boot': BOOT_ID}
    except psutil.Error:
        return None


def work_key(output):
    output = Path(output).resolve()
    for parent in output.parents:
        if parent.name == 'output':
            return str(parent.parent)
    return str(output)


@contextlib.contextmanager
def _registry():
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (STATE_DIR / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = STATE_DIR / 'tasks.json'
        records = json.loads(path.read_text()) if path.exists() else []
        alive = []
        for record in records:
            process = _process(record['pid'])
            if process and process['start'] == record['start'] and process['boot'] == record['boot']:
                alive.append(record)
        try:
            yield alive
        finally:
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(alive, indent=2) + '\n')
            temporary.replace(path)


@contextlib.contextmanager
def task_slot(output, threads, kind):
    record = _process(os.getpid())
    memory = min(TOTAL_MEMORY_MB, 2048) if kind == 'optimizer' else MOLECULAR_MEMORY_MB
    record.update(work=work_key(output), output=str(Path(output).resolve()), state='waiting',
                  threads=threads, memory_mb=memory, kind=kind)
    with _registry() as records:
        records.append(record)
    try:
        logged = False
        while True:
            with _registry() as records:
                active = [r for r in records if r['state'] == 'running']
                busy = {r['work'] for r in active}
                used_cpu = sum(r['threads'] for r in active)
                used_mem = sum(r['memory_mb'] for r in active)
                limit = MAX_OPTIMIZER_TASKS if kind == 'optimizer' else MAX_DFT_TASKS
                eligible = [r for r in records if r['state'] == 'waiting' and r['work'] not in busy
                            and sum(a['kind'] == r['kind'] for a in active) <
                                (MAX_OPTIMIZER_TASKS if r['kind'] == 'optimizer' else MAX_DFT_TASKS)
                            and used_cpu + r['threads'] <= TOTAL_CPU_THREADS
                            and used_mem + r['memory_mb'] <= TOTAL_MEMORY_MB]
                if eligible and eligible[0]['pid'] == record['pid']:
                    next(r for r in records if r['pid'] == record['pid'])['state'] = 'running'
                    break
            if not logged:
                print('QUEUED: waiting for CPU, memory or an earlier run of this job.', flush=True)
                logged = True
            time.sleep(.5)
        yield str(record['pid'])
    finally:
        with _registry() as records:
            records[:] = [r for r in records if r['pid'] != record['pid']]


def enter_task(output, threads, kind='dft'):
    if os.environ.get('DFTHUB_TASK_UNIT'):
        return
    threads = min(threads, TOTAL_CPU_THREADS)
    with task_slot(output, threads, kind) as unit:
        env = dict(os.environ, DFTHUB_TASK_UNIT=unit, PYTHONUNBUFFERED='1')
        child = subprocess.Popen([sys.executable, *sys.argv], env=env, start_new_session=True)
        def stop(signum, frame):
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            raise SystemExit(128 + signum)
        old = signal.signal(signal.SIGTERM, stop)
        try:
            print(f'Scheduler admitted task: {threads} CPU threads; reserved memory {MOLECULAR_MEMORY_MB} MB.', flush=True)
            rc = child.wait()
        finally:
            if child.poll() is None:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
            signal.signal(signal.SIGTERM, old)
    raise SystemExit(rc)


def limit_optimizer():
    # The parent keeps its original reservation until the whole pipeline exits.
    # This conservative reservation avoids overcommitting concurrent SCF work.
    os.environ.update(thread_environment(OPTIMIZER_THREADS))
