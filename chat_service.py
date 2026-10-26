import re
import shlex
import json
import logging
from datetime import datetime, date, timedelta
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Cohort, Intern, Task, InternTask, ChatMessage, CheckIn
from app.services.task_service import TaskService
from app.services.evaluation_engine import EvaluationEngine

logger = logging.getLogger("internops.chat")


def parse_kv_args(text: str) -> Dict[str, str]:
    """
    Parses key=value arguments from a string, handling quoted values.
    Supports both key=value and positional arguments where applicable.
    """
    args: Dict[str, str] = {}
    try:
        tokens = shlex.split(text)
        positional = []
        for token in tokens:
            if "=" in token:
                k, v = token.split("=", 1)
                args[k.strip().lower()] = v.strip()
            else:
                positional.append(token)
        if positional:
            args["_positional"] = " ".join(positional)
    except Exception:
        # Regex fallback in case of unclosed quotes
        matches = re.findall(r'(\w+)=(?:"([^"]*)"|\'([^\']*)\'|(\S+))', text)
        for m in matches:
            key = m[0].lower()
            val = m[1] or m[2] or m[3]
            args[key] = val
    return args


class ChatService:
    @classmethod
    def handle_message(cls, db: Session, user_email: str, text: str) -> Dict[str, Any]:
        """
        Main entry point for incoming chat webhook messages.
        Dispatches slash commands or forwards to conversational NLP router.
        """
        text = text.strip()

        # Log inbound message in database
        user_msg = ChatMessage(user_email=user_email, role="user", content=text)
        db.add(user_msg)
        db.commit()

        if text.startswith("/"):
            response_data = cls._handle_slash_command(db, user_email, text)
        else:
            response_data = cls._handle_natural_language(db, user_email, text)

        # Log outbound message
        assistant_msg = ChatMessage(
            user_email=user_email,
            role="assistant",
            content=response_data.get("reply", ""),
            metadata_json=json.dumps(response_data.get("data", {}))
        )
        db.add(assistant_msg)
        db.commit()

        return response_data

    @classmethod
    def _handle_slash_command(cls, db: Session, user_email: str, text: str) -> Dict[str, Any]:
        parts = text.split(maxsplit=1)
        command = parts[0].lower()
        arg_str = parts[1] if len(parts) > 1 else ""
        args = parse_kv_args(arg_str)

        if command == "/assign-task":
            return cls._cmd_assign_task(db, user_email, args)
        elif command == "/review-task":
            return cls._cmd_review_task(db, user_email, args, arg_str)
        elif command == "/leaderboard":
            return cls._cmd_leaderboard(db, args)
        elif command == "/final-verdict":
            return cls._cmd_final_verdict(db, args, arg_str)
        elif command == "/status":
            return cls._cmd_status(db, args)
        elif command == "/interns":
            return cls._cmd_interns(db, args)
        elif command == "/submit":
            return cls._cmd_submit(db, user_email, args)
        elif command == "/checkin":
            return cls._cmd_checkin(db, user_email, args)
        elif command in ("/help", "/start"):
            return cls._cmd_help()
        else:
            return {
                "reply": (
                    f"Unknown command: `{command}`.\n"
                    "Available commands: `/assign-task`, `/review-task [intern_id]`, `/leaderboard`, `/final-verdict`, `/status`, `/submit`, `/checkin`, `/help`."
                ),
                "data": {"error": "unknown_command"}
            }

    @classmethod
    def _cmd_assign_task(cls, db: Session, user_email: str, args: Dict[str, str]) -> Dict[str, Any]:
        cohort_id_str = args.get("cohort") or "1"
        title = args.get("title")
        spec = args.get("spec")

        # Fallback parsing for natural/positional syntax: /assign-task Task 1 spec="..."
        if not title and "_positional" in args:
            pos = args["_positional"]
            if "title=" not in pos and spec:
                title = pos

        if not title or not spec:
            return {
                "reply": (
                    "⚠️ **Missing arguments for `/assign-task`**\n\n"
                    "**Usage:** `/assign-task cohort=1 title=\"<Task Title>\" spec=\"<Task Spec>\"`\n\n"
                    "⚡ *Note: Dynamic deadline ($T + 2\\text{ days}$) and review date ($T + 3\\text{ days}$) will be automatically calculated and scheduled!*"
                ),
                "data": {"error": "missing_arguments"}
            }

        try:
            cohort_id = int(cohort_id_str)
        except ValueError:
            return {
                "reply": f"⚠️ Invalid cohort ID '{cohort_id_str}'. Must be an integer.",
                "data": {"error": "invalid_cohort_id"}
            }

        result = TaskService.assign_task_to_cohort(
            db=db,
            cohort_id=cohort_id,
            title=title,
            spec=spec,
            assigned_by=user_email
        )

        if not result["success"]:
            return {
                "reply": f"❌ Failed to assign task: {result.get('error')}",
                "data": result
            }

        reply = (
            f"🚀 **Assignment Dispatcher Success!**\n\n"
            f"**Task #{result['task_id']} — '{result['title']}'** has been successfully dispatched to **Cohort #{result['cohort_id']} ({result['cohort_name']})**.\n\n"
            f"📅 **Dynamic Timetable Calculated:**\n"
            f"• **Submission Deadline ($T + 2\\text{{ days}}$):** `{result['due_date']}` 23:59 UTC\n"
            f"• **Mentor Review Date ($T + 3\\text{{ days}}$):** `{result['review_date']}`\n\n"
            f"📬 **Distribution Metrics:**\n"
            f"• Enrolled Interns: **{result['assigned_count']}**\n"
            f"• Notification Emails Dispatched: **{result['emails_sent']}** "
            f"({'DRY RUN MODE - logged to console' if settings.DRY_RUN_EMAIL else 'SMTP LIVE'})\n"
            f"• Assigned by: `{result['assigned_by']}`\n\n"
            f"📋 **Specification:**\n"
            f"> {spec}\n\n"
            f"_Interns can submit their code using `/submit task_id={result['task_id']} url=<repo_url>`._"
        )

        return {"reply": reply, "data": result}

    @classmethod
    def _cmd_review_task(cls, db: Session, user_email: str, args: Dict[str, str], raw_arg_str: str) -> Dict[str, Any]:
        """
        Review & Guidance Agent handler.
        Supports:
        /review-task intern_id=42 task_id=1 code="https://github.com/..." notes="Needs test coverage and JWT validation"
        or shorthand:
        /review-task 42 task=1 notes="Needs input sanitization"
        """
        # Resolve intern_id
        intern_id_str = args.get("intern_id") or args.get("intern")
        if not intern_id_str and "_positional" in args:
            tokens = args["_positional"].split()
            if tokens and tokens[0].isdigit():
                intern_id_str = tokens[0]

        # Resolve task_id
        task_id_str = args.get("task_id") or args.get("task")
        if not task_id_str:
            # Default to latest assigned task for this intern if not explicitly provided
            if intern_id_str and intern_id_str.isdigit():
                last_assignment = db.query(InternTask).filter(InternTask.intern_id == int(intern_id_str)).order_by(InternTask.id.desc()).first()
                if last_assignment:
                    task_id_str = str(last_assignment.task_id)

        code_url = args.get("code") or args.get("url") or args.get("link")
        mentor_notes = args.get("notes") or args.get("feedback") or ""
        score_str = args.get("score")

        if not intern_id_str or not task_id_str or not mentor_notes:
            return {
                "reply": (
                    "⚠️ **Review & Guidance Agent Syntax:**\n\n"
                    "`/review-task intern_id=<id> task_id=<task_id> [code=\"<github_url>\"] notes=\"<feedback/corrections>\" [score=<0-100>]`\n\n"
                    "**Example:**\n"
                    "`/review-task intern_id=1 task_id=1 code=\"https://github.com/intern001/api\" notes=\"Missing unit tests for edge cases and input validation is incomplete.\"`"
                ),
                "data": {"error": "missing_arguments"}
            }

        try:
            intern_id = int(intern_id_str)
            task_id = int(task_id_str)
            score = int(score_str) if score_str and score_str.isdigit() else None
        except ValueError:
            return {"reply": "⚠️ Intern ID and Task ID must be numbers.", "data": {"error": "invalid_types"}}

        result = TaskService.review_task_with_guidance(
            db=db,
            intern_id=intern_id,
            task_id=task_id,
            mentor_notes=mentor_notes,
            submission_url=code_url,
            score=score
        )

        if not result["success"]:
            return {"reply": f"❌ {result.get('error')}", "data": result}

        status_emoji = "✅" if result["status"] == "approved" else "🔄"
        status_label = "Approved" if result["status"] == "approved" else "Revision Requested"

        corrections_bullets = "\n".join([f"• {c}" for c in result["corrections"]])

        reply = (
            f"🤖 **InternOps Review & Guidance Agent Activated!**\n\n"
            f"Review processed for **{result['intern_name']} (Intern #{result['intern_id']})** on **'{result['task_title']}'**:\n\n"
            f"• **Revision Round:** #{result['revision_number']}\n"
            f"• **Evaluation Score:** **{result['score']} / 100**\n"
            f"• **Status:** {status_emoji} **{status_label}**\n\n"
            f"🛠️ **Extracted Correction Items:**\n"
            f"{corrections_bullets}\n\n"
            f"💬 **Actionable & Encouraging Suggestions Generated:**\n"
            f"{result['guidance']}\n\n"
            f"✉️ *Guidance report dispatched to `{result['intern_name']}` with mentor CC'd.*"
        )

        return {"reply": reply, "data": result}

    @classmethod
    def _cmd_leaderboard(cls, db: Session, args: Dict[str, str]) -> Dict[str, Any]:
        cohort_id = int(args["cohort"]) if "cohort" in args and args["cohort"].isdigit() else 1
        limit = int(args["limit"]) if "limit" in args and args["limit"].isdigit() else 10

        res = EvaluationEngine.get_cohort_leaderboard(db, cohort_id=cohort_id, limit=limit)
        if not res["success"]:
            return {"reply": f"❌ {res.get('error')}", "data": res}

        lines = [
            f"🏆 **InternOps AI Cohort #{res['cohort_id']} Leaderboard**\n",
            f"*Tracking {res['total_interns']} enrolled interns across multi-stage milestones:*\n"
        ]

        for item in res["leaderboard"]:
            lines.append(
                f"**#{item['rank']} {item['badge']}** — **{item['name']}** (`{item['email']}`)\n"
                f"  • Composite Score: **{item['composite_score']}** | Avg Score: **{item['avg_score']}%**\n"
                f"  • Completed Tasks: **{item['completed_tasks']}/{item['total_tasks']}** | Revisions: **{item['revisions_count']}** | Standups: **{item['checkins_count']}**"
            )

        lines.append(f"\n_Showing top {len(res['leaderboard'])} of {res['total_ranked']} ranked interns. Run `/final-verdict [intern_id]` for detailed milestone dossiers._")

        return {"reply": "\n".join(lines), "data": res}

    @classmethod
    def _cmd_final_verdict(cls, db: Session, args: Dict[str, str], raw_arg_str: str) -> Dict[str, Any]:
        intern_id_str = args.get("intern_id") or args.get("intern")
        if not intern_id_str and "_positional" in args:
            tokens = args["_positional"].split()
            if tokens and tokens[0].isdigit():
                intern_id_str = tokens[0]

        if not intern_id_str:
            # If no intern specified, check cohort wide status or suggest syntax
            return {
                "reply": (
                    "⚠️ **Final Verdict & 3-Month Milestone Evaluation**\n\n"
                    "**Usage:** `/final-verdict intern_id=<id>` (or `/final-verdict <id>`)\n\n"
                    "**Example:** `/final-verdict intern_id=1`\n"
                    "This calculates aggregate 90-day metrics (completion %, revision velocity, avg score, standups) and issues the verifiable certification verdict."
                ),
                "data": {"error": "missing_intern_id"}
            }

        try:
            intern_id = int(intern_id_str)
        except ValueError:
            return {"reply": f"⚠️ Invalid intern ID '{intern_id_str}'. Must be a number.", "data": {"error": "invalid_id"}}

        res = TaskService.evaluate_intern(db, intern_id=intern_id, milestone_day=90)
        if not res["success"]:
            return {"reply": f"❌ {res.get('error')}", "data": res}

        m = res["metrics"]
        reply = (
            f"🎓 **Official 3-Month Milestone Certification Verdict**\n\n"
            f"**Candidate:** {res['intern_name']} (Intern #{res['intern_id']})\n"
            f"**Cohort:** #{res['cohort_id']}\n"
            f"**Milestone Horizon:** 90-Day Full Program Lifecycle\n\n"
            f"### 🎖️ Official Verdict: {res['verdict']}\n"
            f"**Verification ID:** `{res['certificate_id']}`\n\n"
            f"### 📈 Aggregate Performance Dashboard:\n"
            f"• **Composite Score:** **{m['composite_score']} / 100** ({res['tier']})\n"
            f"• **Task Completion Rate:** {m['completion_rate']:.1f}% ({m['completed_tasks']}/{m['total_assigned']} tasks approved)\n"
            f"• **Average Code Score:** {m['avg_score']:.1f} / 100\n"
            f"• **Multi-Stage Revision Efficiency:** {m['revision_efficiency']:.1f}% ({m['total_revisions']} revision cycles logged)\n"
            f"• **Standup Consistency Rate:** {m['standup_rate']:.1f}%\n\n"
            f"📜 *Verifiable certificate dossier generated and emailed to intern, mentor, and talent operations.*"
        )

        return {"reply": reply, "data": res}

    @classmethod
    def _cmd_status(cls, db: Session, args: Dict[str, str]) -> Dict[str, Any]:
        cohort_id = int(args["cohort"]) if "cohort" in args and args["cohort"].isdigit() else None
        res = TaskService.get_cohort_status(db, cohort_id)

        if not res["success"]:
            return {"reply": f"❌ {res.get('error')}", "data": res}

        lines = ["📊 **InternOps Status Overview:**\n"]
        for c in res["cohorts"]:
            lines.append(f"**Cohort #{c['id']} — {c['name']}** (Total Active Interns: {c['total_interns']})")
            if not c["tasks"]:
                lines.append("  _No tasks assigned yet._")
            else:
                for t in c["tasks"]:
                    lines.append(
                        f"  • **Task #{t['id']}**: {t['title']} | "
                        f"Due: {t['due_date']} (Review: {t['review_date']}) | "
                        f"Assigned: {t['total_assigned']} | "
                        f"Submitted: {t['submitted']} | "
                        f"Reviewed: {t['reviewed']}"
                    )
            lines.append("")

        return {"reply": "\n".join(lines).strip(), "data": res}

    @classmethod
    def _cmd_interns(cls, db: Session, args: Dict[str, str]) -> Dict[str, Any]:
        cohort_id = int(args["cohort"]) if "cohort" in args and args["cohort"].isdigit() else None
        query = db.query(Intern)
        if cohort_id:
            query = query.filter(Intern.cohort_id == cohort_id)

        total = query.count()
        interns = query.limit(20).all()

        if total == 0:
            return {"reply": "No interns found.", "data": {"total": 0}}

        lines = [f"👥 **Interns List** (Showing {len(interns)} of {total}):\n"]
        for i in interns:
            lines.append(f"• **#{i.id:03d} {i.full_name}** (`{i.email}`) | Mentor: `{i.mentor_email}` | Cohort #{i.cohort_id}")

        if total > len(interns):
            lines.append(f"\n_...and {total - len(interns)} more interns in this batch._")

        return {"reply": "\n".join(lines), "data": {"total": total, "sample_count": len(interns)}}

    @classmethod
    def _cmd_submit(cls, db: Session, user_email: str, args: Dict[str, str]) -> Dict[str, Any]:
        task_id_str = args.get("task_id") or args.get("task")
        url = args.get("url") or args.get("link")
        notes = args.get("notes", "")

        if not task_id_str or not url:
            return {
                "reply": "⚠️ **Usage:** `/submit task_id=<id> url=<link_to_work> [notes=\"<optional notes>\"]`",
                "data": {"error": "missing_arguments"}
            }

        try:
            task_id = int(task_id_str)
        except ValueError:
            return {"reply": "⚠️ `task_id` must be an integer.", "data": {"error": "invalid_task_id"}}

        res = TaskService.submit_task(db, user_email=user_email, task_id=task_id, submission_url=url, notes=notes)
        if not res["success"]:
            return {"reply": f"❌ {res.get('error')}", "data": res}

        return {
            "reply": f"🚀 **{res['message']}**\nYour mentor has been notified. The Review & Guidance Agent will review your revision.",
            "data": res
        }

    @classmethod
    def _cmd_checkin(cls, db: Session, user_email: str, args: Dict[str, str]) -> Dict[str, Any]:
        update = args.get("update")
        blockers = args.get("blockers", "None")

        if not update:
            return {
                "reply": "⚠️ **Usage:** `/checkin update=\"<what you accomplished today>\" [blockers=\"<blockers>\"]`",
                "data": {"error": "missing_update"}
            }

        intern = db.query(Intern).filter(Intern.email == user_email).first()
        if not intern:
            return {"reply": f"❌ No intern found with email {user_email}.", "data": {"error": "not_found"}}

        checkin = CheckIn(
            intern_id=intern.id,
            date=date.today(),
            status_update=update,
            blockers=blockers
        )
        db.add(checkin)
        db.commit()

        return {
            "reply": f"✅ **Check-in recorded for {intern.full_name}** ({date.today().isoformat()}). Streak updated for milestone evaluation!",
            "data": {"checkin_id": checkin.id}
        }

    @classmethod
    def _cmd_help(cls) -> Dict[str, Any]:
        help_text = (
            "🤖 **InternOps AI — Automated Operations & Workflow Architecture**\n\n"
            "**Core Command Surface:**\n\n"
            "• `/assign-task cohort=<id> title=\"<title>\" spec=\"<spec>\"`\n"
            "  *Assignment Dispatcher*: Bulk-assigns task, auto-calculates dynamic deadlines ($T + 2\\text{ days}$) and review dates ($T + 3\\text{ days}$), and dispatches notifications to all 100 interns.\n\n"
            "• `/review-task intern_id=<id> task_id=<id> [code=\"<url>\"] notes=\"<feedback>\" [score=<0-100>]`\n"
            "  *Review & Guidance Agent*: Extracts correction items, generates actionable & encouraging suggestions, tracks multi-stage revisions, and emails the intern.\n\n"
            "• `/leaderboard [cohort=<id>]`\n"
            "  *Cohort Leaderboard*: Real-time ranking by composite score, average grade, revision velocity, and check-in streak.\n\n"
            "• `/final-verdict intern_id=<id>`\n"
            "  *3-Month Milestone & Evaluation*: Evaluates 90-day progress, calculates composite metrics, and generates verified certification verdict.\n\n"
            "• `/submit task_id=<id> url=\"<url>\" [notes=\"...\"]`\n"
            "  Submit task work or revisions as an intern.\n\n"
            "• `/checkin update=\"<progress>\" [blockers=\"...\"]`\n"
            "  Log daily standup progress.\n\n"
            "• `/status [cohort=<id>]` | `/interns [cohort=<id>]`\n"
            "  Cohort status summaries and intern directories.\n\n"
            "_You can also interact conversationally (e.g. 'Assign Task 1 to Cohort 1: spec=Build auth system')!_"
        )
        return {
            "reply": help_text,
            "data": {
                "commands": [
                    "/assign-task",
                    "/review-task",
                    "/leaderboard",
                    "/final-verdict",
                    "/status",
                    "/interns",
                    "/submit",
                    "/checkin",
                    "/help"
                ]
            }
        }

    @classmethod
    def _handle_natural_language(cls, db: Session, user_email: str, text: str) -> Dict[str, Any]:
        """
        Conversational NLP Router:
        Recognizes manager intents such as:
        - "Assign Task 1 to Cohort 1 with spec Build REST API"
        - "Review task for intern 5"
        - "Show me the leaderboard"
        - "Give me the final verdict for intern 1"
        """
        low = text.lower()

        # 1. Natural Language Assignment: "Assign Task 1 to Cohort 1: spec=..."
        assign_match = re.search(r"assign\s+(?:task\s+)?([^\s:]+)\s+to\s+cohort\s+(\d+)(?::\s*|\s+with\s+spec\s+|\s+spec\s*=\s*)(.*)", text, re.IGNORECASE)
        if not assign_match:
            assign_match = re.search(r"assign\s+task\s+(\d+)\s+to\s+cohort\s+(\d+)(.*)", text, re.IGNORECASE)

        if assign_match:
            task_ref = assign_match.group(1).strip()
            cohort_id_str = assign_match.group(2).strip()
            spec_candidate = assign_match.group(3).strip() if len(assign_match.groups()) >= 3 else ""

            spec = spec_candidate.lstrip(":").strip()
            if spec.lower().startswith("spec="):
                spec = spec[5:].strip().strip('"\'')
            if not spec:
                spec = f"Core Engineering Assignment: {task_ref}"

            title = f"Task {task_ref}" if not task_ref.lower().startswith("task") else task_ref

            try:
                cohort_id = int(cohort_id_str)
                return cls._cmd_assign_task(db, user_email, {
                    "cohort": str(cohort_id),
                    "title": title,
                    "spec": spec
                })
            except Exception as e:
                logger.warning(f"Error handling conversational assignment: {e}")

        # 2. Natural Language Leaderboard: "Show leaderboard", "who is leading"
        if "leaderboard" in low or "rankings" in low or "top interns" in low:
            cohort_id = 1
            cohort_search = re.search(r"cohort\s+(\d+)", low)
            if cohort_search:
                cohort_id = int(cohort_search.group(1))
            return cls._cmd_leaderboard(db, {"cohort": str(cohort_id)})

        # 3. Natural Language Final Verdict: "final verdict for intern 5", "verdict intern 1"
        verdict_search = re.search(r"(?:final\s+verdict|evaluation|certif\w+)\s+(?:for\s+)?intern\s+(\d+)", low)
        if verdict_search:
            intern_id = verdict_search.group(1)
            return cls._cmd_final_verdict(db, {"intern_id": intern_id}, "")

        # 4. Natural Language Review: "Review intern 5", "review task 1 for intern 2"
        review_search = re.search(r"review\s+(?:task\s+(\d+)\s+for\s+)?intern\s+(\d+)(.*)", low)
        if review_search:
            t_id = review_search.group(1) or "1"
            i_id = review_search.group(2)
            extra = review_search.group(3).strip()
            notes = extra if extra else "General mentor review and code quality assessment."
            return cls._cmd_review_task(db, user_email, {
                "intern_id": i_id,
                "task_id": t_id,
                "notes": notes
            }, "")

        # 5. Natural Language Status
        if "status" in low or "summary" in low or "progress" in low:
            return cls._cmd_status(db, {})

        # 6. Natural Language Interns List
        if "intern" in low or "mentor" in low:
            return cls._cmd_interns(db, {})

        # 7. LLM Chat Handling if Anthropic API configured
        if settings.ANTHROPIC_API_KEY:
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
                cohort_count = db.query(Cohort).count()
                intern_count = db.query(Intern).count()
                task_count = db.query(Task).count()

                system_prompt = (
                    "You are InternOps AI, an AI Automation Chatbot & Workflow Architect managing an automated, "
                    f"conversational 3-month internship program for batches of 100 interns. "
                    f"State: {cohort_count} cohorts, {intern_count} interns, {task_count} tasks. "
                    "You excel at dynamic task dispatching (T+2 deadline, T+3 review date), review guidance with multi-stage revisions, "
                    "leaderboards, and 90-day final certification verdicts. Respond with helpfulness, precision, and authority."
                )

                response = client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=800,
                    system=system_prompt,
                    messages=[{"role": "user", "content": text}]
                )
                return {"reply": response.content[0].text, "data": {"source": "anthropic"}}
            except Exception as e:
                logger.warning(f"Anthropic chat fallback: {e}")

        # Fallback in-character conversational reply
        return {
            "reply": (
                f"👋 **InternOps AI Online & Listening.**\n\n"
                f"I received your inquiry: *\"{text}\"*\n\n"
                "As your **AI Automation Chatbot & Workflow Architect**, I can:\n"
                "• **Dispatch tasks** dynamically: `Assign Task 1 to Cohort 1: spec=Build REST API` (Auto-schedules $T+2\\text{ deadline}$ and $T+3\\text{ review date}$).\n"
                "• **Analyze code & guide interns**: `/review-task intern_id=1 task_id=1 notes=\"Needs input validation\"`.\n"
                "• **Track cohort performance**: `/leaderboard`.\n"
                "• **Generate 90-day certification verdicts**: `/final-verdict intern_id=1`.\n\n"
                "Type `/help` to view all command specifications!"
            ),
            "data": {"source": "internops_persona"}
        }
