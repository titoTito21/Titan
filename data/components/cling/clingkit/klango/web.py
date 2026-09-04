# -*- coding: utf-8 -*-
"""`k_NewHttp` - the web, for an application whose whole point is the web.

The Wikipedia browser is a search box and an article reader; Klango Mastodon,
the Twitter client and the translator are the same shape. They are not
applications that happen to use the network - they ARE the network, and an
emulator that refuses it is an emulator on which they cannot work at all.
They were stopping on `attempt to call a nil value 'k_NewHttp'` before this,
and then, once the shape existed but reached nothing, on their own "cannot
connect" screen.

So this is a real client, and it is deliberately a small one:

* **`http` and `https` only.** `file:` and everything else is a way of
  reading this machine, and a Cling application is a package the user got
  from somewhere.
* **A cap on what it will bring back** (`MAX_BYTES`) and on how long it will
  wait. A page bigger than that is a download, and an application that wanted
  one should say so.
* **It never blocks the game.** Klango's own client is asynchronous - the
  library polls `resp:Done()` from inside the application's frame loop and
  draws a progress dialog while it waits - so the request runs on a thread of
  its own and `Done()` answers truthfully. A synchronous fetch here would
  freeze the application, its sound and its keyboard for the length of the
  request.
* **It follows Klango's own answers.** `GetStatusCode()` is 0 for a
  connection that never happened, -1 for one the user cancelled, and the HTTP
  code otherwise; that is what `k_GetHTTPResponseError` reads to tell the
  three apart.
"""

import threading

#: The most one request will bring back. Klango's own applications fetch
#: search results and articles; anything larger is a download.
MAX_BYTES = 8 * 1024 * 1024

#: How long to wait for the far end. Two numbers: connect, then read.
TIMEOUT = (10.0, 30.0)

#: What Cling will fetch. Everything else is a way of reading this machine.
SCHEMES = ('http://', 'https://')

#: `GetStatusCode` for a request that never reached anything, and for one the
#: application cancelled - the two `k_GetHTTPResponseError` tells apart.
NO_CONNECTION = 0
CANCELLED = -1

#: Who is asking. Klango's own client sent curl's default and it was fine
#: twenty years ago; Wikipedia now answers 403 to a request with no
#: user-agent and says so in the body, which an application reads as "the
#: article is not there". Saying what this really is - and where to complain
#: about it - is also simply the polite thing to do.
USER_AGENT = ('Titan-Cling/1.0 (Klango application emulator; '
              'https://titosofttitan.com/)')


class Request(object):
    """One fetch, running on a thread of its own."""

    def __init__(self, url='', method='GET', fields=None, userpwd='',
                 filename=''):
        self.url = str(url or '')
        self.method = (str(method or 'GET') or 'GET').upper()
        self.fields = fields or {}
        self.userpwd = str(userpwd or '')
        self.filename = str(filename or '')
        self.status = NO_CONNECTION
        self.error = 0
        self.error_text = ''
        self.body = b''
        self.effective_url = self.url
        self.finished = threading.Event()
        self.cancelled = False
        self._thread = None

    # ------------------------------------------------------------- running
    def start(self):
        if not self.url.lower().startswith(SCHEMES):
            self.error, self.error_text = 1, 'only http and https'
            self.finished.set()
            return self
        self._thread = threading.Thread(target=self._fetch,
                                        name='cling-http', daemon=True)
        self._thread.start()
        return self

    def _fetch(self):
        try:
            import requests
        except Exception as failure:
            self.error, self.error_text = 2, 'no HTTP client: %s' % failure
            self.finished.set()
            return
        try:
            authentication = None
            if ':' in self.userpwd:
                user, _sep, password = self.userpwd.partition(':')
                authentication = (user, password)
            with requests.request(
                    self.method, self.url,
                    data=self.fields if self.method != 'GET' else None,
                    params=self.fields if self.method == 'GET'
                    and self.fields else None,
                    auth=authentication, timeout=TIMEOUT, stream=True,
                    headers={'User-Agent': USER_AGENT},
                    allow_redirects=True) as answer:
                self.status = int(answer.status_code)
                self.effective_url = str(answer.url or self.url)
                chunks, total = [], 0
                for chunk in answer.iter_content(64 * 1024):
                    if self.cancelled:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                    if total >= MAX_BYTES:
                        break
                self.body = b''.join(chunks)
            if self.filename:
                self._save()
        except Exception as failure:
            self.error = 7
            self.error_text = str(failure)
            self.status = NO_CONNECTION
        finally:
            self.finished.set()

    def _save(self):
        try:
            with open(self.filename, 'wb') as handle:
                handle.write(self.body)
        except OSError as failure:
            self.error, self.error_text = 23, str(failure)

    # ------------------------------------------------------------- reading
    def done(self):
        return self.finished.is_set()

    def cancel(self):
        self.cancelled = True
        self.status = CANCELLED
        self.finished.set()
        return True

    def text(self):
        return self.body.decode('utf-8', 'replace')

    def progress(self):
        return {'downloadSize': len(self.body),
                'downloadContentLength': len(self.body)}


class Stream(object):
    """What `resp:GetStream()` answers: the body, read a piece at a time."""

    def __init__(self, request):
        self.request = request
        self.position = 0
        self.closed = False

    def available(self):
        return max(0, len(self.request.body) - self.position)

    def read(self, count=None):
        body = self.request.text()
        if count is None:
            piece = body[self.position:]
        else:
            try:
                count = int(count)
            except (TypeError, ValueError):
                count = len(body)
            piece = body[self.position:self.position + max(0, count)]
        self.position += len(piece)
        return piece

    def read_all(self):
        return self.read(None)
