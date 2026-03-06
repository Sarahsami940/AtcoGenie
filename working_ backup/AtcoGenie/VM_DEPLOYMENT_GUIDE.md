# 🚀 AtcoGenie - VM Deployment Instructions

## 📦 **DEPLOYMENT PACKAGE READY**
**Location**: `c:\Users\Sarah.Sami\.gemini\antigravity\playground\midnight-oort\publish\AtcoGenie`

**Build Date**: 2026-01-27 14:17 PM
**Status**: ✅ All latest changes included

---

## ✅ **What's Included in This Build**

### Backend Changes
- ✅ PostgreSQL chat persistence (messages survive restarts)
- ✅ Gemini 2.5 Flash API integration
- ✅ Message deduplication fix (backend handles all persistence)
- ✅ Auto-titling for chat sessions
- ✅ Mock authentication for local testing

### Frontend Changes  
- ✅ Typing animation (ChatGPT-style, 15ms/character)
- ✅ Markdown-to-HTML formatting for bot responses
- ✅ Property mapping fix (content→text, chatSessionId→sessionId)
- ✅ No duplicate messages
- ✅ Dark mode support
- ✅ Chat management (archive, delete, rename)

---

## 🔄 **DEPLOYMENT STEPS TO VM**

### Step 1: Copy Files to VM
```powershell
# Copy the entire publish folder to VM
robocopy "c:\Users\Sarah.Sami\.gemini\antigravity\playground\midnight-oort\publish\AtcoGenie" "\\VM-NAME\c$\inetpub\AtcoGenie" /MIR
```

### Step 2: Setup Database on VM
```powershell
# On VM, run this SQL script to create chat tables
psql -h localhost -U postgres -d AtcoGenie_IMD -f ChatHistory_Schema_Postgres.sql
```

**SQL Script Location**: `c:\Users\Sarah.Sami\.gemini\antigravity\playground\midnight-oort\AtcoGenie.Server\SQL\ChatHistory_Schema_Postgres.sql`

### Step 3: Update Configuration on VM
Edit `appsettings.json` on the VM:

```json
{
  "ConnectionStrings": {
    "ImdConnection": "Host=VM-POSTGRES-HOST;Database=AtcoGenie_IMD;Username=postgres;Password=YOUR_PASSWORD",
    "HcmsConnection": "Server=10.10.0.88;Database=HCMS;User Id=dakiadbreader;Password=s0ftr0n1c@5607;TrustServerCertificate=True;"
  },
  "Gemini": {
    "ApiKey": "AIzaSyDoASFHKtVPytX_Rr1D-v_zCqivGkgQPco",
    "ModelName": "gemini-2.5-flash"
  }
}
```

### Step 4: Configure IIS on VM
1. Create new site in IIS Manager
2. Point to `c:\inetpub\AtcoGenie`
3. Application Pool: `.NET CLR Version: No Managed Code`
4. Set port (e.g., 5256 or 80)
5. Start the site

### Step 5: Verify Deployment
1. Browse to `http://VM-ADDRESS:PORT`
2. Create a new chat and send a message
3. Check typing animation appears
4. Refresh page and verify chat persists
5. Open old chat and verify messages load correctly

---

## 🗄️ **Database Schema (Already Created Locally)**

The following tables should exist in `AtcoGenie_IMD`:

### ChatSessions
- Id (SERIAL PRIMARY KEY)
- UserId (VARCHAR 100) - Indexed
- Title (VARCHAR 200)
- ModelId (VARCHAR 50)
- CreatedAt (TIMESTAMP)
- LastActiveAt (TIMESTAMP)
- IsArchived (BOOLEAN)

### ChatMessages
- Id (SERIAL PRIMARY KEY)
- ChatSessionId (INTEGER FK)
- Sender (VARCHAR 50) - 'user' or 'bot'
- Content (TEXT)
- Timestamp (TIMESTAMP)

---

## 🔧 **Configuration Notes**

### Mock Authentication
- **Local Dev**: Enabled (user: `ATCO\sarah.sami`)
- **VM Production**: Disable in `Program.cs` line ~200:
  ```csharp
  // Comment out this line for production:
  // app.UseMiddleware<MockAuthMiddleware>();
  ```

### Gemini API
- Model: `gemini-2.5-flash`
- Timeout: 5 minutes
- API Key: Already configured

### PostgreSQL
- **Local**: `localhost:5432`
- **VM**: Update connection string to VM's PostgreSQL host

---

## 🐛 **Troubleshooting**

### Issue: Chats not appearing after refresh
**Solution**: 
1. Verify PostgreSQL is running on VM
2. Check connection string in `appsettings.json`
3. Ensure chat tables exist: `SELECT * FROM "ChatSessions";`

### Issue: Typing animation not working
**Solution**:
1. Clear browser cache (Ctrl+Shift+Delete)
2. Hard refresh (Ctrl+F5)
3. Check browser console for errors

### Issue: Duplicate messages
**Solution**:
1. This should be fixed in this build
2. If still occurring, clear database:
   ```sql
   DELETE FROM "ChatMessages"; 
   DELETE FROM "ChatSessions";
   ```

### Issue: 404 errors for static files
**Solution**:
1. Verify `wwwroot` folder exists in deployment
2. Check IIS static file handling is enabled
3. Verify `web.config` is present

---

## 📊 **Files to Copy to VM**

### Required Files
- ✅ `AtcoGenie.Server.dll` (main application)
- ✅ `AtcoGenie.Server.exe` (Windows executable)
- ✅ `appsettings.json` (configuration)
- ✅ `web.config` (IIS configuration)
- ✅ `wwwroot/` (frontend files - CRITICAL!)
- ✅ All DLL dependencies

### SQL Scripts (for reference)
- `ChatHistory_Schema_Postgres.sql` (create tables)
- Located at: `c:\Users\Sarah.Sami\.gemini\antigravity\playground\midnight-oort\AtcoGenie.Server\SQL\`

---

## ✅ **Pre-Deployment Checklist**

- [ ] PostgreSQL is installed and running on VM
- [ ] Chat tables created in `AtcoGenie_IMD` database
- [ ] `appsettings.json` updated with VM connection strings
- [ ] IIS configured with correct application pool
- [ ] Firewall allows traffic on application port
- [ ] Gemini API key is valid and has quota
- [ ] `wwwroot` folder copied to VM (contains frontend)

---

## 🎯 **Expected Behavior After Deployment**

1. **New Chat**: 
   - Click "New Chat" → Type message → See typing animation
   - Chat auto-titles based on first message
   - Messages persist to database

2. **Existing Chat**:
   - Click chat in sidebar → Messages load with formatting
   - No duplicates
   - Markdown renders as HTML (bold, code blocks, etc.)

3. **After Server Restart**:
   - All chats still visible in sidebar
   - Messages still load when opening chat
   - No data loss

---

**Last Updated**: 2026-01-27 14:17 PM
**Build Version**: 1.0 (Production Ready)
**Source**: C:\Users\Sarah.Sami\.gemini\antigravity\playground\midnight-oort\
