#!/usr/bin/env python3
"""
Script to safely clear comtypes cache to fix VTable errors.
Run with administrative privileges.
"""
import os
import shutil
import sys

def clear_comtypes_cache():
    """Clear comtypes generated cache files."""
    try:
        # Find comtypes installation
        import comtypes
        comtypes_path = os.path.dirname(comtypes.__file__)
        gen_path = os.path.join(comtypes_path, 'gen')
        
        print(f"Comtypes path: {comtypes_path}")
        print(f"Gen cache path: {gen_path}")
        
        if not os.path.exists(gen_path):
            print("No comtypes cache found.")
            return True
            
        # List files to remove
        files_to_remove = []
        for root, dirs, files in os.walk(gen_path):
            for file in files:
                if file.endswith(('.py', '.pyc', '.pyo')) and file != '__init__.py':
                    files_to_remove.append(os.path.join(root, file))
        
        print(f"Found {len(files_to_remove)} cache files to remove:")
        for file_path in files_to_remove[:10]:  # Show first 10
            print(f"  {file_path}")
        if len(files_to_remove) > 10:
            print(f"  ... and {len(files_to_remove) - 10} more")
        
        # Remove files
        removed_count = 0
        failed_count = 0
        
        for file_path in files_to_remove:
            try:
                os.remove(file_path)
                removed_count += 1
            except Exception as e:
                print(f"Failed to remove {file_path}: {e}")
                failed_count += 1
        
        # Try to remove __pycache__ directories
        for root, dirs, files in os.walk(gen_path):
            for dir_name in dirs:
                if dir_name == '__pycache__':
                    pycache_path = os.path.join(root, dir_name)
                    try:
                        shutil.rmtree(pycache_path)
                        print(f"Removed __pycache__: {pycache_path}")
                    except Exception as e:
                        print(f"Failed to remove __pycache__ {pycache_path}: {e}")
                        failed_count += 1
        
        print(f"\nCache cleanup completed:")
        print(f"  Removed: {removed_count} files")
        print(f"  Failed: {failed_count} files")
        
        return failed_count == 0
        
    except Exception as e:
        print(f"Error during cache cleanup: {e}")
        return False

if __name__ == "__main__":
    print("Comtypes Cache Cleaner")
    print("=" * 30)
    
    success = clear_comtypes_cache()
    
    if success:
        print("\nCache cleared successfully!")
        print("COM VTable errors should be resolved.")
    else:
        print("\nSome files could not be removed.")
        print("Try running as administrator or restart your application.")
    
    input("\nPress Enter to exit...")