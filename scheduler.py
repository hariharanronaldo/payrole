import logging
from datetime import datetime, date, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from app.models import SessionLocal, Cohort, Intern, Task, InternTask, MilestoneEvaluation
from app.services.email_service import EmailService
from app.services.task_service import TaskService
from app.services.evaluation_engine import EvaluationEngine

logger = logging.getLogger("internops.scheduler")
scheduler = BackgroundScheduler()


def daily_standup_prompt_job():
    """Automation Job: Sends daily 09:00 standup check-in prompt to all active interns."""
    logger.info("Executing daily standup prompt job...")
    db = SessionLocal()
    try:
        interns = db.query(Intern).filter(Intern.status == "active").all()
        for intern in interns:
            EmailService.send_standup_prompt(intern.full_name, intern.email)
        logger.info(f"Daily standup prompts dispatched to {len(interns)} interns.")
    except Exception as e:
        logger.error(f"Error in daily standup prompt job: {e}")
    finally:
        db.close()


def dynamic_deadline_alert_job():
    """
    Automation Job: Dynamic Deadline Monitor (T + 2 days).
    Checks for tasks due today or within the dynamic window with pending submissions,
    and alerts interns with mentor CC.
    """
    logger.info("Executing dynamic deadline alert job...")
    db = SessionLocal()
    try:
        today = date.today()
        # Find active assignments for tasks due on or before today that haven't been submitted
        pending_assignments = (
            db.query(InternTask)
            .join(Task, InternTask.task_id == Task.id)
            .filter(
                Task.due_date <= today,
                InternTask.status.in_(["assigned", "in_progress", "revision_requested"])
            )
            .all()
        )
        for assignment in pending_assignments:
            intern = assignment.intern
            task = assignment.task
            if intern and task:
                EmailService.send_email(
                    to_email=intern.email,
                    subject=f"[Deadline Alert] Task #{task.id} Due Today: {task.title}",
                    body=(
                        f"Hi {intern.full_name},\n\n"
                        f"This is an automated alert from InternOps AI.\n"
                        f"Task #{task.id} ('{task.title}') has reached its dynamic submission deadline ({task.due_date}).\n\n"
                        f"Mentor review is scheduled for tomorrow ({task.review_date}). Please submit your latest work or revision promptly via:\n"
                        f"/submit task_id={task.id} url=<repo_url> notes=\"Final iteration\"\n\n"
                        f"InternOps AI Automation Engine"
                    ),
                    cc=[intern.mentor_email]
                )
        logger.info(f"Dynamic deadline check completed. Alerts sent for {len(pending_assignments)} assignments.")
    except Exception as e:
        logger.error(f"Error in dynamic deadline alert job: {e}")
    finally:
        db.close()


def mentor_review_date_job():
    """
    Automation Job: Dynamic Review Date Monitor (T + 3 days).
    Notifies mentors when submitted tasks reach their review date so feedback is delivered promptly.
    """
    logger.info("Executing mentor review date job...")
    db = SessionLocal()
    try:
        today = date.today()
        submitted_assignments = (
            db.query(InternTask)
            .join(Task, InternTask.task_id == Task.id)
            .filter(
                Task.review_date <= today,
                InternTask.status.in_(["submitted"])
            )
            .all()
        )
        for assignment in submitted_assignments:
            intern = assignment.intern
            task = assignment.task
            if intern and task:
                EmailService.send_email(
                    to_email=intern.mentor_email,
                    subject=f"[Review Due] Submission Ready for Review: {task.title} (Intern: {intern.full_name})",
                    body=(
                        f"Hi Mentor,\n\n"
                        f"Today is the scheduled review date ({task.review_date}) for Task #{task.id} ('{task.title}').\n"
                        f"Intern: {intern.full_name} (Intern #{intern.id})\n"
                        f"Submission URL: {assignment.submission_url}\n\n"
                        f"Please trigger the Review & Guidance Agent to deliver feedback:\n"
                        f"/review-task intern_id={intern.id} task_id={task.id} code=\"{assignment.submission_url}\" notes=\"<your observations>\"\n\n"
                        f"InternOps AI Team"
                    )
                )
        logger.info(f"Mentor review notifications sent for {len(submitted_assignments)} submissions.")
    except Exception as e:
        logger.error(f"Error in mentor review date job: {e}")
    finally:
        db.close()


def milestone_evaluation_90day_job():
    """
    Automation Job: 3-Month (90-Day) Milestone Evaluation.
    Runs daily at midnight. Identifies interns enrolled 90+ days ago who haven't had their
    final milestone evaluation computed, automatically computes composite score & certification verdict,
    and dispatches official certification dossiers.
    """
    logger.info("Executing 90-day milestone evaluation job...")
    db = SessionLocal()
    try:
        today = date.today()
        cutoff_date = today - timedelta(days=90)

        # Interns enrolled 90 or more days ago
        mature_interns = (
            db.query(Intern)
            .filter(
                Intern.status == "active",
                Intern.enrolled_at <= cutoff_date
            )
            .all()
        )

        evaluated_count = 0
        for intern in mature_interns:
            # Check if already evaluated for 90-day milestone
            existing = db.query(MilestoneEvaluation).filter(
                MilestoneEvaluation.intern_id == intern.id,
                MilestoneEvaluation.milestone_day == 90
            ).first()

            if not existing:
                res = TaskService.evaluate_intern(db, intern_id=intern.id, milestone_day=90)
                if res["success"]:
                    evaluated_count += 1
                    logger.info(f"Generated 90-day verdict for Intern #{intern.id} ({intern.full_name}): {res['verdict']}")

        logger.info(f"90-day milestone evaluation check complete. {evaluated_count} interns evaluated.")
    except Exception as e:
        logger.error(f"Error in 90-day milestone evaluation job: {e}")
    finally:
        db.close()


def start_scheduler():
    """Registers and starts all automation workflows."""
    if not scheduler.running:
        # 1. Daily standup prompt at 09:00 daily
        scheduler.add_job(
            daily_standup_prompt_job,
            "cron",
            hour=9,
            minute=0,
            id="daily_standup_prompt",
            replace_existing=True
        )

        # 2. Dynamic Deadline Monitor (T + 2 days alert) - every 4 hours
        scheduler.add_job(
            dynamic_deadline_alert_job,
            "interval",
            hours=4,
            id="dynamic_deadline_alert",
            replace_existing=True
        )

        # 3. Mentor Review Date Monitor (T + 3 days) - runs at 10:00 daily
        scheduler.add_job(
            mentor_review_date_job,
            "cron",
            hour=10,
            minute=0,
            id="mentor_review_date",
            replace_existing=True
        )

        # 4. 90-Day Milestone & Final Verdict Trigger - runs at 00:30 daily
        scheduler.add_job(
            milestone_evaluation_90day_job,
            "cron",
            hour=0,
            minute=30,
            id="milestone_evaluation_90day",
            replace_existing=True
        )

        scheduler.start()
        logger.info("APScheduler initialized with all 4 automated workflow jobs.")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped.")
