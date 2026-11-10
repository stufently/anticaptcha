"""Background worker for processing CAPTCHA tasks"""
import asyncio
import json
from datetime import datetime
from sqlalchemy.orm import Session
from app.database import SessionLocal, init_db
from app.models.task import Task
from app.models.stats import Stats
from app.config import settings
from typing import Dict, Any


# Import solvers
from workers.heartbeat import heartbeat_loop
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


RESTART_ERROR = "worker restarted while processing the task"


class TaskWorker:
    """Process CAPTCHA solving tasks"""
    
    def __init__(self):
        self.running = False
        self.solvers: Dict[str, Any] = {}
        self._recovery_pending = True
    
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
    
    def recover_interrupted_tasks(self) -> int:
        """Fail tasks left in `processing` by a previous worker that died
        mid-task (crash, OOM, SIGILL). Not back to pending: a task that kills
        the worker would otherwise crash-loop it forever."""
        db = SessionLocal()
        try:
            stuck = db.query(Task).filter(Task.status == "processing").all()
            for task in stuck:
                task.status = "failed"
                task.error_message = RESTART_ERROR
                print(f"❌ Task {task.id} failed: {RESTART_ERROR}", flush=True)
            db.commit()
            return len(stuck)
        finally:
            db.close()

    def _try_recover(self) -> None:
        """Requeue interrupted tasks; on failure keep the flag set to retry later."""
        try:
            self.recover_interrupted_tasks()
        except Exception as exc:
            print(
                f"⚠️ Recovery of interrupted tasks failed: {type(exc).__name__}: {exc}",
                flush=True,
            )
            return
        self._recovery_pending = False

    async def run(self):
        """Main worker loop"""
        print("🚀 Task worker started")
        # On a fresh volume the API may not have created the tables yet, and
        # the first query would die with "no such table: tasks". Failure here
        # is fatal on purpose: without tables there is nothing to work on.
        init_db()
        # Recovery is best-effort: a locked or damaged database must not keep
        # the worker from serving new tasks. The flag stays set on failure and
        # the loop below retries, so tasks left in `processing` are not stranded
        # until the next restart.
        self._try_recover()

        # Setup solvers
        await self.setup_solvers()

        self.running = True

        # Liveness: touched from this event loop, including while process_task
        # runs, so only a wedged loop lets the stamp go stale.
        heartbeat = asyncio.create_task(
            heartbeat_loop(
                settings.worker_heartbeat_file,
                settings.worker_heartbeat_interval,
            )
        )
        try:
            while self.running:
                # Retry a recovery that failed at startup until it succeeds:
                # without this, tasks left in `processing` by a dead worker stay
                # stuck until the next restart.
                if self._recovery_pending:
                    self._try_recover()

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
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass
    
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