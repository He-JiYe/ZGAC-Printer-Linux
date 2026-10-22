"""Session-scoped automation: only newly observed CUPS jobs are eligible."""
from collections import deque


class AutoSubmitQueue:
    def __init__(self, existing_ids=()):
        self.seen = set(existing_ids)
        self.pending = deque()
        self.active = None
        self.paused = False

    def observe(self, jobs, enabled):
        for job in sorted(jobs, key=lambda x: x.get('created_at', 0)):
            job_id = job['id']
            if job_id in self.seen:
                continue
            self.seen.add(job_id)
            if enabled and not self.paused and job.get('source') == 'cups' and job['state'] == 'prepared':
                self.pending.append(job_id)

    def take(self, logged_in, busy=False):
        if not logged_in or busy or self.paused or self.active or not self.pending:
            return None
        self.active = self.pending.popleft()
        return self.active

    def finished(self, success):
        self.active = None
        if not success:
            self.pause()

    def pause(self):
        self.pending.clear()
        self.paused = True

    def arm(self, current_jobs):
        self.seen.update(j['id'] for j in current_jobs)
        self.pending.clear()
        self.paused = False
