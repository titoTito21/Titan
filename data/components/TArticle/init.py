import wx
import wx.html2
import requests
from bs4 import BeautifulSoup
import threading
import os
import gettext
from sound import play_sound

# Set up local translations for TArticle component
def setup_translations():
    """Setup translations for TArticle component"""
    component_dir = os.path.dirname(__file__)
    locale_dir = os.path.join(component_dir, 'languages')
    
    # Try to get language from main app, default to 'pl'
    try:
        from translation import language_code
        lang = language_code
    except ImportError:
        lang = 'pl'
    
    try:
        translation = gettext.translation('tarticle', locale_dir, languages=[lang], fallback=True)
        return translation.gettext
    except:
        # Fallback to simple function that returns the original text
        return lambda x: x

_ = setup_translations()

class ArticleFrame(wx.Frame):
    def __init__(self, *args, **kwargs):
        super(ArticleFrame, self).__init__(*args, **kwargs)
        self.InitUI()

    def InitUI(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Create WebView control
        self.webview = wx.html2.WebView.New(panel)
        
        vbox.Add(self.webview, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)
        
        panel.SetSizer(vbox)
        
        self.SetSize((900, 700))
        self.SetTitle(_("Article Viewer - TArticle"))
        self.Centre()

    def load_article_content(self, url):
        """Extract and display clean article content from URL"""
        def fetch_content():
            try:
                wx.CallAfter(self.SetTitle, _("Loading article..."))
                
                # Try Wikipedia API first for better text extraction
                if 'wikipedia.org' in url:
                    wiki_content = self.try_wikipedia_api(url)
                    if wiki_content:
                        return
                
                # Fallback to web scraping method
                # Set user agent and headers for better compatibility
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'pl,en;q=0.5',
                    'Accept-Encoding': 'gzip, deflate',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1'
                }
                
                response = requests.get(url, headers=headers, timeout=15)
                response.raise_for_status()
                
                # Fix encoding issues - especially important for Polish characters
                if response.encoding is None or response.encoding == 'ISO-8859-1':
                    # Try to detect encoding from content
                    response.encoding = response.apparent_encoding
                
                # Ensure UTF-8 encoding for Polish characters
                if 'wikipedia.org' in url and response.encoding.lower() not in ['utf-8', 'utf8']:
                    response.encoding = 'utf-8'
                
                # Parse HTML content with proper encoding
                soup = BeautifulSoup(response.content, 'html.parser', from_encoding=response.encoding)
                
                # Remove unwanted elements globally
                for element in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'iframe', 'form', 'noscript']):
                    element.decompose()
                
                # Remove ads, social media, and other unwanted content
                unwanted_selectors = [
                    '.advertisement', '.ads', '.ad', '.social', '.share', '.comments', 
                    '.related', '.sidebar', '.menu', '.navigation', '.breadcrumb',
                    '.cookie', '.newsletter', '.subscription', '.popup', '.modal'
                ]
                for selector in unwanted_selectors:
                    for element in soup.select(selector):
                        element.decompose()
                
                # Try to find main content area with site-specific selectors
                content = self.extract_content_by_site(soup, url)
                
                if content:
                    # Clean up the content more thoroughly
                    content = self.clean_article_content(content)
                    
                    # Get the title
                    title = soup.find('title')
                    title_text = title.get_text() if title else _("Article")
                    
                    # Create clean HTML
                    clean_html = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <meta charset="utf-8">
                        <title>{title_text}</title>
                        <style>
                            body {{
                                font-family: Arial, sans-serif;
                                line-height: 1.6;
                                margin: 20px;
                                max-width: 800px;
                                margin: 20px auto;
                                padding: 0 20px;
                            }}
                            h1, h2, h3, h4, h5, h6 {{
                                color: #333;
                                margin-top: 1.5em;
                            }}
                            p {{
                                margin: 1em 0;
                            }}
                            img {{
                                max-width: 100%;
                                height: auto;
                            }}
                            a {{
                                color: #0066cc;
                                text-decoration: none;
                            }}
                            a:hover {{
                                text-decoration: underline;
                            }}
                            blockquote {{
                                border-left: 4px solid #ccc;
                                margin: 1em 0;
                                padding-left: 1em;
                                color: #666;
                            }}
                        </style>
                    </head>
                    <body>
                        <h1>{title_text}</h1>
                        {content}
                    </body>
                    </html>
                    """
                    
                    wx.CallAfter(self.webview.SetPage, clean_html, url)
                    wx.CallAfter(self.SetTitle, f"{title_text} - TArticle")
                    
                else:
                    wx.CallAfter(self.show_error, _("Could not extract article content from this URL"))
                    
            except requests.RequestException as e:
                wx.CallAfter(self.show_error, _("Error loading article: ") + str(e))
            except Exception as e:
                wx.CallAfter(self.show_error, _("Unexpected error: ") + str(e))
        
        threading.Thread(target=fetch_content, daemon=True).start()

    def try_wikipedia_api(self, url):
        """Try to extract Wikipedia content using MediaWiki API"""
        try:
            from urllib.parse import urlparse, parse_qs, unquote
            
            # Parse Wikipedia URL to get article title
            parsed = urlparse(url)
            path_parts = parsed.path.split('/')
            
            # Extract title from different Wikipedia URL formats
            title = None
            if '/wiki/' in parsed.path:
                title = parsed.path.split('/wiki/', 1)[1]
            elif 'title=' in parsed.query:
                title = parse_qs(parsed.query).get('title', [None])[0]
            
            if not title:
                return False
                
            title = unquote(title).replace('_', ' ')
            
            # Determine language from URL
            domain_parts = parsed.netloc.split('.')
            lang = 'en'  # default
            if len(domain_parts) >= 3 and domain_parts[0] != 'www':
                lang = domain_parts[0]
            
            # Use MediaWiki API to get clean text - use parse action for full content
            api_url = f"https://{lang}.wikipedia.org/w/api.php"
            api_params = {
                'action': 'parse',
                'format': 'json',
                'page': title,
                'prop': 'text|displaytitle|categories',
                'disableeditsection': 1,
                'disabletoc': 1,
                'utf8': 1
            }
            
            headers = {
                'User-Agent': 'TArticle/1.0 (TCE Launcher; educational use)'
            }
            
            response = requests.get(api_url, params=api_params, headers=headers, timeout=15)
            response.raise_for_status()
            
            data = response.json()
            
            if 'parse' not in data:
                return False
                
            parse_data = data['parse']
            
            if 'text' not in parse_data:
                return False
                
            extract = parse_data['text']['*']  # Full HTML content
            page_title = parse_data.get('displaytitle', title)
            
            # Clean up the HTML content from Wikipedia-specific elements
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(extract, 'html.parser')
            
            # Remove Wikipedia-specific unwanted elements
            unwanted_wiki_selectors = [
                '.navbox', '.infobox', '.navigation-not-searchable', '.mw-navigation', 
                '.printfooter', '.catlinks', '.thumbcaption', '.thumbinner',
                '.navbox-wrapper', '.vertical-navbox', '.sidebar', '.tright', '.tleft',
                '.mbox', '.ambox', '.tmbox', '.imbox', '.cmbox', '.ombox', '.fmbox',
                '.hatnote', '.rellink', '.dablink', '.successbox', '.errorbox',
                '.cite', '.citation', '.reference', '.reflist', '.references',
                '#toc', '.toc', '.toccolours', '.sistersitebox', '.metadata',
                '.navbox-inner', '.collapsible', '.autocollapse', '.collapsed',
                '.navigation-not-searchable', '.noprint', '.nomobile',
                '.mw-editsection', '.mw-editsection-bracket'
            ]
            
            for selector in unwanted_wiki_selectors:
                for element in soup.select(selector):
                    element.decompose()
            
            # Also remove elements by common Wikipedia class patterns
            for element in soup.find_all(attrs={"class": True}):
                classes = ' '.join(element.get('class', []))
                if any(pattern in classes.lower() for pattern in ['navbox', 'infobox', 'hatnote', 'mbox', 'navigation', 'editsection']):
                    element.decompose()
            
            extract = str(soup)
            canonical_url = url
            
            # Create clean HTML from the extract
            clean_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <title>{page_title}</title>
                <style>
                    body {{
                        font-family: Arial, sans-serif;
                        line-height: 1.6;
                        margin: 20px;
                        max-width: 800px;
                        margin: 20px auto;
                        padding: 0 20px;
                    }}
                    h1, h2, h3, h4, h5, h6 {{
                        color: #333;
                        margin-top: 1.5em;
                    }}
                    p {{
                        margin: 1em 0;
                    }}
                    .wiki-source {{
                        background: #f0f0f0;
                        padding: 10px;
                        border-left: 4px solid #0066cc;
                        margin: 20px 0;
                        font-size: 0.9em;
                    }}
                </style>
            </head>
            <body>
                <div class="wiki-source">
                    <strong>{_("Source")}:</strong> <a href="{canonical_url}" target="_blank">Wikipedia</a>
                </div>
                <h1>{page_title}</h1>
                {extract}
            </body>
            </html>
            """
            
            wx.CallAfter(self.webview.SetPage, clean_html, canonical_url)
            wx.CallAfter(self.SetTitle, f"{page_title} - TArticle (Wikipedia API)")
            
            return True
            
        except Exception as e:
            # If Wikipedia API fails, we'll fall back to web scraping
            print(f"Wikipedia API failed: {e}")
            return False

    def extract_content_by_site(self, soup, url):
        """Extract content using site-specific selectors"""
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.lower()
        
        # Site-specific selectors
        if 'onet.pl' in domain:
            # Onet.pl article selectors
            selectors = [
                '.art_body',
                '.articleContent',
                '.detail-body', 
                'article .content',
                '.artText'
            ]
        elif 'wp.pl' in domain or 'wirtualnapolska.pl' in domain:
            # WP.pl selectors
            selectors = [
                '.article-content',
                '.sc-bdfBwQ',
                '.article-body',
                'article .content',
                '.entry-content'
            ]
        elif 'gazeta.pl' in domain:
            # Gazeta.pl selectors
            selectors = [
                '.art_content',
                'article .content',
                '.article-body',
                '.entry-content'
            ]
        elif 'interia.pl' in domain:
            # Interia.pl selectors
            selectors = [
                '.article-content',
                '.news-content',
                '.material-content',
                'article .content'
            ]
        elif 'rmf24.pl' in domain or 'rmf.fm' in domain:
            # RMF selectors
            selectors = [
                '.article-content',
                '.post-content',
                '.newsContent',
                'article .content'
            ]
        elif 'tvn24.pl' in domain:
            # TVN24 selectors
            selectors = [
                '.article-content',
                '.article-body',
                '.post-content',
                'article .content'
            ]
        elif 'polsatnews.pl' in domain:
            # Polsat News selectors
            selectors = [
                '.article-content',
                '.article-body',
                '.news-content',
                'article .content'
            ]
        elif 'se.pl' in domain:
            # Super Express selectors
            selectors = [
                '.article-content',
                '.post-content',
                '.art-content',
                'article .content'
            ]
        elif 'fakt.pl' in domain:
            # Fakt.pl selectors
            selectors = [
                '.article-content',
                '.art-content', 
                '.post-content',
                'article .content'
            ]
        elif 'wikipedia.org' in domain:
            # Wikipedia selectors (improved for better content extraction)
            selectors = [
                '.mw-parser-output',
                '#mw-content-text .mw-parser-output', 
                '#mw-content-text',
                '#content .mw-body-content',
                '.mw-body-content',
                '#bodyContent'
            ]
            
            # Remove Wikipedia-specific unwanted elements BEFORE content extraction
            unwanted_wiki_selectors = [
                '.navbox', '.infobox', '.navigation-not-searchable', '.mw-navigation', 
                '.printfooter', '.catlinks', '.thumbcaption', '.thumbinner',
                '.navbox-wrapper', '.vertical-navbox', '.sidebar', '.tright', '.tleft',
                '.mbox', '.ambox', '.tmbox', '.imbox', '.cmbox', '.ombox', '.fmbox',
                '.hatnote', '.rellink', '.dablink', '.successbox', '.errorbox',
                '.cite', '.citation', '.reference', '.reflist', '.references',
                '#toc', '.toc', '.toccolours', '.sistersitebox', '.metadata',
                '.navbox-inner', '.collapsible', '.autocollapse', '.collapsed',
                '.navigation-not-searchable', '.noprint', '.nomobile'
            ]
            
            for selector in unwanted_wiki_selectors:
                for element in soup.select(selector):
                    element.decompose()
                    
            # Also remove elements by common Wikipedia class patterns
            for element in soup.find_all(attrs={"class": True}):
                classes = ' '.join(element.get('class', []))
                if any(pattern in classes.lower() for pattern in ['navbox', 'infobox', 'hatnote', 'mbox', 'navigation']):
                    element.decompose()
        elif 'bbc.com' in domain or 'bbc.co.uk' in domain:
            # BBC selectors
            selectors = [
                '[data-component="text-block"]',
                '.story-body',
                '.article-body',
                'article .content'
            ]
        elif 'cnn.com' in domain:
            # CNN selectors
            selectors = [
                '.article-body',
                '.zn-body__paragraph',
                '.pg-rail-tall__body',
                'article .content'
            ]
        elif 'theguardian.com' in domain:
            # The Guardian selectors
            selectors = [
                '.content__article-body',
                '[data-gu-name="body"]',
                '.article-body',
                'article .content'
            ]
        else:
            # Generic selectors for unknown sites
            selectors = [
                'article',
                '[role="main"] article', 
                '.article-content', 
                '.post-content', 
                '.entry-content',
                '.content',
                '.article-body',
                '.story-content',
                '.news-content',
                'main article',
                '[itemtype*="Article"]'
            ]
        
        # Try selectors in order
        for selector in selectors:
            content = soup.select_one(selector)
            if content:
                return content
        
        # Final fallback - try to find the largest text block
        return self.extract_main_content_fallback(soup)

    def extract_main_content_fallback(self, soup):
        """Fallback method to extract main content by finding largest text block"""
        candidates = []
        
        # Look for potential content containers
        for tag in soup.find_all(['div', 'section', 'article', 'main']):
            if tag is None:
                continue
            if tag.get_text(strip=True):
                # Calculate text density (text length / total elements)
                text_length = len(tag.get_text(strip=True))
                element_count = len(tag.find_all())
                
                # Skip if too few words (likely not main content)
                word_count = len(tag.get_text(strip=True).split())
                if word_count < 50:
                    continue
                    
                # Calculate score based on text density and word count
                density = text_length / max(element_count, 1)
                score = density * word_count
                
                candidates.append((tag, score, text_length, word_count))
        
        if candidates:
            # Sort by score and return the best candidate
            candidates.sort(key=lambda x: x[1], reverse=True)
            return candidates[0][0]
        
        # Ultimate fallback - return body
        return soup.find('body')

    def clean_article_content(self, content):
        """Clean article content by removing unwanted elements"""
        if not content or content is None:
            return content
            
        # Remove unwanted elements by class patterns
        unwanted_patterns = [
            'ad', 'ads', 'advertisement', 'banner', 'social', 'share', 'sharing',
            'comment', 'comments', 'related', 'sidebar', 'widget', 'promo',
            'newsletter', 'subscription', 'popup', 'modal', 'cookie',
            'navigation', 'nav', 'menu', 'breadcrumb', 'tag', 'tags',
            'author-bio', 'bio', 'byline', 'meta', 'footer', 'header'
        ]
        
        for element in content.find_all(['div', 'span', 'section', 'aside']):
            if element is None:
                continue
                
            classes = element.get('class', [])
            element_id = element.get('id', '')
            
            # Check if any class or id contains unwanted patterns
            if classes or element_id:
                text_to_check = ' '.join(classes + [element_id]).lower()
                if any(pattern in text_to_check for pattern in unwanted_patterns):
                    element.decompose()
                    continue
            
            # Remove elements with little text content but many links (likely navigation)
            text_length = len(element.get_text(strip=True))
            links_count = len(element.find_all('a'))
            if text_length > 0 and links_count > 0:
                link_ratio = links_count / (text_length / 100.0)  # links per 100 chars
                if link_ratio > 2:  # More than 2 links per 100 characters
                    element.decompose()
        
        # Remove empty elements
        for element in content.find_all():
            if element is None:
                continue
            if not element.get_text(strip=True) and not element.find('img'):
                element.decompose()
        
        # Fix relative URLs for images and links
        self.fix_relative_urls(content)
        
        return content

    def fix_relative_urls(self, content):
        """Convert relative URLs to absolute URLs"""
        # This would need the base URL, but for now we'll keep it simple
        # In a future version, we could implement proper URL resolution
        pass

    def show_error(self, message):
        """Show error message in WebView"""
        error_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>{_("Error")}</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    text-align: center;
                    margin: 50px;
                    color: #666;
                }}
                .error {{
                    color: #cc0000;
                    font-size: 18px;
                    margin: 20px 0;
                }}
            </style>
        </head>
        <body>
            <h1>{_("Error")}</h1>
            <div class="error">{message}</div>
        </body>
        </html>
        """
        self.webview.SetPage(error_html, "")
        self.SetTitle(_("Error - TArticle"))

def show_url_dialog():
    """Show dialog to input article URL"""
    dialog = wx.TextEntryDialog(
        None,
        _("Please paste a link to the article, e.g., to Wikipedia page"),
        _("Article URL"),
        ""
    )
    
    if dialog.ShowModal() == wx.ID_OK:
        url = dialog.GetValue().strip()
        if url:
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            
            article_frame = ArticleFrame(None)
            article_frame.Show()
            article_frame.load_article_content(url)
        else:
            wx.MessageBox(_("Please enter a valid URL"), _("Error"), wx.OK | wx.ICON_ERROR)
    
    dialog.Destroy()

def on_tarticle_menu_action(parent_frame):
    """Menu action handler"""
    show_url_dialog()

def add_menu(component_manager):
    """Register menu item"""
    component_manager.register_menu_function(_("Article Viewer"), on_tarticle_menu_action)

def initialize(app):
    """Initialize component"""
    pass