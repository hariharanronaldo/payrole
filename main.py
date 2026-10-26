from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from pathlib import Path

from app.config import settings
from app.models import init_db, get_db, Cohort, Intern, Task, InternTask, ChatMessage, TaskRevision, MilestoneEvaluation
from app.services.chat_service import ChatService
from app.services.task_service import TaskService
from app.services.evaluation_engine import EvaluationEngine
from app.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure tables created and background scheduler running
    init_db()
    start_scheduler()
    yield
    # Shutdown: stop scheduler
    stop_scheduler()


app = FastAPI(
    title="InternOps AI",
    description="Autonomous Operations & Cohort Management Assistant for 3-Month Programs",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Pydantic Schemas
class ChatRequest(BaseModel):
    user_email: str
    text: str


class ChatResponse(BaseModel):
    user_email: str
    text: str
    reply: str
    data: Optional[Dict[str, Any]] = None


class CohortCreate(BaseModel):
    name: str


class AssignTaskRequest(BaseModel):
    cohort_id: int
    title: str
    spec: str
    assigned_by: Optional[str] = "manager@example.com"
    due_date: Optional[str] = None
    review_date: Optional[str] = None


class ReviewTaskRequest(BaseModel):
    intern_id: int
    task_id: int
    mentor_notes: str
    code_url: Optional[str] = None
    score: Optional[int] = None


@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    try:
        cohort_count = db.query(Cohort).count()
        intern_count = db.query(Intern).count()
        task_count = db.query(Task).count()
        revisions_count = db.query(TaskRevision).count()
        evaluations_count = db.query(MilestoneEvaluation).count()
        return {
            "status": "healthy",
            "persona": "InternOps AI",
            "dry_run_email": settings.DRY_RUN_EMAIL,
            "cohort_count": cohort_count,
            "intern_count": intern_count,
            "task_count": task_count,
            "revisions_tracked": revisions_count,
            "milestone_evaluations": evaluations_count,
            "database": "connected"
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


@app.post("/chat", response_model=ChatResponse)
def chat_webhook(payload: ChatRequest, db: Session = Depends(get_db)):
    """
    Main webhook endpoint for inbound chat / email / Slack / CLI integrations.
    Accepts commands such as:
    - /assign-task cohort=1 title="REST API" spec="Build a CRUD API with tests"
    - /review-task intern_id=1 task_id=1 code="https://github.com/..." notes="Needs test coverage"
    - /leaderboard cohort=1
    - /final-verdict intern_id=1
    """
    res = ChatService.handle_message(
        db=db,
        user_email=payload.user_email,
        text=payload.text
    )
    return ChatResponse(
        user_email=payload.user_email,
        text=payload.text,
        reply=res.get("reply", ""),
        data=res.get("data")
    )


@app.get("/api/cohorts")
def list_cohorts(db: Session = Depends(get_db)):
    cohorts = db.query(Cohort).all()
    results = []
    for c in cohorts:
        intern_count = db.query(Intern).filter(Intern.cohort_id == c.id).count()
        task_count = db.query(Task).filter(Task.cohort_id == c.id).count()
        results.append({
            "id": c.id,
            "name": c.name,
            "start_date": c.start_date.isoformat() if c.start_date else None,
            "total_interns": intern_count,
            "total_tasks": task_count,
            "status": c.status
        })
    return results


@app.get("/api/cohorts/{cohort_id}/interns")
def list_cohort_interns(cohort_id: int, limit: int = 100, db: Session = Depends(get_db)):
    interns = db.query(Intern).filter(Intern.cohort_id == cohort_id).limit(limit).all()
    return [
        {
            "id": i.id,
            "full_name": i.full_name,
            "email": i.email,
            "mentor_email": i.mentor_email,
            "status": i.status
        }
        for i in interns
    ]


@app.get("/api/tasks")
def list_tasks(db: Session = Depends(get_db)):
    tasks = db.query(Task).order_by(Task.id.desc()).all()
    results = []
    for t in tasks:
        total = db.query(InternTask).filter(InternTask.task_id == t.id).count()
        submitted = db.query(InternTask).filter(
            InternTask.task_id == t.id,
            InternTask.status.in_(["submitted", "revision_requested", "reviewed", "approved"])
        ).count()
        reviewed = db.query(InternTask).filter(
            InternTask.task_id == t.id,
            InternTask.status.in_(["reviewed", "approved"])
        ).count()
        results.append({
            "id": t.id,
            "cohort_id": t.cohort_id,
            "title": t.title,
            "spec": t.spec,
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "review_date": t.review_date.isoformat() if t.review_date else None,
            "assigned_by": t.assigned_by,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "stats": {
                "total": total,
                "submitted": submitted,
                "reviewed": reviewed
            }
        })
    return results


@app.post("/api/tasks/assign")
def assign_task_api(req: AssignTaskRequest, db: Session = Depends(get_db)):
    res = TaskService.assign_task_to_cohort(
        db=db,
        cohort_id=req.cohort_id,
        title=req.title,
        spec=req.spec,
        assigned_by=req.assigned_by or "manager@example.com"
    )
    if not res["success"]:
        raise HTTPException(status_code=400, detail=res.get("error"))
    return res


@app.post("/api/tasks/review")
def review_task_api(req: ReviewTaskRequest, db: Session = Depends(get_db)):
    res = TaskService.review_task_with_guidance(
        db=db,
        intern_id=req.intern_id,
        task_id=req.task_id,
        mentor_notes=req.mentor_notes,
        submission_url=req.code_url,
        score=req.score
    )
    if not res["success"]:
        raise HTTPException(status_code=400, detail=res.get("error"))
    return res


@app.get("/api/leaderboard")
def get_leaderboard_api(cohort_id: int = 1, limit: int = 10, db: Session = Depends(get_db)):
    res = EvaluationEngine.get_cohort_leaderboard(db, cohort_id=cohort_id, limit=limit)
    if not res["success"]:
        raise HTTPException(status_code=404, detail=res.get("error"))
    return res


@app.get("/api/final-verdict/{intern_id}")
def get_final_verdict_api(intern_id: int, db: Session = Depends(get_db)):
    res = TaskService.evaluate_intern(db, intern_id=intern_id, milestone_day=90)
    if not res["success"]:
        raise HTTPException(status_code=404, detail=res.get("error"))
    return res


@app.get("/api/messages")
def get_recent_messages(limit: int = 50, db: Session = Depends(get_db)):
    msgs = db.query(ChatMessage).order_by(ChatMessage.id.desc()).limit(limit).all()
    return [
        {
            "id": m.id,
            "user_email": m.user_email,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else None
        }
        for m in reversed(msgs)
    ]


# Mount static dashboard
static_path = Path(__file__).resolve().parent.parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def serve_dashboard():
        index_file = static_path / "index.html"
        if index_file.exists():
            return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
        return HTMLResponse(content="<h1>InternOps AI is running</h1>")
else:
    @app.get("/", response_class=HTMLResponse)
    def index():
        return HTMLResponse(content="<h1>InternOps AI is running</h1><p>Visit /docs for OpenAPI documentation.</p>")
