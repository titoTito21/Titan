#!/usr/bin/env python3
"""Simple stereo speech test"""

import win32com.client
import tempfile
import os

def test_sapi_basic():
    print("Testing basic SAPI5...")
    
    try:
        import pythoncom
        pythoncom.CoInitialize()
        
        sapi = win32com.client.Dispatch("SAPI.SpVoice")
        print("SAPI5 initialized successfully")
        
        # Test basic speech
        sapi.Speak("Test basic speech")
        print("Basic speech test completed")
        
        # Test file generation
        temp_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        temp_path = temp_file.name
        temp_file.close()
        
        file_stream = win32com.client.Dispatch("SAPI.SpFileStream")
        file_stream.Open(temp_path, 3)  # SSFMCreateForWrite
        
        original_output = sapi.AudioOutputStream
        sapi.AudioOutputStream = file_stream
        
        sapi.Speak("Test file generation")
        sapi.WaitUntilDone(5000)
        
        file_stream.Close()
        sapi.AudioOutputStream = original_output
        
        if os.path.exists(temp_path):
            size = os.path.getsize(temp_path)
            print(f"File generated: {temp_path}, size: {size} bytes")
            
            if size > 100:
                print("File generation test PASSED")
            else:
                print("File generation test FAILED - file too small")
                
            # Clean up
            os.unlink(temp_path)
        else:
            print("File generation test FAILED - file not created")
            
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_sapi_basic()