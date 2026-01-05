import asyncio
import logging
import json
from trading_agent import orchestrator
from account import demo_account

# Configure logging to console
logging.basicConfig(level=logging.INFO)

async def main():
    print("Testing Orchestrator Cycle...")
    await demo_account.initialize()
    try:
        result = await orchestrator.run_cycle()
        print("Cycle Result:", json.dumps(result, indent=2, default=str))
        
        # Verification Check
        for dec in result.get("decisions", []):
            if "invalidation" in dec:
                 print(f"VERIFIED: {dec['coin']} {dec['signal']} has invalidation: {dec['invalidation']}")
            else:
                 print(f"WARNING: {dec['coin']} {dec['signal']} missing invalidation")
    except Exception as e:
        print(f"Cycle Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
