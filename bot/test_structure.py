#!/usr/bin/env python3
"""
Test script to verify bot.py structure without connecting to Telegram
"""

import sys
import ast

def check_bot_structure():
    """Verify bot.py has correct structure"""
    
    print("🔍 Checking bot.py structure...")
    
    with open('bot.py', 'r') as f:
        content = f.read()
    
    checks = {
        "AsyncIOScheduler imported": "from apscheduler.schedulers.asyncio import AsyncIOScheduler",
        "post_init function defined": "async def post_init(application: Application)",
        "Scheduler in post_init": "scheduler = AsyncIOScheduler()",
        "No scheduler.start() in main": "def main():",
        "post_init assigned": "application.post_init = post_init",
    }
    
    results = []
    for check_name, search_string in checks.items():
        if search_string in content:
            print(f"  ✅ {check_name}")
            results.append(True)
        else:
            print(f"  ❌ {check_name}")
            results.append(False)
    
    # Check that scheduler.start() is NOT in main() function
    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == 'main':
                main_code = ast.get_source_segment(content, node)
                if main_code and 'scheduler.start()' in main_code:
                    print(f"  ❌ scheduler.start() should NOT be in main()")
                    results.append(False)
                else:
                    print(f"  ✅ scheduler.start() correctly NOT in main()")
                    results.append(True)
                break
    except:
        print(f"  ⚠️  Could not parse main() function")
    
    print()
    if all(results):
        print("✅ All checks passed! Bot structure is correct.")
        return True
    else:
        print("❌ Some checks failed. Please review bot.py")
        return False

if __name__ == '__main__':
    success = check_bot_structure()
    sys.exit(0 if success else 1)
