import re
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from app.config import settings

logger = logging.getLogger("internops.guidance")

class GuidanceAgent:
    """
    Review & Guidance Agent:
    Extracts correction items from mentor reviews or code submissions,
    and synthesizes actionable, encouraging suggestions to elevate the intern's work.
    """

    @classmethod
    def generate_review_guidance(
        cls,
        task_title: str,
        task_spec: str,
        submission_url: Optional[str],
        mentor_notes: str,
        revision_number: int
    ) -> Dict[str, Any]:
        """
        Extracts concrete action items and generates an encouraging, high-impact review report.
        Uses Anthropic Claude if configured; otherwise utilizes the built-in rule-based analysis engine.
        """
        # Try LLM if API key is present
        if settings.ANTHROPIC_API_KEY:
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

                prompt = (
                    f"You are the InternOps AI Review & Guidance Agent.\n"
                    f"Task: {task_title}\n"
                    f"Task Spec: {task_spec}\n"
                    f"Submission URL: {submission_url or 'None'}\n"
                    f"Revision Round: #{revision_number}\n"
                    f"Mentor Feedback / Notes: {mentor_notes}\n\n"
                    f"Instructions:\n"
                    f"1. Extract specific correction items as a JSON list under key 'corrections'.\n"
                    f"2. Generate an actionable, encouraging, supportive guidance message for the intern under 'guidance'.\n"
                    f"3. Determine if this requires revision ('revision_requested') or is ready for approval ('approved') under 'verdict_status'.\n"
                    f"Output strictly valid JSON with keys: 'corrections' (list of strings), 'guidance' (markdown string), 'verdict_status' (string)."
                )

                response = client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=1200,
                    messages=[{"role": "user", "content": prompt}]
                )
                raw_text = response.content[0].text
                # Extract JSON if enclosed in markdown
                match = re.search(r"\{.*\}", raw_text, re.DOTALL)
                if match:
                    parsed = json.loads(match.group(0))
                    return {
                        "corrections": parsed.get("corrections", []),
                        "guidance": parsed.get("guidance", ""),
                        "status": parsed.get("verdict_status", "revision_requested")
                    }
            except Exception as e:
                logger.warning(f"LLM guidance generation failed; falling back to heuristic engine: {e}")

        # Built-in Heuristic Analysis Engine
        return cls._heuristic_analysis(task_title, task_spec, submission_url, mentor_notes, revision_number)

    @classmethod
    def _heuristic_analysis(
        cls,
        task_title: str,
        task_spec: str,
        submission_url: Optional[str],
        mentor_notes: str,
        revision_number: int
    ) -> Dict[str, Any]:
        corrections: List[str] = []
        low_notes = (mentor_notes or "").lower()

        # Parse mentor notes into bullet points or sentences
        sentences = [s.strip() for s in re.split(r'[;\n\.\!]', mentor_notes) if len(s.strip()) > 3]

        # Extract domain-specific correction tags
        if any(w in low_notes for w in ["test", "coverage", "mock", "assert", "pytest", "unit"]):
            corrections.append("🧪 **Test Automation**: Increase unit/integration test coverage and verify boundary conditions.")
        if any(w in low_notes for w in ["error", "exception", "validation", "fail", "catch", "try"]):
            corrections.append("🛡️ **Defensive Engineering**: Add comprehensive input validation and structured HTTP error responses.")
        if any(w in low_notes for w in ["style", "lint", "pep8", "format", "clean", "naming"]):
            corrections.append("🧹 **Code Quality & Style**: Format code adhering to team standards (PEP8/Black) and improve variable nomenclature.")
        if any(w in low_notes for w in ["security", "auth", "token", "sql injection", "sanitize", "jwt"]):
            corrections.append("🔒 **Security Hardening**: Enforce authentication middleware, sanitize database queries, and secure token lifecycles.")
        if any(w in low_notes for w in ["perf", "speed", "slow", "async", "index", "latency", "scale"]):
            corrections.append("⚡ **Performance Optimization**: Profile queries, introduce caching/indexing, and use asynchronous execution where appropriate.")
        if any(w in low_notes for w in ["doc", "readme", "comment", "swagger", "openapi"]):
            corrections.append("📚 **Documentation**: Update API documentation, Swagger specs, and include clear local execution instructions in README.")

        # Fallback to direct sentences if no keywords matched
        if not corrections and sentences:
            corrections = [f"📌 **Action Item**: {s}" for s in sentences[:4]]

        if not corrections:
            corrections.append("📌 **Action Item**: Implement requested changes from mentor specifications.")

        # Determine revision need vs approval
        is_approved = any(w in low_notes for w in ["approved", "lgtm", "looks good", "great job", "perfect", "passed", "100/100"])
        status = "approved" if is_approved else "revision_requested"

        # Generate Actionable & Encouraging guidance markdown
        tone_salutation = "🌟 Outstanding progress!" if revision_number > 1 else "👋 Great start on this milestone!"
        if status == "approved":
            guidance = (
                f"{tone_salutation}\n\n"
                f"Your work on **{task_title}** (Revision #{revision_number}) has been reviewed and **approved**! 🎉\n\n"
                f"### 💡 Mentor Feedback Highlights:\n"
                f"> \"{mentor_notes}\"\n\n"
                f"### ✨ Next Steps:\n"
                f"- Merge your pull request if applicable.\n"
                f"- Continue your daily standups via `/checkin` to maintain your momentum for the 90-day certification milestone!"
            )
        else:
            guidance = (
                f"{tone_salutation} You are making steady progress on **{task_title}** (Revision #{revision_number}). "
                f"Our engineering review highlighted key refinement opportunities that will level up your code craftsmanship:\n\n"
                f"### 🛠️ Key Actionable Improvements:\n"
                + "\n".join([f"- {c}" for c in corrections]) + "\n\n"
                f"### 💬 Mentor Notes:\n"
                f"> \"{mentor_notes}\"\n\n"
                f"### 🚀 Next Iteration:\n"
                f"1. Address each action item in your codebase.\n"
                f"2. Push your commits and re-submit your task revision using:\n"
                f"   `/submit task_id=<task_id> url={submission_url or '<repo_url>'} notes=\"Applied mentor feedback\"`\n\n"
                f"_Remember: Senior software engineering is built on iteration. You've got this!_"
            )

        return {
            "corrections": corrections,
            "guidance": guidance,
            "status": status
        }
