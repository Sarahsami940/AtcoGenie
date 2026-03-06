-- =============================================================================
-- ATCO Genie - Chat History Schema (PostgreSQL)
-- Run this script on your production database (e.g., AtcoGenie_IMD or a separate DB)
-- =============================================================================

-- 1. Create Data Tables
CREATE TABLE IF NOT EXISTS "ChatSessions" (
    "Id" SERIAL PRIMARY KEY,
    "UserId" VARCHAR(100) NOT NULL, -- Stores 'ATCO\Sarah.Sami' or EmployeeId 'SLS_09'
    "Title" VARCHAR(200) NOT NULL,
    "ModelId" VARCHAR(50) NOT NULL DEFAULT 'gemini-3-pro',
    "CreatedAt" TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    "LastActiveAt" TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    "IsArchived" BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS "ChatMessages" (
    "Id" SERIAL PRIMARY KEY,
    "ChatSessionId" INTEGER NOT NULL REFERENCES "ChatSessions"("Id") ON DELETE CASCADE,
    "Sender" VARCHAR(50) NOT NULL, -- 'user' or 'bot'
    "Content" TEXT NOT NULL,
    "Timestamp" TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. Indexes for Performance
CREATE INDEX IF NOT EXISTS "IX_ChatSessions_UserId" ON "ChatSessions" ("UserId");
CREATE INDEX IF NOT EXISTS "IX_ChatSessions_LastActiveAt" ON "ChatSessions" ("LastActiveAt" DESC);
CREATE INDEX IF NOT EXISTS "IX_ChatMessages_SessionId" ON "ChatMessages" ("ChatSessionId");

-- 3. Comments (Optional documentation)
COMMENT ON TABLE "ChatSessions" IS 'Stores conversation threads for Genie users.';
COMMENT ON COLUMN "ChatSessions"."UserId" IS 'The owner identity. Ensures User Isolation.';
