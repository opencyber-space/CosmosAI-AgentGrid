from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras

from ..config import PostgresConfig

_SCHEMA = """
CREATE TABLE IF NOT EXISTS episodic_memories (
    id          VARCHAR(64)  PRIMARY KEY,
    session_id  VARCHAR(255),
    agent_id    VARCHAR(255),
    content     TEXT         NOT NULL,
    context     JSONB        NOT NULL DEFAULT '{}',
    outcome     VARCHAR(50)  NOT NULL DEFAULT 'unknown',
    importance  FLOAT        NOT NULL DEFAULT 0.5,
    metadata    JSONB        NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS semantic_memories (
    id          VARCHAR(64)  PRIMARY KEY,
    subject     VARCHAR(500),
    predicate   VARCHAR(255),
    object      TEXT,
    confidence  FLOAT        NOT NULL DEFAULT 1.0,
    source      VARCHAR(500),
    content     TEXT         NOT NULL,
    metadata    JSONB        NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS procedures (
    id                  VARCHAR(64)  PRIMARY KEY,
    name                VARCHAR(500) NOT NULL,
    description         TEXT,
    trigger_conditions  JSONB        NOT NULL DEFAULT '[]',
    success_rate        FLOAT        NOT NULL DEFAULT 0.0,
    use_count           INTEGER      NOT NULL DEFAULT 0,
    metadata            JSONB        NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS procedure_steps (
    id               VARCHAR(64)  PRIMARY KEY,
    procedure_id     VARCHAR(64)  NOT NULL REFERENCES procedures(id) ON DELETE CASCADE,
    step_order       INTEGER      NOT NULL,
    action           VARCHAR(500) NOT NULL,
    parameters       JSONB        NOT NULL DEFAULT '{}',
    expected_outcome TEXT,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS reflective_memories (
    id                      VARCHAR(64)  PRIMARY KEY,
    source_episode_id       VARCHAR(64),
    content                 TEXT         NOT NULL,
    lesson                  TEXT,
    improvement_suggestion  TEXT,
    confidence              FLOAT        NOT NULL DEFAULT 1.0,
    applied_count           INTEGER      NOT NULL DEFAULT 0,
    metadata                JSONB        NOT NULL DEFAULT '{}',
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS reward_memories (
    id                VARCHAR(64)  PRIMARY KEY,
    state_description TEXT         NOT NULL,
    action            VARCHAR(500) NOT NULL,
    reward            FLOAT        NOT NULL,
    outcome           TEXT,
    policy            VARCHAR(255) NOT NULL DEFAULT 'default',
    context           JSONB        NOT NULL DEFAULT '{}',
    metadata          JSONB        NOT NULL DEFAULT '{}',
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_episodic_session    ON episodic_memories(session_id);
CREATE INDEX IF NOT EXISTS idx_episodic_agent      ON episodic_memories(agent_id);
CREATE INDEX IF NOT EXISTS idx_episodic_outcome    ON episodic_memories(outcome);
CREATE INDEX IF NOT EXISTS idx_semantic_subject    ON semantic_memories(subject);
CREATE INDEX IF NOT EXISTS idx_semantic_predicate  ON semantic_memories(predicate);
CREATE INDEX IF NOT EXISTS idx_procedure_name      ON procedures(name);
CREATE INDEX IF NOT EXISTS idx_proc_step_proc      ON procedure_steps(procedure_id);
CREATE INDEX IF NOT EXISTS idx_reflective_episode  ON reflective_memories(source_episode_id);
CREATE INDEX IF NOT EXISTS idx_reward_action       ON reward_memories(action);
CREATE INDEX IF NOT EXISTS idx_reward_policy       ON reward_memories(policy);
"""


class PostgresClient:
    def __init__(self, config: PostgresConfig):
        self.config = config
        self._conn = self._connect()
        self._init_schema()

    def _connect(self):
        return psycopg2.connect(
            host=self.config.host,
            port=self.config.port,
            dbname=self.config.database,
            user=self.config.username,
            password=self.config.password,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )

    def _init_schema(self):
        with self._conn.cursor() as cur:
            cur.execute(_SCHEMA)
        self._conn.commit()

    def execute(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            self._conn.commit()
            try:
                return [dict(row) for row in cur.fetchall()]
            except psycopg2.ProgrammingError:
                return []

    def execute_one(self, sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        rows = self.execute(sql, params)
        return rows[0] if rows else None

    def close(self):
        self._conn.close()
