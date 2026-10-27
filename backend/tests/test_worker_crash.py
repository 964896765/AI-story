"""Real Windows worker crash/restart, not a fabricated state-only recovery."""
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import timedelta
import pytest
from app import worker
from app.models import Task,now
from test_render_postgres import studio
from test_postgres import database

@pytest.mark.skipif(os.name!='nt',reason='Windows Job Object lifecycle test')
def test_worker_death_kills_encoder_and_new_worker_recovers(studio,tmp_path):
    client,project,asset,upload,submit,task,resolve,factory=studio
    queued=submit({'duration':2,'resolution':'2160'})
    tid=queued['id']
    # Launch the actual interpreter directly with this venv's module paths, avoiding
    # the Windows venv launcher parent so killing this PID kills the worker itself.
    env={**os.environ,'DATABASE_URL':os.environ['TEST_DATABASE_URL'],'STORAGE_ROOT':str(tmp_path),'PYTHONPATH':os.pathsep.join(str(Path(p).resolve()) for p in sys.path if p)}
    base=getattr(sys,'_base_executable',sys.executable)
    with (tmp_path/'worker-process.log').open('w') as log:
        process=subprocess.Popen([base,'-c','from app.worker import run_once; run_once()'],env=env,stdout=log,stderr=log)
        try:
            partial=resolve(f'tmp/{tid}/1/partial.mp4')
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                current=task(tid)
                if current['stage']=='encoding' and partial.exists():break
                if process.poll() is not None:pytest.fail((tmp_path/'worker-process.log').read_text())
                time.sleep(0.05)
            assert current['stage']=='encoding' and partial.exists()
            # A second worker cannot run while the first holds the global lock.
            assert worker.run_once() is False
            process.kill();process.wait(timeout=5)
            # The kernel must close the job and kill FFmpeg. Its temporary file
            # becomes exclusively openable again, proving the writer exited.
            import ctypes
            from ctypes import wintypes
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
            kernel.CreateFileW.restype=wintypes.HANDLE
            kernel.CloseHandle.argtypes=[wintypes.HANDLE]
            for _ in range(30):
                if partial.exists():
                    handle=kernel.CreateFileW(str(partial),0x80000000,0,None,3,0,None)
                    if handle!=ctypes.c_void_p(-1).value:
                        kernel.CloseHandle(handle);break
                time.sleep(0.1)
            else:pytest.fail('Encoder still holds its temporary output after worker death')
            with factory.begin() as db:
                db.get(Task,tid).lease_until=now()-timedelta(seconds=1)
            restarted=subprocess.run([base,'-c','from app.worker import run_once; run_once()'],env=env,stdout=log,stderr=log,timeout=60)
            assert restarted.returncode==0
            result=task(tid)
            assert result['status']=='succeeded',result['error']
            assert result['attempt']==2 and resolve(result['output']['storage_key']).is_file()
        finally:
            if process.poll() is None:process.kill();process.wait(timeout=5)
