# -*- coding: utf-8 -*-
"""
Refresh Elten token by logging in with password
Saves fresh credentials to titan_im_config
"""

import sys
sys.path.insert(0, 'C:\\Users\\win8k\\OneDrive\\projects\\TCE Launcher')

from src.eltenlink_client.elten_client import EltenClient
from src.settings.titan_im_config import set_eltenlink_credentials

def refresh_token():
    """Refresh token by logging in"""

    print("=" * 80)
    print("ELTEN TOKEN REFRESH")
    print("=" * 80)

    # Credentials from user
    username = "titomaton"
    password = "tito.Blinder123456"

    print(f"\nLogging in as: {username}")
    print("Password: ***********")

    # Create client and login
    client = EltenClient()

    try:
        status, user, token = client.login(username, password)

        if status == 0:
            print(f"\nOK LOGIN SUCCESS!")
            print(f"  Username: {user}")
            print(f"  Token length: {len(token)} chars")
            print(f"  Token: {token[:20]}...{token[-20:]}")

            # Save to titan_im_config (with password for auto-refresh)
            print(f"\nSaving to titan_im_config (with password for auto-refresh)...")
            set_eltenlink_credentials(user, token, password)
            print("OK Credentials saved!")

            # Test if token works
            print(f"\n" + "=" * 80)
            print("TESTING FRESH TOKEN")
            print("=" * 80)

            # Test contacts
            print("\n[1/3] Testing CONTACTS...")
            try:
                contacts = client.get_contacts()
                print(f"OK Contacts: {len(contacts)}")
                if contacts:
                    print(f"  First 5: {contacts[:5]}")
            except Exception as e:
                print(f"ERROR Error: {e}")

            # Test conversations
            print("\n[2/3] Testing CONVERSATIONS...")
            try:
                convs = client.get_conversations(limit=10)
                print(f"OK Conversations: {len(convs)}")
                if convs:
                    print(f"  First 3:")
                    for i, conv in enumerate(convs[:3]):
                        print(f"    {i+1}. {conv.get('user', 'N/A')}: {conv.get('subject', 'N/A')}")
            except Exception as e:
                print(f"ERROR Error: {e}")

            # Test blog
            print("\n[3/3] Testing BLOG POSTS...")
            try:
                exists = client.check_blog_exists(username)
                if exists:
                    posts = client.get_blog_posts(username, 0)
                    print(f"OK Blog posts: {len(posts)}")
                    if posts:
                        print(f"  First 3:")
                        for i, post in enumerate(posts[:3]):
                            print(f"    {i+1}. {post.get('name', 'N/A')}")
                else:
                    print("  Blog doesn't exist")
            except Exception as e:
                print(f"ERROR Error: {e}")

            print("\n" + "=" * 80)
            print("TOKEN REFRESH COMPLETE!")
            print("=" * 80)
            print("\nToken is now valid and saved to titan_im_config.")
            print("You can now run: python test_elten_auto.py")

        elif status == -5:
            print("\nERROR 2FA REQUIRED!")
            print("  This account has two-factor authentication enabled.")
            print("  Cannot refresh token automatically.")

        else:
            print(f"\nERROR LOGIN FAILED!")
            print(f"  Status: {status}")
            print(f"  This usually means wrong username/password.")

    except Exception as e:
        print(f"\nERROR EXCEPTION: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    refresh_token()
