import os
import asyncio
from typing import List
from dotenv import load_dotenv

# LangChain imports
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate

# Load environment configuration
load_dotenv(override=True)

# =======================================================================
# 1. Security Context Emulation
# =======================================================================
class MockUserFormRight:
    def __init__(self, app_code: str, form_id: str, view_mode: bool):
        self.application_code = app_code
        self.form_id = form_id
        self.view_mode = view_mode

class MockSecurityContext:
    def __init__(self, username: str, rights: List[MockUserFormRight]):
        self.user_id = username
        self.form_rights = rights

    def has_report_access(self, application_code: str, report_sp_name: str) -> bool:
        for right in self.form_rights:
            if right.application_code.lower() == application_code.lower():
                if right.form_id.lower() == report_sp_name.lower():
                    return right.view_mode
        return False

# We manually inject what our .NET middleware would have hydrated from Redis
TEST_CONTEXT = MockSecurityContext(
    username="Sarah.Sami",
    rights=[
        MockUserFormRight("PharmaCRM", "Report1_Placeholder", view_mode=True),   # ALLOWED
        MockUserFormRight("PharmaCRM", "Report2_Placeholder", view_mode=True),   # ALLOWED
        MockUserFormRight("PharmaCRM", "Report3_Placeholder", view_mode=False),  # DENIED (Testing security intercept)
    ]
)


# =======================================================================
# 2. LangChain Mock Tools (With embedded security intercepts)
# =======================================================================
@tool
def get_report_1(start_date: str, end_date: str) -> str:
    """Retrieves data for Report 1. Requires start_date and end_date in YYYY-MM-DD format."""
    print(f"\n[TOOL CALLED: get_report_1] Checking security for {TEST_CONTEXT.user_id}...")
    
    # Security Intercept!
    if not TEST_CONTEXT.has_report_access("PharmaCRM", "Report1_Placeholder"):
        print("[SECURITY] Denied access to Report1_Placeholder")
        return "SECURITY ALERT: You do not have permission to run Report 1."
    
    print("[SECURITY] Access Granted.")
    return f"Execution Success! [Report 1 Data for {start_date} to {end_date}: Revenue=$5,000, Visits=42]"


@tool
def get_report_2(city: str) -> str:
    """Retrieves data for Report 2. Requires a city name."""
    print(f"\n[TOOL CALLED: get_report_2] Checking security for {TEST_CONTEXT.user_id}...")
    
    if not TEST_CONTEXT.has_report_access("PharmaCRM", "Report2_Placeholder"):
        print("[SECURITY] Denied access to Report2_Placeholder")
        return "SECURITY ALERT: You do not have permission to run Report 2."
    
    print("[SECURITY] Access Granted.")
    return f"Execution Success! [Report 2 Data for {city}: Top Doctor=Dr. Smith]"


@tool
def get_report_3(product_name: str) -> str:
    """Retrieves data for Report 3. Requires a product name."""
    print(f"\n[TOOL CALLED: get_report_3] Checking security for {TEST_CONTEXT.user_id}...")
    
    if not TEST_CONTEXT.has_report_access("PharmaCRM", "Report3_Placeholder"):
        print("[SECURITY] Denied access to Report3_Placeholder")
        return "SECURITY ALERT: You do not have permission to view Report 3 data."
    
    print("[SECURITY] Access Granted.")
    return f"Execution Success! [Report 3 Data for {product_name}: Market Share=15%]"


# =======================================================================
# 3. Agent Execution Playground
# =======================================================================
async def main():
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("\nERROR: GOOGLE_API_KEY is missing in your .env file!")
        print("Please add 'GOOGLE_API_KEY=your_gemini_key' to D:\\Office Stuff\\AtcoGenie\\AtcoGenie.AI\\.env")
        return

    print("==========================================================")
    print(" AtcoGenie AI - Standalone Agent Playground (Placeholders) ")
    print("==========================================================")
    print("Type 'exit' to stop.")
    print("\nSimulated Identity: Sarah.Sami")
    print("Rights:")
    print(" - Report 1: ALLOWED")
    print(" - Report 2: ALLOWED")
    print(" - Report 3: DENIED (Testing our Pre-Execution Security)")
    print("==========================================================\n")
    
    # Initialize the Gemini Model (Flash model is super fast for tool calling)
    llm = ChatGoogleGenerativeAI(
        model="gemini-1.5-flash",
        google_api_key=api_key,
        temperature=0
    )
    
    tools = [get_report_1, get_report_2, get_report_3]
    
    # Prompt Instruction
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are the AtcoGenie AI Agent. You have access to three reports via tools. Answer the user's query by executing the relevant tool. If a tool returns a SECURITY ALERT, explicitly tell the user they are not authorized. Do not attempt to guess the data."),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ])
    
    agent = create_tool_calling_agent(llm, tools, prompt)
    # Using verbose=False so you only see exactly what the user and tools return
    agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=False)
    
    while True:
        try:
            user_input = input("\nYou: ")
            if user_input.lower() in ["exit", "quit"]:
                break
                
            print("Genie is thinking...")
            response = await agent_executor.ainvoke({"input": user_input})
            print(f"\nGenie: {response['output']}")
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error occurred: {e}")

if __name__ == "__main__":
    asyncio.run(main())
