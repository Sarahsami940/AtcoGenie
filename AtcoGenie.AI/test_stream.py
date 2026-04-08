import asyncio
from app.agent.engine import create_agent_executor
from app.database.manager import DatabaseManager
from app.security.context import SecurityContext
from app.agent.user_context import ResolvedUserContext
from app.config import get_settings

async def test():
    class DummyDB:
        pass
    class DummyContext(SecurityContext):
        user_id = 'test'
        display_name = 'Test'
        claims = {}
    class DummyResolved(ResolvedUserContext):
        user_role = 'Admin'
        team_names = ['1']
        team_ids_csv = '1'
        is_admin = True
    context = SecurityContext(user_id='test', display_name='Test', claims={})
    resolved = ResolvedUserContext(user_role='Admin', is_admin=True, team_names=['1'], team_ids_csv='1')
    agent = create_agent_executor(context, DummyDB(), resolved)
    messages = [{"role": "user", "content": "say hi"}]
    try:
        async for c, meta in agent.astream({"messages": messages}, stream_mode="messages"):
            print(c.type, repr(c.content))
    except Exception as e:
        print("ERR:", e)

asyncio.run(test())
