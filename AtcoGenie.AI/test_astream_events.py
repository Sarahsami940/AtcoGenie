import asyncio
from app.agent.engine import create_agent_executor
from app.database.manager import DatabaseManager
from app.security.context import SecurityContext
from app.agent.user_context import ResolvedUserContext
from app.config import get_settings

async def test():
    class DummyDB:
        pass
    context = SecurityContext(user_id='test', display_name='Test', claims={})
    resolved = ResolvedUserContext(user_role='Admin', is_admin=True, team_names=['1'], team_ids_csv='1')
    agent = create_agent_executor(context, DummyDB(), resolved)
    messages = [{"role": "user", "content": "say hi token by token"}]
    try:
        async for event in agent.astream_events({"messages": messages}, version="v1"):
            kind = event["event"]
            if kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if hasattr(chunk, "content"):
                    print("TOKEN:", repr(chunk.content))
    except Exception as e:
        print("ERR:", e)

asyncio.run(test())
