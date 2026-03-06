-- ============================================
-- AtcoGenie: Create IMD_UserFormRights Table
-- Version: 002
-- Purpose: Full mirror of imd_usermapping + Security.UserFormRights
--          Includes AD, HCMS, and Security data in one table.
--          Employees without app access get NULL form fields.
-- Run on: PostgreSQL (IMD Database on VM)
-- NOTE: imd_usermapping is NOT modified.
-- ============================================

CREATE TABLE IF NOT EXISTS imd_userformrights (
    id              SERIAL PRIMARY KEY,

    -- AD + HCMS fields (mirror of imd_usermapping)
    adobjectguid    UUID NOT NULL,
    hcmsemployeeid  VARCHAR(50) NOT NULL,
    email           VARCHAR(255) NOT NULL,
    displayname     VARCHAR(255),
    samaccountname  VARCHAR(100),
    isactive        BOOLEAN DEFAULT TRUE,

    -- Security.dbo.UserMapping fields
    securityuserid  INT NULL,                      -- NULL if employee not in Security

    -- Security.dbo.UserFormRights fields (NULL if no access)
    ccode           VARCHAR(50) NULL,
    applicationcode VARCHAR(50) NULL,              -- 'PharmaCRM' or 'HCMS' or NULL
    formid          VARCHAR(100) NULL,
    addmode         BOOLEAN NULL,
    editmode        BOOLEAN NULL,
    viewmode        BOOLEAN NULL,
    deletemode      BOOLEAN NULL,

    lastsyncedat    TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS ix_ufr_hcmsemployeeid ON imd_userformrights(hcmsemployeeid);
CREATE INDEX IF NOT EXISTS ix_ufr_email ON imd_userformrights(email);
CREATE INDEX IF NOT EXISTS ix_ufr_securityuserid ON imd_userformrights(securityuserid);
CREATE INDEX IF NOT EXISTS ix_ufr_appcode ON imd_userformrights(applicationcode);
CREATE INDEX IF NOT EXISTS ix_ufr_empid_appcode ON imd_userformrights(hcmsemployeeid, applicationcode);

-- Unique: one row per user per app per form (NULLs allowed for users with no rights)
CREATE UNIQUE INDEX IF NOT EXISTS uq_ufr_empid_app_form 
ON imd_userformrights(hcmsemployeeid, applicationcode, formid)
WHERE applicationcode IS NOT NULL;

-- ============================================
-- ROLLBACK:
-- DROP TABLE IF EXISTS imd_userformrights;
-- ============================================
