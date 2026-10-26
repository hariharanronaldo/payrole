import json
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from app.models import Cohort, Intern, Task, InternTask, TaskRevision, CheckIn
from app.services.email_service import EmailService
from app.services.guidance_agent import GuidanceAgent
from app.services.evaluation_engine import EvaluationEngine


class TaskService:
    @staticmethod
    def assign_task_to_cohort(
        db: Session,
        cohort_id: int,
        title: str,
        spec: str,
        assigned_by: str = "manager@example.com",
        due_date: Optional[date] = None,
        review_date: Optional[date] = None
    ) -> Dict[str, Any]:
        """
        Assignment Dispatcher:
        Accepts task specs, auto-calculates dynamic deadlines (T + 2 days),
        marks review dates (T + 3 days), and dispatches emails to all interns in the cohort.
        """
        cohort = db.query(Cohort).filter(Cohort.id == cohort_id).first()
        if not cohort:
            return {
                "success": False,
                "error": f"Cohort with ID {cohort_id} not found."
            }

        interns = db.query(Intern).filter(
            Intern.cohort_id == cohort_id,
            Intern.status == "active"
        ).all()

        if not interns:
            return {
                "success": False,
                "error": f"Cohort {cohort.name} (ID: {cohort_id}) has no active interns to assign."
            }

        # Auto-calculate dynamic deadlines: T + 2 days submission deadline, T + 3 days review date
        today = date.today()
        calculated_due_date = due_date or (today + timedelta(days=2))
        calculated_review_date = review_date or (today + timedelta(days=3))

        # Create Task record
        task = Task(
            cohort_id=cohort_id,
            title=title,
            spec=spec,
            due_date=calculated_due_date,
            review_date=calculated_review_date,
            assigned_by=assigned_by,
            created_at=datetime.utcnow()
        )
        db.add(task)
        db.flush()  # to obtain task.id

        # Bulk assign to all active cohort interns
        assignments = []
        for intern in interns:
            assignment = InternTask(
                task_id=task.id,
                intern_id=intern.id,
                status="assigned",
                due_date=calculated_due_date,
                review_date=calculated_review_date,
                revision_count=0,
                created_at=datetime.utcnow()
            )
            assignments.append(assignment)
        db.add_all(assignments)
        db.commit()

        # Dispatch emails to all 100 interns
        emails_sent = 0
        due_str = calculated_due_date.isoformat()
        review_str = calculated_review_date.isoformat()

        for intern in interns:
            EmailService.notify_task_assignment(
                intern_name=intern.full_name,
                intern_email=intern.email,
                mentor_email=intern.mentor_email,
                task_title=task.title,
                task_spec=task.spec,
                task_id=task.id,
                due_date=due_str,
                review_date=review_str
            )
            emails_sent += 1

        return {
            "success": True,
            "task_id": task.id,
            "cohort_id": cohort_id,
            "cohort_name": cohort.name,
            "title": title,
            "due_date": due_str,
            "review_date": review_str,
            "assigned_count": len(interns),
            "emails_sent": emails_sent,
            "assigned_by": assigned_by
        }

    @staticmethod
    def review_task_with_guidance(
        db: Session,
        intern_id: int,
        task_id: int,
        mentor_notes: str,
        submission_url: Optional[str] = None,
        score: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Review & Guidance Agent:
        Extracts correction items, generates actionable and encouraging suggestions,
        tracks multi-stage revisions, and dispatches guidance email to the intern.
        """
        intern = db.query(Intern).filter(Intern.id == intern_id).first()
        if not intern:
            return {"success": False, "error": f"Intern with ID #{intern_id} not found."}

        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return {"success": False, "error": f"Task with ID #{task_id} not found."}

        assignment = db.query(InternTask).filter(
            InternTask.task_id == task_id,
            InternTask.intern_id == intern_id
        ).first()

        if not assignment:
            return {"success": False, "error": f"Task #{task_id} is not assigned to Intern #{intern_id}."}

        current_url = submission_url or assignment.submission_url
        revision_number = (assignment.revision_count or 0) + 1

        # Generate AI Guidance & Extract Corrections
        ai_result = GuidanceAgent.generate_review_guidance(
            task_title=task.title,
            task_spec=task.spec,
            submission_url=current_url,
            mentor_notes=mentor_notes,
            revision_number=revision_number
        )

        corrections = ai_result["corrections"]
        guidance = ai_result["guidance"]
        verdict_status = ai_result["status"]

        # If score not explicitly provided, calculate sensible default based on status
        final_score = score
        if final_score is None:
            final_score = 92 if verdict_status == "approved" else max(60, 80 - (len(corrections) * 5))

        # Record Revision in Database
        revision = TaskRevision(
            intern_task_id=assignment.id,
            task_id=task.id,
            intern_id=intern.id,
            revision_number=revision_number,
            submission_url=current_url,
            mentor_notes=mentor_notes,
            extracted_corrections=json.dumps(corrections),
            ai_guidance=guidance,
            score=final_score,
            status=verdict_status,
            created_at=datetime.utcnow()
        )
        db.add(revision)

        # Update assignment state
        assignment.revision_count = revision_number
        assignment.status = "approved" if verdict_status == "approved" else "revision_requested"
        assignment.score = final_score
        assignment.feedback = guidance
        assignment.reviewed_at = datetime.utcnow()
        db.commit()

        # Email guidance to intern
        EmailService.notify_review_guidance(
            intern_name=intern.full_name,
            intern_email=intern.email,
            mentor_email=intern.mentor_email,
            task_title=task.title,
            task_id=task.id,
            revision_number=revision_number,
            score=final_score,
            status=verdict_status,
            corrections=corrections,
            guidance=guidance
        )

        return {
            "success": True,
            "intern_id": intern.id,
            "intern_name": intern.full_name,
            "task_id": task.id,
            "task_title": task.title,
            "revision_number": revision_number,
            "score": final_score,
            "status": verdict_status,
            "corrections": corrections,
            "guidance": guidance,
            "submission_url": current_url
        }

    @staticmethod
    def submit_task(
        db: Session,
        user_email: str,
        task_id: int,
        submission_url: str,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        intern = db.query(Intern).filter(Intern.email == user_email).first()
        if not intern:
            return {"success": False, "error": f"Intern with email {user_email} not found."}

        assignment = db.query(InternTask).filter(
            InternTask.task_id == task_id,
            InternTask.intern_id == intern.id
        ).first()

        if not assignment:
            return {"success": False, "error": f"Task #{task_id} is not assigned to {user_email}."}

        task = db.query(Task).filter(Task.id == task_id).first()

        assignment.status = "submitted"
        assignment.submission_url = submission_url
        assignment.submission_notes = notes
        assignment.submitted_at = datetime.utcnow()
        db.commit()

        EmailService.notify_submission(
            intern_name=intern.full_name,
            intern_email=intern.email,
            mentor_email=intern.mentor_email,
            task_title=task.title if task else f"Task #{task_id}",
            task_id=task_id,
            submission_url=submission_url,
            notes=notes
        )

        return {
            "success": True,
            "message": f"Task #{task_id} successfully submitted by {intern.full_name}.",
            "submission_url": submission_url
        }

    @staticmethod
    def evaluate_intern(
        db: Session,
        intern_id: int,
        milestone_day: int = 90
    ) -> Dict[str, Any]:
        result = EvaluationEngine.evaluate_intern_milestone(db, intern_id, milestone_day)
        if not result["success"]:
            return result

        intern = db.query(Intern).filter(Intern.id == intern_id).first()
        cohort = intern.cohort

        # Dispatch milestone email
        EmailService.notify_milestone_evaluation(
            intern_name=intern.full_name,
            intern_email=intern.email,
            mentor_email=intern.mentor_email,
            cohort_name=cohort.name,
            milestone_day=milestone_day,
            composite_score=result["metrics"]["composite_score"],
            verdict=result["verdict"],
            certificate_id=result["certificate_id"],
            dossier=result["dossier"]
        )

        return result

    @staticmethod
    def get_cohort_status(db: Session, cohort_id: Optional[int] = None) -> Dict[str, Any]:
        query = db.query(Cohort)
        if cohort_id:
            query = query.filter(Cohort.id == cohort_id)
        cohorts = query.all()

        if not cohorts:
            return {"success": False, "error": f"No cohorts found for ID {cohort_id}" if cohort_id else "No cohorts found."}

        cohort_data = []
        for c in cohorts:
            intern_count = db.query(Intern).filter(Intern.cohort_id == c.id).count()
            tasks = db.query(Task).filter(Task.cohort_id == c.id).all()
            task_summaries = []
            for t in tasks:
                total_assigned = db.query(InternTask).filter(InternTask.task_id == t.id).count()
                submitted_count = db.query(InternTask).filter(
                    InternTask.task_id == t.id,
                    InternTask.status.in_(["submitted", "revision_requested", "reviewed", "approved"])
                ).count()
                reviewed_count = db.query(InternTask).filter(
                    InternTask.task_id == t.id,
                    InternTask.status.in_(["reviewed", "approved"])
                ).count()
                task_summaries.append({
                    "id": t.id,
                    "title": t.title,
                    "due_date": t.due_date.isoformat() if t.due_date else None,
                    "review_date": t.review_date.isoformat() if t.review_date else None,
                    "total_assigned": total_assigned,
                    "submitted": submitted_count,
                    "reviewed": reviewed_count
                })

            cohort_data.append({
                "id": c.id,
                "name": c.name,
                "start_date": c.start_date.isoformat() if c.start_date else None,
                "total_interns": intern_count,
                "tasks": task_summaries
            })

        return {"success": True, "cohorts": cohort_data}
