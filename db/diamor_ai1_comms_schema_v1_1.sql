-- =====================================================================
-- DIAMOR / ZIXAN  —  AI-1 Comms Store  —  Postgres migration  v1.1  (FINAL)
-- =====================================================================
-- Supersedes diamor_ai1_comms_schema_v1.sql. Apply THIS file from scratch.
--
-- v1.1 adds ONLY the three critical pre-implementation fixes:
--   FIX 1 (idempotency)   : message.external_id + unique partial index.
--   FIX 2 (concurrency)   : conversation.state_version optimistic lock.
--   FIX 3 (erasure)       : a clear, sanctioned right-to-erasure path that scrubs
--                           PII from the retained-for-analytics tables (llm_call,
--                           event) and hard-deletes everywhere else — implemented
--                           as the function erase_candidate().
-- Nothing else about the architecture changed from v1.
--
-- Runs on:  the DEDICATED comms Postgres ONLY.
--           DO NOT run against `default` / `diamor_app` / `diamor`.
--
-- Naming conventions (unchanged from v1):
--   snake_case singular tables; pk = `id uuid`; fk = `<table>_id`;
--   timestamps timestamptz UTC; enumerated text guarded by CHECK (not native ENUM,
--   so AI-2 can add values with a one-line constraint swap); indexes idx_<table>_<cols>.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pgcrypto;     -- gen_random_uuid()
-- pgvector is intentionally NOT enabled (AI-2). AI-1 uses full-text only.


-- =====================================================================
-- 1. IDENTITY  (candidate != chat id)
-- =====================================================================
CREATE TABLE candidate (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name  text,                          -- PII; best-known name; nullable
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE channel_identity (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_id     uuid NOT NULL REFERENCES candidate(id) ON DELETE CASCADE,
    channel          text NOT NULL,
    channel_user_id  text NOT NULL,              -- PII (chat/user id on that channel)
    created_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chk_channel_identity_channel
        CHECK (channel IN ('telegram','whatsapp','instagram','web')),
    CONSTRAINT uq_channel_identity_channel_user
        UNIQUE (channel, channel_user_id)
);

CREATE INDEX idx_channel_identity_candidate ON channel_identity (candidate_id);


-- =====================================================================
-- 2. CONVERSATION  =  SOURCE OF TRUTH   (+ FIX 2: state_version)
-- =====================================================================
CREATE TABLE conversation (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_id     uuid NOT NULL REFERENCES candidate(id) ON DELETE CASCADE,
    channel          text NOT NULL,
    language         text,
    status           text NOT NULL DEFAULT 'active',
    assigned_human   text,
    state            jsonb NOT NULL DEFAULT '{}'::jsonb,   -- PII (the 14 intake fields)
    state_version    integer NOT NULL DEFAULT 0,           -- FIX 2: optimistic lock counter
    intake_complete  boolean NOT NULL DEFAULT false,
    bitrix_lead_id   text,                                 -- projection pointer; Bitrix != truth
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chk_conversation_channel
        CHECK (channel IN ('telegram','whatsapp','instagram','web')),
    CONSTRAINT chk_conversation_status
        CHECK (status IN ('active','escalated','human_controlled','completed')),
    CONSTRAINT chk_conversation_language
        CHECK (language IS NULL OR language IN ('ru','uz','en'))
);

CREATE INDEX idx_conversation_candidate        ON conversation (candidate_id);
CREATE INDEX idx_conversation_status           ON conversation (status);
CREATE INDEX idx_conversation_bitrix           ON conversation (bitrix_lead_id);
CREATE INDEX idx_conversation_candidate_status ON conversation (candidate_id, status);


-- =====================================================================
-- 3. MESSAGE  (modality-ready)   (+ FIX 1: external_id idempotency)
-- =====================================================================
CREATE TABLE message (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id  uuid NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
    candidate_id     uuid NOT NULL REFERENCES candidate(id)    ON DELETE CASCADE,
    external_id      text,                          -- FIX 1: channel msg id, e.g. 'tg:<update_id>'
                                                    --        NULL for outbound (we generate those)
    direction        text NOT NULL,
    modality         text NOT NULL DEFAULT 'text',  -- AI-1 only ever writes 'text'
    text             text NOT NULL,                 -- PII; canonical content; everything reads this
    media_ref        text,                          -- AI-2 (audio/image/file pointer); null now
    language         text,
    agent            text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chk_message_direction CHECK (direction IN ('in','out')),
    CONSTRAINT chk_message_modality  CHECK (modality IN ('text','audio','image','file')),
    CONSTRAINT chk_message_language  CHECK (language IS NULL OR language IN ('ru','uz','en'))
);

CREATE INDEX idx_message_conversation ON message (conversation_id, created_at);
CREATE INDEX idx_message_candidate    ON message (candidate_id, created_at);

-- FIX 1: dedupe inbound messages. Partial unique index allows many NULLs (outbound),
-- but rejects a second insert of the same channel message id (Telegram redelivery / n8n retry).
CREATE UNIQUE INDEX uq_message_external
    ON message (external_id) WHERE external_id IS NOT NULL;

-- Full-text search over canonical text (AI-1 keyword recall; AI-2 adds pgvector separately).
ALTER TABLE message
    ADD COLUMN text_search tsvector
    GENERATED ALWAYS AS (to_tsvector('simple', coalesce(text, ''))) STORED;

CREATE INDEX idx_message_text_search ON message USING GIN (text_search);


-- =====================================================================
-- 4. ESCALATION  (safety record)
-- =====================================================================
CREATE TABLE escalation (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id  uuid NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
    reason           text,                          -- may contain PII context
    triggered_by     text,
    notified_at      timestamptz NOT NULL DEFAULT now(),
    resolved_at      timestamptz,
    CONSTRAINT chk_escalation_triggered_by
        CHECK (triggered_by IS NULL OR triggered_by IN ('master','intake','post_filter','manual'))
);

CREATE INDEX idx_escalation_conversation ON escalation (conversation_id);
CREATE INDEX idx_escalation_open ON escalation (resolved_at) WHERE resolved_at IS NULL;


-- =====================================================================
-- 5. LLM_CALL  (provider contract + prompt version = eval dataset)
-- =====================================================================
-- ERASURE NOTE (FIX 3): input/output CONTAIN PII (rendered prompt incl. name/phone/etc.).
-- conversation_id is ON DELETE SET NULL so the NON-PII metrics survive a conversation delete
-- for analytics. PII columns are scrubbed by erase_candidate() (see end of file). The
-- sanctioned erasure path is erase_candidate(); do NOT hard-delete candidates by raw DELETE
-- (that would null the link but leave input/output PII behind).
CREATE TABLE llm_call (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id  uuid REFERENCES conversation(id) ON DELETE SET NULL,
    provider         text NOT NULL,                 -- 'anthropic' in AI-1
    model            text NOT NULL,
    prompt_name      text NOT NULL,                 -- 'master'|'intake'|'escalation'
    prompt_version   text NOT NULL,                 -- e.g. 'intake_v1' (ties to prompt file)
    input            jsonb NOT NULL,                -- PII; scrubbed to '{}' on erasure
    output           jsonb,                         -- PII; scrubbed to NULL on erasure
    latency_ms       integer,
    token_input      integer,
    token_output     integer,
    created_at       timestamptz NOT NULL DEFAULT now()
    -- No CHECK on provider/prompt_name: new providers/agents must be addable freely.
);

CREATE INDEX idx_llm_call_conversation ON llm_call (conversation_id, created_at);
CREATE INDEX idx_llm_call_prompt       ON llm_call (prompt_name, prompt_version);
CREATE INDEX idx_llm_call_model        ON llm_call (provider, model);


-- =====================================================================
-- 6. EVENT  (observability + metrics source)
-- =====================================================================
-- ERASURE NOTE (FIX 3): payload MAY contain PII. candidate_id/conversation_id are
-- ON DELETE SET NULL so non-PII metrics survive; payload is scrubbed by erase_candidate().
CREATE TABLE event (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id  uuid REFERENCES conversation(id) ON DELETE SET NULL,
    candidate_id     uuid REFERENCES candidate(id)    ON DELETE SET NULL,
    type             text NOT NULL,
    payload          jsonb NOT NULL DEFAULT '{}'::jsonb,   -- may contain PII; scrubbed on erasure
    created_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chk_event_type CHECK (type IN (
        'msg_in','msg_out','routed','escalated',
        'lead_created','lead_updated','manager_rated','handoff','resumed'
    ))
);

CREATE INDEX idx_event_conversation ON event (conversation_id, created_at);
CREATE INDEX idx_event_type_time    ON event (type, created_at);


-- =====================================================================
-- 7. OUTCOME + HUMAN JUDGMENT  (the decade-long moat)
-- =====================================================================
CREATE TABLE lead_origin (
    bitrix_lead_id   text PRIMARY KEY,
    conversation_id  uuid NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
    candidate_id     uuid NOT NULL REFERENCES candidate(id)    ON DELETE CASCADE,
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_lead_origin_conversation ON lead_origin (conversation_id);
CREATE INDEX idx_lead_origin_candidate    ON lead_origin (candidate_id);

CREATE TABLE manager_lead_rating (
    bitrix_lead_id   text PRIMARY KEY,
    rating           text NOT NULL,                 -- 'good' | 'bad' (extensible later)
    rated_by         text,
    rated_at         timestamptz NOT NULL DEFAULT now(),
    note             text,
    CONSTRAINT chk_manager_lead_rating_rating
        CHECK (rating IN ('good','bad'))
);


-- =====================================================================
-- 8. ERASURE  (FIX 3): the ONE sanctioned right-to-erasure path
-- =====================================================================
-- DECISION (explicit): on erasure we HARD-DELETE every PII-bearing row that is purely
-- personal (candidate, channel_identity, conversation, message, escalation, lead_origin,
-- and the candidate's manager_lead_rating rows), and we RETAIN the analytics rows
-- (llm_call, event) but SCRUB their PII columns — keeping only non-PII metrics
-- (provider, model, prompt_version, latency, tokens, event type, timestamps).
-- This honors right-to-erasure while preserving aggregate evaluation/observability value.
--
-- Use ONLY this function to erase a candidate. Order matters: scrub the retained tables
-- (which reference the candidate's conversations/leads) BEFORE the cascade delete removes
-- those references.
CREATE OR REPLACE FUNCTION erase_candidate(p_candidate_id uuid) RETURNS void AS $$
BEGIN
    -- 1. Scrub PII from llm_call rows for this candidate's conversations.
    UPDATE llm_call
       SET input = '{}'::jsonb, output = NULL
     WHERE conversation_id IN (
           SELECT id FROM conversation WHERE candidate_id = p_candidate_id);

    -- 2. Scrub PII from event rows for this candidate (direct + via conversations).
    UPDATE event
       SET payload = '{}'::jsonb
     WHERE candidate_id = p_candidate_id
        OR conversation_id IN (
           SELECT id FROM conversation WHERE candidate_id = p_candidate_id);

    -- 3. Remove quality labels tied to this candidate's leads (lead_origin cascades in step 4,
    --    so read it now). The good/bad label has no training value once the conversation is gone.
    DELETE FROM manager_lead_rating
     WHERE bitrix_lead_id IN (
           SELECT bitrix_lead_id FROM lead_origin WHERE candidate_id = p_candidate_id);

    -- 4. Hard-delete the candidate. CASCADE removes channel_identity, conversation, message,
    --    escalation, lead_origin. llm_call/event survive with conversation_id/candidate_id
    --    set NULL and PII already scrubbed in steps 1-2.
    DELETE FROM candidate WHERE id = p_candidate_id;
END;
$$ LANGUAGE plpgsql;
-- (If the deploy role cannot create functions, run steps 1-4 inline in one transaction
--  in the same order. Never erase by a bare `DELETE FROM candidate` alone.)

COMMIT;


-- =====================================================================
-- MINIMAL SEED / DEFAULT STATE EXAMPLE  (reference — run ad hoc, not in the migration)
-- =====================================================================
-- Canonical conversation.state for AI-1 (the 14 intake fields + flags), set by wf_state_load
-- when opening a new conversation:
--
-- '{
--    "intake": {
--      "full_name": null, "phone": null, "telegram_handle": null,
--      "country_current": null, "age": null, "profession": null,
--      "work_experience": null, "destination_country": null,
--      "desired_vacancy": null, "language_level": null,
--      "passport_available": null, "documents_readiness": null,
--      "urgency": null, "source_referrer": null
--    },
--    "flags": { "consent_shown": false }
--  }'::jsonb
--
-- "next missing field" = first key in state->'intake' whose value IS NULL.
-- The agent NEVER re-asks a non-null field (cross-session, cross-day).


-- =====================================================================
-- DEVELOPER NOTES — SAFE MESSAGE PROCESSING, RETRIES, BITRIX (FIX 5)
-- =====================================================================
--
-- A) IDEMPOTENT INBOUND PROCESSING (uses FIX 1)
--    On each inbound Telegram update:
--      1. external_id := 'tg:' || <telegram update_id>.
--      2. Resolve identity: SELECT channel_identity by (channel='telegram', channel_user_id).
--         If absent -> INSERT candidate, then channel_identity. (AI-1: one candidate per chat id.)
--      3. Open/fetch the active conversation for that candidate (seed state if new).
--      4. INSERT the inbound `message` WITH external_id.
--         -> If this INSERT raises a unique-violation on uq_message_external, the update was
--            ALREADY processed (Telegram redelivery or n8n retry): STOP. Do not run agents,
--            do not advance state, do not create a lead. This is the idempotency gate.
--      5. Emit event 'msg_in'.
--
-- B) CONCURRENCY-SAFE STATE SAVE (uses FIX 2)
--    Read state with its version, then save with an optimistic check:
--      -- read:
--      SELECT state, state_version FROM conversation WHERE id = $cid;     -- remember $ver
--      -- ... run Master/Intake, compute merged state ...
--      -- save:
--      UPDATE conversation
--         SET state = $merged, state_version = state_version + 1, updated_at = now()
--       WHERE id = $cid AND state_version = $ver;
--      -- If 0 rows affected -> another execution updated state concurrently:
--      --   reload (SELECT state, state_version), re-merge your updated_fields, retry the UPDATE.
--      --   Use a small bounded retry loop (e.g. up to 3 attempts).
--    Combined with (A) and per-conversation ordered processing, this prevents lost fields and
--    double advances when a candidate sends messages in quick succession.
--
-- C) RETRIES IN GENERAL
--    Every external step (LLM, Bitrix, Telegram) may be retried by n8n. Make each safe:
--      - Inbound dedupe (A) makes re-running the whole flow safe.
--      - llm_call rows are append-only logs; a retry simply logs another attempt (acceptable).
--      - State saves are guarded by (B).
--      - Lead creation is guarded by (D).
--
-- D) BITRIX LEAD CREATE-ONCE (prevents duplicate leads on retry)
--    Lead creation runs only when intake_complete = true AND conversation.bitrix_lead_id IS NULL.
--    To survive a lost response after a successful create, make creation idempotent via the
--    conversation reference we already store on the lead (UF_CRM_conversation_ref):
--      1. BEFORE crm.lead.add: query crm.lead.list filtered by UF_CRM_conversation_ref = <conv_id>.
--         - If a lead already exists -> treat as created; take its id (do NOT add another).
--         - Else -> crm.lead.add with UF_CRM_conversation_ref = <conv_id>.
--      2. Persist the id back under the optimistic lock:
--           UPDATE conversation SET bitrix_lead_id = $id, state_version = state_version + 1
--            WHERE id = $cid AND bitrix_lead_id IS NULL AND state_version = $ver;
--      3. INSERT INTO lead_origin (bitrix_lead_id, conversation_id, candidate_id) ...;
--         (bitrix_lead_id is PK -> a duplicate insert fails, a second guard against double-create.)
--      4. Emit event 'lead_created'.
--    Net: even if a retry occurs, step 1's lookup + the bitrix_lead_id-IS-NULL guard + the
--    lead_origin PK together ensure exactly one lead per conversation.
--
-- E) HANDOFF SUPPRESSION
--    While conversation.status IN ('escalated','human_controlled'), the orchestrator appends
--    transcript + emits events but DOES NOT generate AI replies (the AI must not talk over a
--    human). A human sets status back to 'active' (emit 'resumed') to return control to the agent.
--
-- F) ERASURE
--    To fulfill a deletion request: SELECT erase_candidate('<candidate uuid>');
--    Then erase the corresponding lead in Bitrix separately (Bitrix is the projection).
--
-- =====================================================================
-- EXACT BUILD ORDER (unchanged from v1; this migration is STEP 1)
-- =====================================================================
--   1. Apply this file to the dedicated comms Postgres ONLY. Verify 9 tables, the GIN index,
--      uq_message_external, conversation.state_version, and erase_candidate() exist.
--      Confirm this DB is NOT default/diamor_app/diamor.
--   2. Bitrix: create lead custom fields (incl. UF_CRM_conversation_ref) + the
--      "AI Intake -> Needs Human Review" pipeline; capture UF_CRM_* ids.
--   3. n8n skeleton: Telegram Trigger -> Inbound Normalizer (envelope) -> Telegram echo,
--      doing the writes in DEVELOPER NOTE (A) (incl. external_id dedupe). Prove the pipe.
--   4. wf_llm_call abstraction (logs every call to llm_call; robust JSON parse; fail-safe to escalation).
--   5. wf_state_load / wf_state_save (optimistic lock per NOTE (B)).
--   6. Master Agent (master_v1) -> route/language/escalation; log llm_call + event 'routed'.
--   7. Intake Agent (intake_v1) -> fill next NULL field; on completion produce summary.
--   8. Escalation flow (escalation_v1) + handoff suppression per NOTE (E).
--   9. Bitrix lead upsert per NOTE (D) + no-promise post-filter before any outbound send.
--  10. Manager rating hook -> manager_lead_rating + event 'manager_rated'.
--   Then run the AI-1 testing checklist and soft-launch.
--
-- NOT INCLUDED (AI-2, deliberately): pgvector/embeddings, candidate-merge logic,
--   candidate_profile_summary / vacancy / vacancy_match tables, audio/OCR pipelines.
-- =====================================================================
