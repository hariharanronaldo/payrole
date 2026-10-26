"""
python seed.py
Initializes database and seeds Cohort 1 with 100 demo interns, assigned mentors,
initial tasks with dynamic deadlines (T+2) and review dates (T+3),
as well as sample revisions and daily standups.
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from datetime import date, timedelta, datetime, timezone
import json
from app.models import init_db, SessionLocal, Cohort, Intern, Task, InternTask, TaskRevision, CheckIn

init_db()
db = SessionLocal()

try:
    # Safely clear previous seed for idempotency
    existing_cohort = db.query(Cohort).filter(Cohort.name == "Cohort 1").first()
    if existing_cohort:
        db.delete(existing_cohort)
        db.commit()

    today = date.today()
    start_date = today - timedelta(days=90) # 90 days ago for realistic 3-month milestone evaluation

    c = Cohort(name="Cohort 1", start_date=start_date)
    db.add(c)
    db.commit()

    # Seed 100 interns
    interns = []
    for n in range(1, 101):
        mentor_id = (n % 5) + 1
        intern = Intern(
            cohort_id=c.id,
            full_name=f"Intern {n:03d}",
            email=f"intern{n:03d}@example.com",
            mentor_email=f"mentor{mentor_id}@techcorp.internal",
            enrolled_at=start_date
        )
        interns.append(intern)
    db.add_all(interns)
    db.commit()

    # Re-query interns to get IDs
    all_interns = db.query(Intern).filter(Intern.cohort_id == c.id).order_by(Intern.id.asc()).all()

    # Seed Task 1: REST API & Authentication with dynamic T+2 deadline and T+3 review date
    t1_due = today + timedelta(days=2)
    t1_rev = today + timedelta(days=3)
    task1 = Task(
        cohort_id=c.id,
        title="Task 1: Distributed Auth Service",
        spec="Build a RESTful Authentication service with JWT tokens, refresh rotation, rate limiting, and 85%+ test coverage.",
        due_date=t1_due,
        review_date=t1_rev,
        assigned_by="engineering-manager@techcorp.internal"
    )
    db.add(task1)
    db.commit()

    # Assign Task 1 to all 100 interns
    assignments = []
    for intern in all_interns:
        it = InternTask(
            task_id=task1.id,
            intern_id=intern.id,
            status="assigned",
            due_date=t1_due,
            review_date=t1_rev,
            revision_count=0
        )
        assignments.append(it)
    db.add_all(assignments)
    db.commit()

    # Seed sample multi-stage revisions and completed status for first 15 interns to showcase Leaderboard and Verdicts
    now = datetime.now(timezone.utc)
    for idx in range(15):
        it = assignments[idx]
        intern = all_interns[idx]

        # Simulate 2-stage revision
        rev1 = TaskRevision(
            intern_task_id=it.id,
            task_id=task1.id,
            intern_id=intern.id,
            revision_number=1,
            submission_url=f"https://github.com/intern{idx+1:03d}/auth-service",
            mentor_notes="Initial submission looks promising. Missing unit test assertions for token expiration and need to sanitize error outputs.",
            extracted_corrections=json.dumps([
                "🧪 Test Automation: Add unit tests verifying token expiration under clock skew.",
                "🛡️ Defensive Engineering: Sanitize JSON error responses to avoid leaking tracebacks."
            ]),
            ai_guidance="Great effort on the core authentication routes! Address the error sanitization and token tests, then submit Revision #2.",
            score=78,
            status="revision_requested"
        )
        db.add(rev1)

        rev2 = TaskRevision(
            intern_task_id=it.id,
            task_id=task1.id,
            intern_id=intern.id,
            revision_number=2,
            submission_url=f"https://github.com/intern{idx+1:03d}/auth-service/commit/rev2",
            mentor_notes="Addressed all feedback cleanly. Test coverage is at 91% and token rotation handles refresh tokens safely.",
            extracted_corrections=json.dumps([]),
            ai_guidance="Approved! High-quality refactor with excellent test rigor. Ready for merging.",
            score=94 if idx < 5 else (88 if idx < 10 else 82),
            status="approved"
        )
        db.add(rev2)

        it.revision_count = 2
        it.status = "approved"
        it.score = rev2.score
        it.feedback = rev2.ai_guidance
        it.submission_url = rev2.submission_url
        it.submitted_at = now - timedelta(days=1)
        it.reviewed_at = now

        # Seed check-ins (standups)
        for d in range(1, 15):
            ci = CheckIn(
                intern_id=intern.id,
                date=today - timedelta(days=d),
                status_update=f"Day {d}: Worked on auth token flow, unit tests, and reviewed mentor feedback.",
                blockers="None" if d % 3 != 0 else "Waiting for mentor clarification on refresh token TTL"
            )
            db.add(ci)

    db.commit()
    print(f"[OK] Successfully seeded Cohort 1 with {len(all_interns)} interns, dynamic deadlines (T+2: {t1_due}, T+3: {t1_rev}), assignments, revisions, and check-ins!")

except Exception as e:
    db.rollback()
    print(f"[FAIL] Error during seed: {e}")
    raise
finally:
    db.close()
