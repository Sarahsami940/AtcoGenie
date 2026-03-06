-- Identity Mapping Database (IMD) Schema

CREATE TABLE [IMD_UserMapping] (
    [Id] INT IDENTITY(1,1) PRIMARY KEY,
    [AdObjectGuid] UNIQUEIDENTIFIER NOT NULL, -- ObjectGUID from Active Directory
    [HcmsEmployeeId] NVARCHAR(50) NOT NULL,   -- Employee ID from HR System
    [Email] NVARCHAR(255) NOT NULL,           -- Common link between AD and HR
    [DisplayName] NVARCHAR(255) NULL,
    [LastSyncedAt] DATETIME2 DEFAULT GETUTCDATE(),
    [IsActive] BIT DEFAULT 1,
    INDEX [IX_UserMapping_Email] ([Email]),
    INDEX [IX_UserMapping_AdObjectGuid] ([AdObjectGuid])
);

CREATE TABLE [IMD_QueryAudit] (
    [Id] BIGINT IDENTITY(1,1) PRIMARY KEY,
    [UserMappingId] INT NOT NULL,
    [UserEmail] NVARCHAR(255) NOT NULL,
    [Prompt] NVARCHAR(MAX) NOT NULL,
    [GeneratedSql] NVARCHAR(MAX) NULL,
    [ExecutionTimeMs] INT NULL,
    [Timestamp] DATETIME2 DEFAULT GETUTCDATE(),
    [IsSuccess] BIT DEFAULT 0,
    [ErrorMessage] NVARCHAR(MAX) NULL,
    CONSTRAINT [FK_Audit_User] FOREIGN KEY ([UserMappingId]) REFERENCES [IMD_UserMapping]([Id])
);

GO
