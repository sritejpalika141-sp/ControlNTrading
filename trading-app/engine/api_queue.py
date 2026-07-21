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
        # ROOT-CAUSE FIX (no-trades investigation, 21-Jul): this is a SINGLE-CONSUMER queue that
        # every Fyers call in the app funnels through. It had NO per-call timeout, so one hung REST
        # request blocked EVERY other API call process-wide. Measured effect: get_quotes_with_fallback
        # and find_nearest_expiry both stalled >45s, get_analysis exceeded 150s per symbol, a
        # 7-symbol automation cycle took 15-20+ minutes, and time-boxed strategies (ORB 09:20-09:30,
        # the 09:26 entry) could never be evaluated inside their window -> no trades placed.
        # Bounding each call keeps one bad request from starving the whole system.
        self.CALL_TIMEOUT = 12.0   # seconds per individual API call
        self.timeouts = 0          # observability: how often calls are being killed
    
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
                    inner = func(*args, **kwargs)
                else:
                    # Run blocking Fyers SDK calls in a thread pool
                    inner = asyncio.to_thread(func, *args, **kwargs)
                # Hard per-call bound: a hung request must never stall the shared queue.
                result = await asyncio.wait_for(inner, timeout=self.CALL_TIMEOUT)
                if not future.done():
                    future.set_result(result)
            except asyncio.TimeoutError:
                self.timeouts += 1
                name = getattr(func, "__name__", str(func))
                print(f"⏱️ API call '{name}' exceeded {self.CALL_TIMEOUT}s — abandoned so the queue "
                      f"keeps moving (total timeouts: {self.timeouts}).", flush=True)
                if not future.done():
                    future.set_exception(TimeoutError(f"{name} exceeded {self.CALL_TIMEOUT}s"))
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
