# AtcoGenie - Deployment Guide

## 📦 Published Location
**Path**: `c:\Users\Sarah.Sami\.gemini\antigravity\playground\midnight-oort\publish\AtcoGenie`

## ✅ What's Included

### Backend (.NET 10)
- ✅ PostgreSQL chat persistence enabled
- ✅ Gemini API integration (model: gemini-2.5-flash)
- ✅ Mock authentication for local testing
- ✅ Chat history with auto-titling
- ✅ Message deduplication fixed

### Frontend (React + Vite)
- ✅ Typing animation for bot responses
- ✅ Markdown-to-HTML formatting
- ✅ Dark mode support
- ✅ Chat management (archive, delete, rename)
- ✅ No duplicate messages

## 🗄️ Database Requirements

### PostgreSQL Tables (Already Created in AtcoGenie_IMD)
```sql
-- Chat tables exist in: AtcoGenie_IMD database
- ChatSessions
- ChatMessages
```

### Connection String
```
Host=localhost;Database=AtcoGenie_IMD;Username=postgres;Password=postgres
```

## 🚀 Deployment Steps

### Option 1: Local Testing (Current Setup)
1. Database is already configured
2. Server runs on: `http://localhost:5256`
3. Just run: `dotnet run` from `AtcoGenie.Server` folder

### Option 2: VM Deployment
1. **Copy publish folder** to VM
2. **Run migration script** on VM's PostgreSQL:
   ```powershell
   psql -h localhost -U postgres -d AtcoGenie_IMD -f ChatHistory_Schema_Postgres.sql
   ```
3. **Update appsettings.json** with VM's connection strings
4. **Configure IIS** or run as Windows Service
5. **Test** at `http://vm-address:5256`

## ⚙️ Configuration Files

### appsettings.json (Current Settings)
```json
{
  "ConnectionStrings": {
    "ImdConnection": "Host=localhost;Database=AtcoGenie_IMD;Username=postgres;Password=postgres"
  },
  "Gemini": {
    "ApiKey": "AIzaSyDoASFHKtVPytX_Rr1D-v_zCqivGkgQPco",
    "ModelName": "gemini-2.5-flash"
  }
}
```

## 🔧 Key Features

### Chat Persistence
- ✅ Messages saved to PostgreSQL
- ✅ Survives server restarts
- ✅ Auto-titles based on first message

### AI Integration
- ✅ Gemini 2.5 Flash model
- ✅ 5-minute timeout for long responses
- ✅ Typing animation (15ms/character)

### Security
- ✅ Mock authentication for local dev
- ✅ User isolation (messages tied to userId)
- ✅ XSS protection in markdown rendering

## 📝 Notes

- **Mock User**: `ATCO\sarah.sami` (local testing)
- **Chat Storage**: PostgreSQL (not in-memory anymore)
- **Frontend**: Pre-built and included in `wwwroot`
- **Port**: 5256 (configurable in launchSettings.json)

## 🐛 Troubleshooting

### Chats not persisting?
- Check PostgreSQL is running
- Verify connection string in appsettings.json
- Ensure ChatSessions and ChatMessages tables exist

### Gemini API errors?
- Verify API key is valid
- Check model name is correct (gemini-2.5-flash)
- Ensure internet connectivity

### Duplicate messages?
- This has been fixed - backend handles all persistence
- If you see duplicates, clear the database:
  ```sql
  DELETE FROM "ChatMessages"; DELETE FROM "ChatSessions";
  ```

## 📊 Database Schema

### ChatSessions
- Id (PK)
- UserId (indexed)
- Title
- ModelId
- CreatedAt
- LastActiveAt
- IsArchived

### ChatMessages
- Id (PK)
- ChatSessionId (FK)
- Sender ('user' or 'bot')
- Content (TEXT)
- Timestamp

---
**Last Updated**: 2026-01-27
**Version**: 1.0 (Production Ready)
