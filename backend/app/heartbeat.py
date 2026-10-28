"""Independent DB heartbeat, including while ffprobe blocks."""
import os
import socket
import threading
import time
from datetime import timedelta
from uuid import uuid4
from sqlalchemy import select
from .models import WorkerNode,Task,now

class Heartbeat:
    def __init__(self,factory):
        self.factory=factory
        self.id=str(uuid4())
        self.active=None
        self.lock=threading.Lock()
        self.stop=threading.Event()
        self.lost=threading.Event()
        self.failure=None

    def bind(self,task_id,token):
        with self.lock:
            self.active=(task_id,token,time.monotonic())
            self.lost.clear();self.failure=None

    def clear(self):
        with self.lock:self.active=None

    def tick(self):
        with self.lock:
            with self.factory.begin() as db:
                node=db.get(WorkerNode,self.id)
                node.last_seen=now()
                node.state='busy' if self.active else 'idle'
                node.task_id=self.active[0] if self.active else None
                node.error=self.failure
                if self.active:
                    tid,token,started=self.active
                    task=db.scalar(select(Task).where(Task.id==tid).with_for_update())
                    if not task or task.worker_token!=token or task.status!='running':
                        self.lost.set()
                    else:
                        task.lease_until=now()+timedelta(seconds=30)
                        task.elapsed_seconds=time.monotonic()-started

    def loop(self):
        while not self.stop.wait(2):
            try:self.tick()
            except Exception as exc:
                self.failure=type(exc).__name__+': heartbeat failed'
                self.lost.set()

    def __enter__(self):
        with self.factory.begin() as db:
            db.add(WorkerNode(id=self.id,pid=os.getpid(),hostname=socket.gethostname(),state='idle'))
        self.thread=threading.Thread(target=self.loop,daemon=True)
        self.thread.start()
        return self

    def __exit__(self,*args):
        self.stop.set();self.thread.join(timeout=5)
        try:
            with self.factory.begin() as db:
                node=db.get(WorkerNode,self.id)
                node.state='offline';node.last_seen=now();node.error=self.failure
        except Exception:pass
