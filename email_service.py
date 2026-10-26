import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional
from app.config import settings

logger = logging.getLogger("internops.email")

class EmailService:
    @staticmethod
    def send_email(
        to_email: str,
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        html_body: Optional[str] = None
    ) -> bool:
        """
        Sends an email or logs it if DRY_RUN_EMAIL is enabled.
        """
        cc_list = cc or []
        recipients = [to_email] + cc_list

        if settings.DRY_RUN_EMAIL:
            cc_str = f" (CC: {', '.join(cc_list)})" if cc_list else ""
            print(f"\n[DRY RUN EMAIL] To: {to_email}{cc_str}\nSubject: {subject}\nBody:\n{body}\n{'-'*60}")
            logger.info(f"[DRY RUN] Sent email to {to_email} with subject '{subject}'")
            return True

        # Production SMTP send
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = settings.SMTP_FROM_EMAIL
            msg["To"] = to_email
            if cc_list:
                msg["Cc"] = ", ".join(cc_list)

            msg.attach(MIMEText(body, "plain"))
            if html_body:
                msg.attach(MIMEText(html_body, "html"))

            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10)
            if settings.SMTP_USE_TLS:
                server.starttls()
            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)

            server.sendmail(settings.SMTP_FROM_EMAIL, recipients, msg.as_string())
            server.quit()
            logger.info(f"Successfully sent email to {to_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False

    @classmethod
    def notify_task_assignment(
        cls,
        intern_name: str,
        intern_email: str,
        mentor_email: str,
        task_title: str,
        task_spec: str,
        task_id: int,
        due_date: str,
        review_date: str
    ) -> bool:
        subject = f"[InternOps] New Task #{task_id} Assigned: {task_title}"
        body = (
            f"Hello {intern_name},\n\n"
            f"A new task has been dispatched to your cohort:\n"
            f"📌 Task #{task_id}: {task_title}\n\n"
            f"⏰ DYNAMIC DEADLINE TIMELINE:\n"
            f"• Submission Deadline (T + 2 days): {due_date} 23:59 UTC\n"
            f"• Mentor Review Date (T + 3 days):  {review_date}\n\n"
            f"📋 SPECIFICATION:\n"
            f"{task_spec}\n\n"
            f"🚀 HOW TO SUBMIT:\n"
            f"When your work is ready, submit via the InternOps command:\n"
            f"/submit task_id={task_id} url=\"https://github.com/your-username/repo-or-pr\" notes=\"Ready for review\"\n\n"
            f"Your mentor ({mentor_email}) is CC'd on this dispatch.\n\n"
            f"Best regards,\n"
            f"InternOps AI - Autonomous Workflow Coordinator"
        )
        return cls.send_email(
            to_email=intern_email,
            subject=subject,
            body=body,
            cc=[mentor_email] if mentor_email else []
        )

    @classmethod
    def notify_submission(
        cls,
        intern_name: str,
        intern_email: str,
        mentor_email: str,
        task_title: str,
        task_id: int,
        submission_url: str,
        notes: Optional[str] = None
    ) -> bool:
        subject = f"[InternOps] Submission Received: {task_title} (Task #{task_id})"
        body = (
            f"Hi Mentor,\n\n"
            f"{intern_name} ({intern_email}) has submitted Task #{task_id}: '{task_title}'.\n\n"
            f"🔗 Submission URL: {submission_url}\n"
            f"💬 Notes: {notes or 'No notes provided'}\n\n"
            f"To review this work, trigger the Review & Guidance Agent:\n"
            f"/review-task intern_id=<id> task_id={task_id} code=\"{submission_url}\" notes=\"<your observations>\"\n\n"
            f"InternOps AI will extract actionable correction items and email the intern.\n\n"
            f"InternOps AI Team"
        )
        return cls.send_email(
            to_email=mentor_email,
            subject=subject,
            body=body,
            cc=[intern_email]
        )

    @classmethod
    def notify_review_guidance(
        cls,
        intern_name: str,
        intern_email: str,
        mentor_email: str,
        task_title: str,
        task_id: int,
        revision_number: int,
        score: Optional[int],
        status: str,
        corrections: List[str],
        guidance: str
    ) -> bool:
        status_label = "✅ Approved" if status == "approved" else "🔄 Revision Requested"
        score_label = f"{score}/100" if score is not None else "Pending"
        subject = f"[InternOps] Code Review & Guidance: {task_title} (Rev #{revision_number}) [{status_label}]"

        corrections_text = "\n".join([f"• {c}" for c in corrections])
        body = (
            f"Hello {intern_name},\n\n"
            f"Your submission for Task #{task_id} ('{task_title}') has been processed by your mentor and the InternOps Review & Guidance Agent.\n\n"
            f"📊 REVIEW SUMMARY:\n"
            f"• Revision Round: #{revision_number}\n"
            f"• Score: {score_label}\n"
            f"• Status: {status_label}\n\n"
            f"🛠️ KEY ACTION ITEMS / CORRECTIONS:\n"
            f"{corrections_text}\n\n"
            f"💡 ACTIONABLE & ENCOURAGING GUIDANCE:\n"
            f"{guidance}\n\n"
            f"If revision is requested, push your updates and re-submit using:\n"
            f"/submit task_id={task_id} url=<link_to_work> notes=\"Revision #{revision_number + 1} addressing feedback\"\n\n"
            f"Best regards,\n"
            f"InternOps AI Guidance Agent\n"
            f"Mentor CC: {mentor_email}"
        )
        return cls.send_email(
            to_email=intern_email,
            subject=subject,
            body=body,
            cc=[mentor_email] if mentor_email else []
        )

    @classmethod
    def notify_milestone_evaluation(
        cls,
        intern_name: str,
        intern_email: str,
        mentor_email: str,
        cohort_name: str,
        milestone_day: int,
        composite_score: float,
        verdict: str,
        certificate_id: str,
        dossier: str
    ) -> bool:
        subject = f"[InternOps] 📜 90-Day Milestone Evaluation Verdict: {intern_name} [{certificate_id}]"
        body = (
            f"Dear {intern_name},\n\n"
            f"Congratulations on completing your {milestone_day}-day internship milestone in {cohort_name}!\n\n"
            f"OFFICIAL VERDICT:\n"
            f"{verdict}\n\n"
            f"• Composite Score: {composite_score} / 100\n"
            f"• Certificate ID: {certificate_id}\n\n"
            f"FULL PERFORMANCE DOSSIER:\n"
            f"{dossier}\n\n"
            f"This verdict has been recorded in the permanent cohort registry.\n\n"
            f"Warm regards,\n"
            f"InternOps AI Certification Board\n"
            f"CC: Mentor ({mentor_email})"
        )
        return cls.send_email(
            to_email=intern_email,
            subject=subject,
            body=body,
            cc=[mentor_email] if mentor_email else []
        )

    @classmethod
    def send_standup_prompt(cls, intern_name: str, intern_email: str) -> bool:
        subject = "[InternOps] Daily Check-in & Standup"
        body = (
            f"Good morning {intern_name}!\n\n"
            f"Please take a minute to submit your daily update by replying with:\n"
            f"/checkin update=\"<what you accomplished today>\" blockers=\"<any blockers or 'none'>\"\n\n"
            f"InternOps AI Team"
        )
        return cls.send_email(to_email=intern_email, subject=subject, body=body)
