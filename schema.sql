-- Schema for InternOps AI
-- Supports PostgreSQL and SQLite
-- Autonomous operations, task distribution, AI review guidance, and 3-month milestone evaluation

CREATE TABLE IF NOT EXISTS cohorts (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE,
    status VARCHAR(50) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS interns (
    id SERIAL PRIMARY KEY,
    cohort_id INTEGER NOT NULL REFERENCES cohorts(id) ON DELETE CASCADE,
    full_name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    mentor_email VARCHAR(255) NOT NULL,
    status VARCHAR(50) DEFAULT 'active',
    enrolled_at DATE DEFAULT CURRENT_DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tasks (
    id SERIAL PRIMARY KEY,
    cohort_id INTEGER NOT NULL REFERENCES cohorts(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    spec TEXT NOT NULL,
    due_date DATE,           -- Dynamic deadline: T + 2 days
    review_date DATE,        -- Marked review date: T + 3 days
    assigned_by VARCHAR(255) DEFAULT 'manager@example.com',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS intern_tasks (
    id SERIAL PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    intern_id INTEGER NOT NULL REFERENCES interns(id) ON DELETE CASCADE,
    status VARCHAR(50) DEFAULT 'assigned', -- assigned, submitted, revision_requested, reviewed, approved
    submission_url TEXT,
    submission_notes TEXT,
    feedback TEXT,
    score INTEGER,
    revision_count INTEGER DEFAULT 0,
    due_date DATE,
    review_date DATE,
    submitted_at TIMESTAMP,
    reviewed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_task_intern UNIQUE (task_id, intern_id)
);

CREATE TABLE IF NOT EXISTS task_revisions (
    id SERIAL PRIMARY KEY,
    intern_task_id INTEGER REFERENCES intern_tasks(id) ON DELETE CASCADE,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    intern_id INTEGER NOT NULL REFERENCES interns(id) ON DELETE CASCADE,
    revision_number INTEGER NOT NULL DEFAULT 1,
    submission_url TEXT,
    mentor_notes TEXT,
    extracted_corrections TEXT,
    ai_guidance TEXT,
    score INTEGER,
    status VARCHAR(50) DEFAULT 'revision_requested', -- revision_requested, approved
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS milestone_evaluations (
    id SERIAL PRIMARY KEY,
    intern_id INTEGER NOT NULL REFERENCES interns(id) ON DELETE CASCADE,
    cohort_id INTEGER NOT NULL REFERENCES cohorts(id) ON DELETE CASCADE,
    milestone_day INTEGER DEFAULT 90,
    completion_rate FLOAT NOT NULL,
    avg_score FLOAT NOT NULL,
    revision_efficiency FLOAT NOT NULL,
    standup_rate FLOAT NOT NULL,
    composite_score FLOAT NOT NULL,
    verdict VARCHAR(100) NOT NULL,
    certificate_id VARCHAR(100) UNIQUE NOT NULL,
    dossier_text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS check_ins (
    id SERIAL PRIMARY KEY,
    intern_id INTEGER NOT NULL REFERENCES interns(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    status_update TEXT NOT NULL,
    blockers TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id SERIAL PRIMARY KEY,
    user_email VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    metadata_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
