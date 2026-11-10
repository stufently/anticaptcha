"""Background worker for processing CAPTCHA tasks"""
import asyncio
import json
from datetime import datetime
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.task import Task
from app.models.stats import Stats
from app.config import settings
from typing import Dict, Any


# Import solvers
from workers.solvers.recaptcha import RecaptchaV2Solver, RecaptchaV3Solver
from workers.solvers.hcaptcha import HcaptchaSolver
from workers.solvers.image_text import ImageTextSolver
from workers.solvers.turnstile import TurnstileSolver


# Solver registry
SOLVERS = {
    "recaptcha_v2": RecaptchaV2Solver,
    "recaptcha_v3": RecaptchaV3Solver,
    "hcaptcha": HcaptchaSolver,
    "image_text": ImageTextSolver,
    "turnstile": TurnstileSolver,
}


class TaskWorker:
    """Process CAPTCHA solving tasks"""
    
    def __init__(self):
        self.running = False
        self.solvers: Dict[str, Any] = {}
    
    async def setup_solvers(self):
        """Initialize all solvers"""
        failed = []
        for task_type, solver_class in SOLVERS.items():
            try:
                solver = solver_class()
                await solver.setup()
            except Exception as e:
                # One broken solver must not take the whole worker down: skip it,
                # its tasks fail with "No solver for task type".
                failed.append(task_type)
                print(
                    f"❌ Solver {task_type} failed to initialize, not registered: "
                    f"{type(e).__name__}: {e}",
                    flush=True,
                )
                continue
            self.solvers[task_type] = solver
            print(f"✅ Initialized solver: {task_type}")
        print(
            f"Solvers ready: {sorted(self.solvers)}; failed: {sorted(failed)}",
            flush=True,
        )
    
    async def cleanup_solvers(self):
        """Cleanup all solvers"""
        for task_type, solver in self.solvers.items():
            await solver.cleanup()
            print(f"🧹 Cleaned up solver: {task_type}")
    
    async def process_task(self, db: Session, task: Task):
        """Process a single task"""
        print(f"🔄 Processing task {task.id} (type: {task.type})")
        
        # Update status to processing
        task.status = "processing"
        task.started_at = datetime.utcnow()
        db.commit()
        
        try:
            # Get solver
            solver = self.solvers.get(task.type)
            if not solver:
                raise ValueError(f"No solver for task type: {task.type}")
            
            # Solve CAPTCHA
            input_data = json.loads(task.input_data)
            try:
                # Bound every solve: a hung page (e.g. a Promise that never
                # resolves) must not block the single worker forever. Cancelling
                # runs the solver's finally blocks, which close its page.
                result = await asyncio.wait_for(
                    solver.solve(input_data), timeout=settings.task_timeout
                )
            except asyncio.TimeoutError:
                raise TimeoutError(
                    f"Task timed out after {settings.task_timeout}s"
                ) from None
            
            # Update task
            task.status = "solved"
            task.result = json.dumps(result)
            task.solved_at = datetime.utcnow()
            db.commit()
            
            print(f"✅ Task {task.id} solved: {result}")
            
        except Exception as e:
            # Handle failure
            task.status = "failed"
            task.error_message = str(e)
            task.retries += 1
            db.commit()
            
            print(f"❌ Task {task.id} failed: {e}")
            return

        # Stats are best-effort: a stats error must not turn a solved task into failed
        try:
            self._update_stats(db, task)
        except Exception as e:
            db.rollback()
            print(f"⚠️ Stats update failed for task {task.id}: {type(e).__name__}: {e}")
    
    def _update_stats(self, db: Session, task: Task):
        """Update global statistics"""
        stats = db.query(Stats).first()
        
        if not stats:
            # Column defaults apply only on INSERT; set explicitly so += works
            stats = Stats(
                total_tasks=0, solved_tasks=0, failed_tasks=0, total_solve_time_seconds=0
            )
            db.add(stats)
        
        stats.total_tasks += 1
        stats.solved_tasks += 1
        
        if task.started_at and task.solved_at:
            solve_time = (task.solved_at - task.started_at).total_seconds()
            stats.total_solve_time_seconds += int(solve_time)
        
        db.commit()
    
    async def run(self):
        """Main worker loop"""
        print("🚀 Task worker started")
        
        # Setup solvers
        await self.setup_solvers()
        
        self.running = True
        
        while self.running:
            db = SessionLocal()
            try:
                # Get next pending task
                task = db.query(Task).filter(
                    Task.status == "pending"
                ).order_by(Task.created_at.asc()).first()
                
                if task:
                    await self.process_task(db, task)
                else:
                    # No tasks, wait
                    await asyncio.sleep(settings.worker_poll_interval)
            
            except Exception as e:
                print(f"❌ Worker error: {e}")
                await asyncio.sleep(1)
            
            finally:
                db.close()
        
        # Cleanup
        await self.cleanup_solvers()
        print("🛑 Task worker stopped")
    
    def stop(self):
        """Stop the worker"""
        self.running = False


async def main():
    """Run the task worker"""
    worker = TaskWorker()
    try:
        await worker.run()
    except KeyboardInterrupt:
        worker.stop()


if __name__ == "__main__":
    asyncio.run(main())