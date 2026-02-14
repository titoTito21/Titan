import os
import json
import hashlib
import shutil
from datetime import datetime
import tempfile

class GenerationCache:
    """Manages local cache of generated audio to prevent unnecessary regeneration"""

    def __init__(self, cache_dir=None, max_items=10):
        if cache_dir is None:
            cache_dir = os.path.join(tempfile.gettempdir(), 'elevenlabs_cache')

        self.cache_dir = cache_dir
        self.max_items = max_items
        self.cache_file = os.path.join(cache_dir, 'cache_index.json')

        # Create cache directory if it doesn't exist
        os.makedirs(cache_dir, exist_ok=True)

        # Load existing cache index
        self.cache_index = self._load_cache_index()

    def _load_cache_index(self):
        """Load cache index from file"""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return []
        return []

    def _save_cache_index(self):
        """Save cache index to file"""
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache_index, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving cache index: {e}")

    def _generate_cache_key(self, text, voice_id, model_id, settings):
        """Generate unique cache key based on generation parameters"""
        # Create a string with all parameters
        params = f"{text}|{voice_id}|{model_id}|{settings.get('stability', 0.5)}|{settings.get('similarity_boost', 0.75)}|{settings.get('style', 0)}|{settings.get('use_speaker_boost', True)}"
        # Hash it
        return hashlib.md5(params.encode('utf-8')).hexdigest()

    def add(self, text, voice_id, voice_name, model_id, settings, audio_data):
        """Add a generation to the cache"""
        try:
            # Generate cache key
            cache_key = self._generate_cache_key(text, voice_id, model_id, settings)

            # Check if already cached
            for item in self.cache_index:
                if item['key'] == cache_key:
                    # Update timestamp
                    item['timestamp'] = datetime.now().isoformat()
                    self._save_cache_index()
                    return cache_key

            # Save audio file
            audio_path = os.path.join(self.cache_dir, f"{cache_key}.mp3")
            with open(audio_path, 'wb') as f:
                f.write(audio_data)

            # Add to index
            cache_entry = {
                'key': cache_key,
                'text': text[:100],  # Store first 100 chars for display
                'full_text_hash': hashlib.md5(text.encode('utf-8')).hexdigest(),
                'voice_id': voice_id,
                'voice_name': voice_name,
                'model_id': model_id,
                'settings': settings,
                'timestamp': datetime.now().isoformat(),
                'audio_path': audio_path,
                'character_count': len(text)
            }

            self.cache_index.insert(0, cache_entry)  # Add to front

            # Limit cache size
            while len(self.cache_index) > self.max_items:
                # Remove oldest item
                old_item = self.cache_index.pop()
                try:
                    if os.path.exists(old_item['audio_path']):
                        os.remove(old_item['audio_path'])
                except:
                    pass

            self._save_cache_index()
            return cache_key

        except Exception as e:
            print(f"Error adding to cache: {e}")
            return None

    def get(self, text, voice_id, model_id, settings):
        """Get cached audio if it exists"""
        try:
            cache_key = self._generate_cache_key(text, voice_id, model_id, settings)

            for item in self.cache_index:
                if item['key'] == cache_key:
                    # Check if file still exists
                    if os.path.exists(item['audio_path']):
                        with open(item['audio_path'], 'rb') as f:
                            return f.read()
                    else:
                        # Remove from index if file is missing
                        self.cache_index.remove(item)
                        self._save_cache_index()
                        return None

            return None

        except Exception as e:
            print(f"Error getting from cache: {e}")
            return None

    def check_similar(self, text, threshold=0.9):
        """Check if similar text has been generated recently"""
        try:
            text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()

            # Check for exact match first
            for item in self.cache_index:
                if item['full_text_hash'] == text_hash:
                    return {
                        'found': True,
                        'exact': True,
                        'item': item
                    }

            # Check for very similar text (first 100 chars match)
            text_preview = text[:100]
            for item in self.cache_index:
                if item['text'] == text_preview:
                    return {
                        'found': True,
                        'exact': False,
                        'item': item
                    }

            return {'found': False}

        except Exception as e:
            print(f"Error checking similar: {e}")
            return {'found': False}

    def get_recent(self, limit=5):
        """Get most recent cache entries"""
        return self.cache_index[:limit]

    def get_by_key(self, cache_key):
        """Get cached audio by key"""
        try:
            for item in self.cache_index:
                if item['key'] == cache_key:
                    if os.path.exists(item['audio_path']):
                        with open(item['audio_path'], 'rb') as f:
                            return f.read()
            return None
        except Exception as e:
            print(f"Error getting by key: {e}")
            return None

    def clear(self):
        """Clear all cache"""
        try:
            for item in self.cache_index:
                try:
                    if os.path.exists(item['audio_path']):
                        os.remove(item['audio_path'])
                except:
                    pass

            self.cache_index = []
            self._save_cache_index()

        except Exception as e:
            print(f"Error clearing cache: {e}")

    def get_cache_size(self):
        """Get total cache size in bytes"""
        total_size = 0
        for item in self.cache_index:
            try:
                if os.path.exists(item['audio_path']):
                    total_size += os.path.getsize(item['audio_path'])
            except:
                pass
        return total_size

    def get_cache_info(self):
        """Get cache statistics"""
        return {
            'item_count': len(self.cache_index),
            'max_items': self.max_items,
            'total_size_mb': self.get_cache_size() / (1024 * 1024),
            'cache_dir': self.cache_dir
        }
