# Fix Crash Command

Analyze the codebase for common crash-causing issues and fix them.

## What to check:

1. **Threading Issues:**
   - Look for daemon threads without proper cleanup
   - Check for blocking `thread.join()` calls
   - Verify all threads have stop events/flags
   - Ensure thread-safe access to shared resources

2. **wx.App Issues:**
   - Verify only ONE wx.App instance is created
   - Check proper cleanup in finally blocks
   - Look for wx.CallAfter usage in threads

3. **COM/Windows API Issues:**
   - Check for proper COM initialization/cleanup
   - Look for unhandled COM errors
   - Verify timeout handling for slow operations

4. **Resource Cleanup:**
   - Verify proper cleanup in __del__ and cleanup() methods
   - Check for circular references preventing garbage collection
   - Look for unclosed files, connections, or handles

5. **Error Handling:**
   - Add try-except blocks around crash-prone code
   - Ensure errors are logged before re-raising
   - Check for catching overly broad exceptions

## Action:

1. Search for common threading patterns that can cause crashes
2. Identify and fix any issues found
3. Add proper cleanup code where needed
4. Test that the program starts and stops cleanly
5. Report findings and fixes made
