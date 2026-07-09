import asyncio
import time
import inspect
from functools import wraps

class APIPriorityQueue:
    def __init__(self):
        self.queue = asyncio.PriorityQueue()
        self.is_running = False
        self._last_call_time = 0
        self.RATE_LIMIT = 0.1 # 100ms between calls
    
    async def start(self):
        if self.is_running: return
        self.is_running = True
        asyncio.create_task(self._process_queue())

    async def _process_queue(self):
        while self.is_running:
            priority, timestamp, func, args, kwargs, future = await self.queue.get()
            
            # Rate limiting
            now = time.time()
            elapsed = now - self._last_call_time
            if elapsed < self.RATE_LIMIT:
                await asyncio.sleep(self.RATE_LIMIT - elapsed)
            
            self._last_call_time = time.time()
            
            try:
                if inspect.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    # Run blocking Fyers SDK calls in a thread pool
                    result = await asyncio.to_thread(func, *args, **kwargs)
                if not future.done():
                    future.set_result(result)
            except Exception as e:
                if not future.done():
                    future.set_exception(e)
            
            self.queue.task_done()

    async def enqueue(self, priority: int, func, *args, **kwargs):
        future = asyncio.Future()
        await self.queue.put((priority, time.time(), func, args, kwargs, future))
        return await future

# Global queue
api_queue = APIPriorityQueue()
