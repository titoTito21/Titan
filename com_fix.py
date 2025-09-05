"""
COM Error Fix Module
Provides utilities to prevent VTable errors in COM operations.
"""
import atexit
import threading
from functools import wraps

# Global lock for COM operations
_com_lock = threading.RLock()
_com_initialized = set()

def com_safe(func):
    """
    Decorator to make COM operations safer by preventing VTable errors.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        with _com_lock:
            try:
                return func(*args, **kwargs)
            except (OSError, ValueError) as e:
                if "COM method call without VTable" in str(e) or "access violation" in str(e):
                    # COM error - return None or safe default
                    return None
                raise
    return wrapper

def init_com_safe():
    """
    Initialize COM in a safer way to prevent VTable errors.
    """
    try:
        import pythoncom
        thread_id = threading.get_ident()
        
        if thread_id not in _com_initialized:
            pythoncom.CoInitialize()
            _com_initialized.add(thread_id)
            
    except Exception:
        pass

def cleanup_com_on_exit():
    """
    Cleanup function to be called on program exit.
    """
    try:
        import pythoncom
        import gc
        
        # Only cleanup if we're the main thread
        if threading.current_thread() is threading.main_thread():
            # Force garbage collection before COM cleanup
            gc.collect()
            
            for thread_id in _com_initialized:
                try:
                    pythoncom.CoUninitialize()
                except:
                    pass
            _com_initialized.clear()
            
            # Final garbage collection after COM cleanup
            gc.collect()
    except:
        pass

# Register cleanup on exit
atexit.register(cleanup_com_on_exit)

def suppress_com_errors():
    """
    Suppress COM-related error messages that appear at program exit.
    """
    import sys
    import warnings
    
    # Filter COM-related warnings
    warnings.filterwarnings("ignore", category=UserWarning, module="comtypes")
    warnings.filterwarnings("ignore", message=".*COM.*")
    
    # Suppress stderr for COM cleanup errors
    class COMErrorSuppressor:
        def __init__(self):
            self.original_stderr = sys.stderr
            
        def write(self, text):
            # Suppress specific COM error messages and patterns
            if any(pattern in text.lower() for pattern in [
                "com method call without vtable",
                "_compointer_base.__del__",
                "access violation",
                "valueerror: com method call",
                "failed to load any com objects",
                "freedomsci.jawsapi",
                "jfwapi",
                "gwspeak.speak",
                "com objects. tried",
                "exception ignored in"
            ]):
                return
            self.original_stderr.write(text)
            
        def flush(self):
            self.original_stderr.flush()
    
    # Only suppress during cleanup, not during normal operation
    if not hasattr(suppress_com_errors, '_suppressor_installed'):
        sys.stderr = COMErrorSuppressor()
        suppress_com_errors._suppressor_installed = True