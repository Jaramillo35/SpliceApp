"""
Session Manager - Save and restore browser sessions using cookies
"""

import json
import os
from pathlib import Path
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class SessionManager:
    """Manages browser session cookies for persistent login"""
    
    def __init__(self, session_dir="sessions"):
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(exist_ok=True)
        self.cookies_file = self.session_dir / "chrysler_cookies.json"
        self.session_info_file = self.session_dir / "session_info.json"
    
    async def save_session(self, page, username):
        """
        Save browser cookies and session info to file
        
        Args:
            page: Playwright page object
            username: Username for session identification
        """
        try:
            # Get cookies
            cookies = await page.context.cookies()
            
            # Get storage state (localStorage, sessionStorage)
            storage_state = await page.context.storage_state()
            
            # Prepare session data
            session_data = {
                "username": username,
                "timestamp": datetime.now().isoformat(),
                "url": page.url,
                "cookies": cookies,
                "storage_state": storage_state
            }
            
            # Save to file
            with open(self.cookies_file, 'w') as f:
                json.dump(session_data, f, indent=2)
            
            logger.info(f"✓ Session saved for user: {username}")
            logger.info(f"  Cookies: {len(cookies)} stored")
            logger.info(f"  Location: {self.cookies_file}")
            
            return True
            
        except Exception as e:
            logger.error(f"✗ Failed to save session: {e}")
            return False
    
    async def restore_session(self, page):
        """
        Restore browser cookies from file
        
        Args:
            page: Playwright page object
            
        Returns:
            bool: True if session restored successfully, False otherwise
        """
        try:
            if not self.cookies_file.exists():
                logger.warning("No saved session found")
                return False
            
            # Load session data
            with open(self.cookies_file, 'r') as f:
                session_data = json.load(f)
            
            cookies = session_data.get("cookies", [])
            storage_state = session_data.get("storage_state", {})
            username = session_data.get("username", "Unknown")
            saved_time = session_data.get("timestamp", "Unknown")
            
            # Add cookies to context
            if cookies:
                await page.context.add_cookies(cookies)
            
            logger.info(f"✓ Session restored for user: {username}")
            logger.info(f"  Saved at: {saved_time}")
            logger.info(f"  Cookies restored: {len(cookies)}")
            
            return True
            
        except Exception as e:
            logger.error(f"✗ Failed to restore session: {e}")
            return False
    
    def clear_session(self):
        """Clear saved session files"""
        try:
            if self.cookies_file.exists():
                self.cookies_file.unlink()
                logger.info(f"✓ Cleared session: {self.cookies_file}")
            return True
        except Exception as e:
            logger.error(f"✗ Failed to clear session: {e}")
            return False
    
    def session_exists(self):
        """Check if a saved session exists"""
        return self.cookies_file.exists()
    
    def get_session_info(self):
        """Get info about saved session"""
        try:
            if not self.cookies_file.exists():
                return None
            
            with open(self.cookies_file, 'r') as f:
                session_data = json.load(f)
            
            return {
                "username": session_data.get("username"),
                "timestamp": session_data.get("timestamp"),
                "url": session_data.get("url"),
                "cookie_count": len(session_data.get("cookies", []))
            }
        except:
            return None
