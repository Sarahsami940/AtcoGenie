-- Identity Mapping Database (IMD) Schema - PostgreSQL (Simplified)

-- Users Table
CREATE TABLE IMD_UserMapping (
    Id SERIAL PRIMARY KEY,
    AdObjectGuid UUID NOT NULL,
    HcmsEmployeeId VARCHAR(50) NOT NULL,
    Email VARCHAR(255) NOT NULL,
    DisplayName VARCHAR(255) NULL,
    SamAccountName VARCHAR(100) NULL,
    LastSyncedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    IsActive BOOLEAN DEFAULT TRUE
);

-- Indexes
CREATE UNIQUE INDEX IX_UserMapping_Email ON IMD_UserMapping (Email);
CREATE UNIQUE INDEX IX_UserMapping_AdObjectGuid ON IMD_UserMapping (AdObjectGuid);

-- Audit Table
CREATE TABLE IMD_QueryAudit (
    Id BIGSERIAL PRIMARY KEY,
    UserMappingId INT NOT NULL,
    UserEmail VARCHAR(255) NOT NULL,
    Prompt TEXT NOT NULL,
    GeneratedSql TEXT NULL,
    ExecutionTimeMs INT NULL,
    Timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    IsSuccess BOOLEAN DEFAULT FALSE,
    ErrorMessage TEXT NULL,
    CONSTRAINT FK_Audit_User FOREIGN KEY (UserMappingId) REFERENCES IMD_UserMapping(Id)
);
