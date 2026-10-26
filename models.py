from datetime import datetime, date
from typing import Generator
from sqlalchemy import create_engine, Column, Integer, Float, String, Text, Date, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session
from app.config import settings

# Handle PostgreSQL URI protocol compatibility (postgres:// -> postgresql://)
db_url = settings.DATABASE_URL
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

connect_args = {}
if db_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(db_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Cohort(Base):
    __tablename__ = "cohorts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    start_date = Column(Date, nullable=False, default=date.today)
    end_date = Column(Date, nullable=True)
    status = Column(String(50), default="active")
    created_at = Column(DateTime, default=datetime.utcnow)

    interns = relationship("Intern", back_populates="cohort", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="cohort", cascade="all, delete-orphan")
    evaluations = relationship("MilestoneEvaluation", back_populates="cohort", cascade="all, delete-orphan")


class Intern(Base):
    __tablename__ = "interns"

    id = Column(Integer, primary_key=True, index=True)
    cohort_id = Column(Integer, ForeignKey("cohorts.id", ondelete="CASCADE"), nullable=False)
    full_name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    mentor_email = Column(String(255), nullable=False)
    status = Column(String(50), default="active")
    enrolled_at = Column(Date, default=date.today)
    created_at = Column(DateTime, default=datetime.utcnow)

    cohort = relationship("Cohort", back_populates="interns")
    tasks = relationship("InternTask", back_populates="intern", cascade="all, delete-orphan")
    revisions = relationship("TaskRevision", back_populates="intern", cascade="all, delete-orphan")
    check_ins = relationship("CheckIn", back_populates="intern", cascade="all, delete-orphan")
    evaluations = relationship("MilestoneEvaluation", back_populates="intern", cascade="all, delete-orphan")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    cohort_id = Column(Integer, ForeignKey("cohorts.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    spec = Column(Text, nullable=False)
    due_date = Column(Date, nullable=True)        # Dynamic deadline: T + 2 days
    review_date = Column(Date, nullable=True)     # Dynamic review date: T + 3 days
    assigned_by = Column(String(255), default="manager@example.com")
    created_at = Column(DateTime, default=datetime.utcnow)

    cohort = relationship("Cohort", back_populates="tasks")
    assignments = relationship("InternTask", back_populates="task", cascade="all, delete-orphan")
    revisions = relationship("TaskRevision", back_populates="task", cascade="all, delete-orphan")


class InternTask(Base):
    __tablename__ = "intern_tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    intern_id = Column(Integer, ForeignKey("interns.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(50), default="assigned")  # assigned, in_progress, submitted, revision_requested, reviewed, approved
    submission_url = Column(Text, nullable=True)
    submission_notes = Column(Text, nullable=True)
    feedback = Column(Text, nullable=True)
    score = Column(Integer, nullable=True)
    revision_count = Column(Integer, default=0)
    due_date = Column(Date, nullable=True)
    review_date = Column(Date, nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("task_id", "intern_id", name="uq_task_intern"),
    )

    task = relationship("Task", back_populates="assignments")
    intern = relationship("Intern", back_populates="tasks")
    revisions = relationship("TaskRevision", back_populates="intern_task", cascade="all, delete-orphan")


class TaskRevision(Base):
    __tablename__ = "task_revisions"

    id = Column(Integer, primary_key=True, index=True)
    intern_task_id = Column(Integer, ForeignKey("intern_tasks.id", ondelete="CASCADE"), nullable=True)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    intern_id = Column(Integer, ForeignKey("interns.id", ondelete="CASCADE"), nullable=False)
    revision_number = Column(Integer, nullable=False, default=1)
    submission_url = Column(Text, nullable=True)
    mentor_notes = Column(Text, nullable=True)
    extracted_corrections = Column(Text, nullable=True)  # JSON or bullet list of action items
    ai_guidance = Column(Text, nullable=True)             # Actionable & encouraging feedback
    score = Column(Integer, nullable=True)
    status = Column(String(50), default="revision_requested")  # revision_requested, approved
    created_at = Column(DateTime, default=datetime.utcnow)

    intern_task = relationship("InternTask", back_populates="revisions")
    task = relationship("Task", back_populates="revisions")
    intern = relationship("Intern", back_populates="revisions")


class MilestoneEvaluation(Base):
    __tablename__ = "milestone_evaluations"

    id = Column(Integer, primary_key=True, index=True)
    intern_id = Column(Integer, ForeignKey("interns.id", ondelete="CASCADE"), nullable=False)
    cohort_id = Column(Integer, ForeignKey("cohorts.id", ondelete="CASCADE"), nullable=False)
    milestone_day = Column(Integer, default=90)
    completion_rate = Column(Float, nullable=False)
    avg_score = Column(Float, nullable=False)
    revision_efficiency = Column(Float, nullable=False)
    standup_rate = Column(Float, nullable=False)
    composite_score = Column(Float, nullable=False)
    verdict = Column(String(100), nullable=False)
    certificate_id = Column(String(100), unique=True, nullable=False)
    dossier_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    intern = relationship("Intern", back_populates="evaluations")
    cohort = relationship("Cohort", back_populates="evaluations")


class CheckIn(Base):
    __tablename__ = "check_ins"

    id = Column(Integer, primary_key=True, index=True)
    intern_id = Column(Integer, ForeignKey("interns.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False, default=date.today)
    status_update = Column(Text, nullable=False)
    blockers = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    intern = relationship("Intern", back_populates="check_ins")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    user_email = Column(String(255), nullable=False, index=True)
    role = Column(String(50), nullable=False)  # user, assistant
    content = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    """Initializes tables in database."""
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Dependency for yielding db session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
