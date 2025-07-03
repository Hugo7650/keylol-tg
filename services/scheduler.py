import asyncio
import schedule
import time
import threading
import logging
from typing import Callable

class TaskScheduler:
    """任务调度器"""
    
    def __init__(self, loop=None):
        self.is_running = False
        self.thread = None
        self.logger = logging.getLogger(__name__)
        self.jobs = {}
        self.loop = loop
    
    def add_job(self, func: Callable, interval: int, job_id: str = "", **kwargs):
        """添加定时任务"""
        if not job_id:
            job_id = f"job_{len(self.jobs)}"

        # 包装异步函数为同步可调用
        if asyncio.iscoroutinefunction(func):
            def sync_wrapper(*args, **kw):
                if self.loop:
                    asyncio.run_coroutine_threadsafe(func(*args, **kw), self.loop)
                else:
                    self.logger.error("未设置事件循环，无法调度异步任务")
            job = schedule.every(interval).seconds.do(sync_wrapper, **kwargs)
        else:
            job = schedule.every(interval).seconds.do(func, **kwargs)

        self.jobs[job_id] = job
        self.logger.info(f"添加定时任务: {job_id}, 间隔: {interval}秒")
        return job_id
    
    def remove_job(self, job_id: str):
        """移除定时任务"""
        if job_id in self.jobs:
            schedule.cancel_job(self.jobs[job_id])
            del self.jobs[job_id]
            self.logger.info(f"移除定时任务: {job_id}")
    
    def start(self):
        """启动调度器"""
        if self.is_running:
            return
        
        self.is_running = True
        self.thread = threading.Thread(target=self._run_schedule, daemon=True)
        self.thread.start()
        self.logger.info("任务调度器启动")
    
    def stop(self):
        """停止调度器"""
        self.is_running = False
        if self.thread:
            self.thread.join()
        self.logger.info("任务调度器停止")
    
    def _run_schedule(self):
        """运行调度循环"""
        while self.is_running:
            try:
                schedule.run_pending()
                time.sleep(1)
            except Exception as e:
                self.logger.error(f"调度器运行错误: {e}")
                time.sleep(5)
