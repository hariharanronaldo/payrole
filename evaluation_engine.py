import hashlib
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import Cohort, Intern, Task, InternTask, TaskRevision, MilestoneEvaluation, CheckIn


class EvaluationEngine:
    """
    3-Month Milestone & Performance Evaluation Engine:
    Tracks multi-stage revisions, calculates aggregate performance metrics,
    and produces final certification / performance verdicts at the 90-day mark.
    """

    @classmethod
    def evaluate_intern_milestone(
        cls,
        db: Session,
        intern_id: int,
        milestone_day: int = 90
    ) -> Dict[str, Any]:
        intern = db.query(Intern).filter(Intern.id == intern_id).first()
        if not intern:
            return {"success": False, "error": f"Intern #{intern_id} not found."}

        cohort = intern.cohort

        # 1. Task Metrics
        assignments = db.query(InternTask).filter(InternTask.intern_id == intern_id).all()
        total_assigned = len(assignments)

        completed_tasks = [a for a in assignments if a.status in ("reviewed", "approved")]
        submitted_tasks = [a for a in assignments if a.status in ("submitted", "revision_requested", "reviewed", "approved")]

        completion_rate = (len(completed_tasks) / total_assigned * 100.0) if total_assigned > 0 else 0.0

        scores = [a.score for a in completed_tasks if a.score is not None]
        avg_score = (sum(scores) / len(scores)) if scores else 0.0

        # 2. Multi-Stage Revision Tracking
        revisions = db.query(TaskRevision).filter(TaskRevision.intern_id == intern_id).all()
        total_revisions = len(revisions)
        approved_revisions = [r for r in revisions if r.status == "approved"]

        # Revision efficiency: reward iterative improvement. High if intern takes few cycles or resolves revisions
        if total_revisions == 0:
            revision_efficiency = 85.0 if completion_rate > 0 else 50.0
        else:
            approval_ratio = len(approved_revisions) / total_revisions
            revision_efficiency = min(100.0, max(40.0, approval_ratio * 100.0))

        # 3. Standup & Check-in Consistency
        checkins = db.query(CheckIn).filter(CheckIn.intern_id == intern_id).all()
        total_checkins = len(checkins)
        # Expected ~60 business days over 90 calendar days
        standup_rate = min(100.0, (total_checkins / 60.0) * 100.0) if total_checkins > 0 else 0.0

        # 4. Composite Metric Calculation (0 - 100)
        # Weights: Task Scores (40%), Completion (30%), Revision Efficiency (15%), Standup Consistency (15%)
        composite_score = round(
            (0.40 * avg_score) +
            (0.30 * completion_rate) +
            (0.15 * revision_efficiency) +
            (0.15 * standup_rate),
            1
        )

        # 5. Verdict Classification
        if composite_score >= 90.0:
            verdict = "🏆 PASSED WITH HONORS — Full-Time Offer Recommended"
            tier = "Tier 1: Honors Distinction"
        elif composite_score >= 75.0:
            verdict = "🎓 CERTIFIED — Software Engineering Intern Graduate"
            tier = "Tier 2: Certified Graduate"
        elif composite_score >= 60.0:
            verdict = "📋 CERTIFICATE OF COMPLETION — Proficient with Growth Scope"
            tier = "Tier 3: Standard Completion"
        else:
            verdict = "⚠️ CONDITIONAL — Extended Mentorship Required"
            tier = "Tier 4: Needs Improvement"

        # 6. Generate Verifiable Certificate ID
        raw_hash = hashlib.sha256(f"{intern.id}:{intern.email}:{cohort.id}:{composite_score}".encode()).hexdigest()[:8].upper()
        certificate_id = f"IOPS-2026-C{cohort.id}-{intern.id:03d}-{raw_hash}"

        # 7. Milestone Dossier Text
        dossier = (
            f"# 📜 InternOps AI - 3-Month Performance Dossier\n\n"
            f"**Intern:** {intern.full_name} (`{intern.email}`)\n"
            f"**Cohort:** #{cohort.id} ({cohort.name})\n"
            f"**Milestone Day:** {milestone_day} Days (Full Program Lifecycle)\n"
            f"**Certificate ID:** `{certificate_id}`\n"
            f"**Official Verdict:** {verdict}\n\n"
            f"## 📊 Aggregate Performance Metrics\n"
            f"- **Composite Rating:** **{composite_score} / 100** ({tier})\n"
            f"- **Task Completion Rate:** {completion_rate:.1f}% ({len(completed_tasks)}/{total_assigned} tasks)\n"
            f"- **Average Task Score:** {avg_score:.1f} / 100\n"
            f"- **Multi-Stage Revision Efficiency:** {revision_efficiency:.1f}% ({total_revisions} total revisions recorded)\n"
            f"- **Standup Consistency Rate:** {standup_rate:.1f}% ({total_checkins} check-ins logged)\n\n"
            f"## 🗓️ 3-Month Lifecycle Breakdown\n"
            f"- **Month 1 (Core Foundations & Tooling):** Completed initial onboarding & core architectural tasks.\n"
            f"- **Month 2 (Systems Integration & Revisions):** Handled multi-stage code reviews, mentor feedback loops, and refactoring.\n"
            f"- **Month 3 (Capstone & Production Readiness):** Demonstrated end-to-end delivery, defensive design, and documentation standards.\n\n"
            f"## 📝 Recommendation & Summary\n"
            f"{intern.full_name} has successfully met program milestones with demonstrated competence in automated workflows, revision responsiveness, and engineering rigor. "
            f"Assigned Mentor: `{intern.mentor_email}`."
        )

        # Save or update record in database
        eval_record = db.query(MilestoneEvaluation).filter(
            MilestoneEvaluation.intern_id == intern_id,
            MilestoneEvaluation.milestone_day == milestone_day
        ).first()

        if not eval_record:
            eval_record = MilestoneEvaluation(
                intern_id=intern_id,
                cohort_id=cohort.id,
                milestone_day=milestone_day,
                completion_rate=completion_rate,
                avg_score=avg_score,
                revision_efficiency=revision_efficiency,
                standup_rate=standup_rate,
                composite_score=composite_score,
                verdict=verdict,
                certificate_id=certificate_id,
                dossier_text=dossier
            )
            db.add(eval_record)
        else:
            eval_record.completion_rate = completion_rate
            eval_record.avg_score = avg_score
            eval_record.revision_efficiency = revision_efficiency
            eval_record.standup_rate = standup_rate
            eval_record.composite_score = composite_score
            eval_record.verdict = verdict
            eval_record.certificate_id = certificate_id
            eval_record.dossier_text = dossier

        db.commit()

        return {
            "success": True,
            "intern_id": intern.id,
            "intern_name": intern.full_name,
            "cohort_id": cohort.id,
            "milestone_day": milestone_day,
            "metrics": {
                "composite_score": composite_score,
                "completion_rate": completion_rate,
                "avg_score": avg_score,
                "revision_efficiency": revision_efficiency,
                "standup_rate": standup_rate,
                "total_revisions": total_revisions,
                "completed_tasks": len(completed_tasks),
                "total_assigned": total_assigned
            },
            "verdict": verdict,
            "tier": tier,
            "certificate_id": certificate_id,
            "dossier": dossier
        }

    @classmethod
    def get_cohort_leaderboard(cls, db: Session, cohort_id: int = 1, limit: int = 10) -> Dict[str, Any]:
        """
        Calculates and ranks interns within a cohort based on aggregate performance metrics.
        """
        cohort = db.query(Cohort).filter(Cohort.id == cohort_id).first()
        if not cohort:
            return {"success": False, "error": f"Cohort #{cohort_id} not found."}

        interns = db.query(Intern).filter(Intern.cohort_id == cohort_id, Intern.status == "active").all()
        if not interns:
            return {"success": False, "error": f"No active interns found in Cohort #{cohort_id}."}

        leaderboard = []
        for intern in interns:
            assignments = db.query(InternTask).filter(InternTask.intern_id == intern.id).all()
            completed = [a for a in assignments if a.status in ("reviewed", "approved")]
            scores = [a.score for a in completed if a.score is not None]
            avg_score = (sum(scores) / len(scores)) if scores else 0.0
            revisions_count = db.query(TaskRevision).filter(TaskRevision.intern_id == intern.id).count()
            checkins_count = db.query(CheckIn).filter(CheckIn.intern_id == intern.id).count()

            completion_pct = (len(completed) / len(assignments) * 100.0) if assignments else 0.0

            # Composite ranking score
            rank_score = round((0.6 * avg_score) + (0.3 * completion_pct) + (0.1 * min(100.0, checkins_count * 2.0)), 1)

            leaderboard.append({
                "intern_id": intern.id,
                "name": intern.full_name,
                "email": intern.email,
                "mentor": intern.mentor_email,
                "completed_tasks": len(completed),
                "total_tasks": len(assignments),
                "avg_score": round(avg_score, 1),
                "revisions_count": revisions_count,
                "checkins_count": checkins_count,
                "composite_score": rank_score
            })

        # Sort descending by composite score
        leaderboard.sort(key=lambda x: (x["composite_score"], x["avg_score"]), reverse=True)

        # Attach rank and badges
        for idx, entry in enumerate(leaderboard, start=1):
            entry["rank"] = idx
            if idx == 1:
                entry["badge"] = "🥇 Cohort Leader"
            elif idx <= 3:
                entry["badge"] = "🥈 Top 3 Performer"
            elif idx <= 10:
                entry["badge"] = "🌟 Top 10 Elite"
            elif entry["composite_score"] >= 80:
                entry["badge"] = "🚀 High Contributor"
            else:
                entry["badge"] = "⚡ Active Intern"

        return {
            "success": True,
            "cohort_id": cohort.id,
            "cohort_name": cohort.name,
            "total_interns": len(interns),
            "leaderboard": leaderboard[:limit],
            "total_ranked": len(leaderboard)
        }
