// Rich mail bodies for the web portal - the browser-side twin of the desktop
// client's src/network/mail_format.py.
//
// Same three formats (plain, Markdown, HTML), same rule about what leaves the
// page: a message is markup written by a stranger, so it is rendered inside a
// sandboxed frame whose content policy blocks every remote fetch and every
// script. No tracking pixel, no web font, no code - opening a message tells its
// sender nothing.
(function () {
  'use strict';

  var CSP = "default-src 'none'; img-src data: cid:; style-src 'unsafe-inline'; " +
            "font-src data:; form-action 'none'; frame-src 'none'; script-src 'none'";
  var CSP_TAGS = '<meta http-equiv="Content-Security-Policy" content="' + CSP + '">' +
                 '<meta name="referrer" content="no-referrer">';
  var BASE_STYLE = '<style>html,body{margin:0;padding:.5rem;font:inherit;' +
                   'color:inherit;background:transparent;word-wrap:break-word}' +
                   'img{max-width:100%;height:auto}table{border-collapse:collapse}' +
                   'td,th{border:1px solid currentColor;padding:.25rem}</style>';

  var HTML_HINT = /<\s*(?:html|body|div|p|br|table|tr|td|ul|ol|li|h[1-6]|blockquote|span|a\s|img\s)/i;
  var MD_STRONG = [/^\s{0,3}#{1,6}\s+\S/m, /^\s*(?:```|~~~)/m, /!?\[[^\]]*\]\([^)\s]+\)/,
                   /^\s*\|.+\|\s*$/m];
  var MD_WEAK = [/^\s*[-*+]\s+\S/m, /^\s*\d+[.)]\s+\S/m, /\*\*[^*\n]+\*\*/, /`[^`\n]+`/];
  var BARE_URL = /(?:https?:\/\/|www\.)[^\s<>"')\]]+/gi;

  function escapeHtml(text) {
    return String(text == null ? '' : text)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function absoluteUrl(url) {
    url = (url || '').trim();
    if (!url) return '';
    if (/^www\./i.test(url)) return 'http://' + url;
    if (url.indexOf('@') >= 0 && url.indexOf('://') < 0 && !/^mailto:/i.test(url)) {
      return 'mailto:' + url;
    }
    return url;
  }

  function looksLikeHtml(source) {
    return !!source && (/<!doctype\s+html/i.test(source) || HTML_HINT.test(source));
  }

  function looksLikeMarkdown(source) {
    if (!source) return false;
    for (var i = 0; i < MD_STRONG.length; i++) {
      if (MD_STRONG[i].test(source)) return true;
    }
    var weak = 0;
    for (var j = 0; j < MD_WEAK.length; j++) {
      if (MD_WEAK[j].test(source)) weak++;
    }
    return weak >= 2;
  }

  // What a stored body actually is. The declared content type wins; a message
  // filed before the server recorded one is sniffed instead.
  function detect(body, contentType, bodyHtml) {
    var declared = (contentType || '').toLowerCase();
    if (bodyHtml) return 'html';
    if (declared.indexOf('html') >= 0) return 'html';
    if (declared.indexOf('markdown') >= 0) return 'markdown';
    if (declared.indexOf('text/plain') === 0) return looksLikeHtml(body) ? 'html' : 'plain';
    if (looksLikeHtml(body)) return 'html';
    if (looksLikeMarkdown(body)) return 'markdown';
    return 'plain';
  }

  // ---------------------------------------------------------------- Markdown
  function stripEmphasis(text) {
    return text
      .replace(/\*\*\*([\s\S]+?)\*\*\*/g, '$1')
      .replace(/\*\*([\s\S]+?)\*\*/g, '$1')
      .replace(/(^|\W)__([\s\S]+?)__(\W|$)/g, '$1$2$3')
      .replace(/(^|[^*])\*(?!\s)([^*]+?)(?<!\s)\*(?!\*)/g, '$1$2')
      .replace(/~~([\s\S]+?)~~/g, '$1');
  }

  function inlineMd(text) {
    var html = escapeHtml(text);
    html = html.replace(/!\[([^\]]*)\]\(\s*([^)\s]+)[^)]*\)/g, function (all, alt) {
      return '[' + (alt || 'image') + ']';
    });
    html = html.replace(/\[([^\]]*)\]\(\s*([^)\s]+)[^)]*\)/g, function (all, label, url) {
      return '<a href="' + escapeHtml(absoluteUrl(url)) + '">' + (label || escapeHtml(url)) + '</a>';
    });
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    html = stripEmphasis(html);
    return html;
  }

  // Markdown to simple, valid HTML - the alternative part sent beside the text.
  function mdToHtml(source) {
    var lines = String(source || '').replace(/\r\n?/g, '\n').split('\n');
    var out = [];
    var paragraph = [];
    var list = null;

    function flushParagraph() {
      if (!paragraph.length) return;
      out.push('<p>' + inlineMd(paragraph.join(' ').trim()) + '</p>');
      paragraph = [];
    }
    function closeList() {
      if (list) { out.push('</' + list + '>'); list = null; }
    }
    function openList(kind) {
      if (list !== kind) { closeList(); out.push('<' + kind + '>'); list = kind; }
    }

    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      var trimmed = line.trim();
      var fence = trimmed.slice(0, 3);

      if (fence === '```' || fence === '~~~') {
        flushParagraph(); closeList();
        var code = [];
        i++;
        while (i < lines.length && lines[i].trim().indexOf(fence) !== 0) {
          code.push(escapeHtml(lines[i]));
          i++;
        }
        out.push('<pre><code>' + code.join('\n') + '</code></pre>');
        continue;
      }
      if (!trimmed) { flushParagraph(); closeList(); continue; }

      var heading = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/.exec(line);
      if (heading) {
        flushParagraph(); closeList();
        var level = heading[1].length;
        out.push('<h' + level + '>' + inlineMd(heading[2]) + '</h' + level + '>');
        continue;
      }
      if (/^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/.test(line)) {
        flushParagraph(); closeList(); out.push('<hr>'); continue;
      }
      if (trimmed.charAt(0) === '>') {
        flushParagraph(); closeList();
        out.push('<blockquote><p>' + inlineMd(trimmed.replace(/^>+\s?/, '')) + '</p></blockquote>');
        continue;
      }
      var bullet = /^\s*[-*+]\s+(.*)$/.exec(line);
      if (bullet) {
        flushParagraph(); openList('ul');
        out.push('<li>' + inlineMd(bullet[1]) + '</li>');
        continue;
      }
      var numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
      if (numbered) {
        flushParagraph(); openList('ol');
        out.push('<li>' + inlineMd(numbered[1]) + '</li>');
        continue;
      }
      if (trimmed.charAt(0) === '|' && trimmed.slice(-1) === '|' && trimmed.length > 2) {
        var cells = trimmed.replace(/^\||\|$/g, '').split('|');
        var separator = cells.every(function (cell) {
          return !cell.trim() || /^:?-{2,}:?$/.test(cell.trim());
        });
        if (separator) continue;
        flushParagraph(); closeList();
        out.push('<table><tr>' + cells.map(function (cell) {
          return '<td>' + inlineMd(cell.trim()) + '</td>';
        }).join('') + '</tr></table>');
        continue;
      }
      paragraph.push(line);
    }
    flushParagraph();
    closeList();
    return '<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>' +
           out.join('') + '</body></html>';
  }

  function textToHtml(source) {
    return '<!DOCTYPE html><html><head><meta charset="utf-8"></head><body><p>' +
           escapeHtml(source).replace(/\n/g, '<br>') + '</p></body></html>';
  }

  // ------------------------------------------------------------------- HTML
  // DOMParser builds an inert document: nothing is fetched, nothing runs. It is
  // only ever used to read text and links out of a message.
  function parseInert(html) {
    try {
      return new DOMParser().parseFromString(String(html || ''), 'text/html');
    } catch (e) {
      return null;
    }
  }

  function htmlToText(html) {
    var doc = parseInert(html);
    if (!doc) return String(html || '').replace(/<[^>]*>/g, ' ');
    var body = doc.body;
    if (!body) return '';
    Array.prototype.forEach.call(body.querySelectorAll('script,style,head'), function (node) {
      node.parentNode.removeChild(node);
    });
    Array.prototype.forEach.call(body.querySelectorAll('br'), function (node) {
      node.parentNode.replaceChild(doc.createTextNode('\n'), node);
    });
    Array.prototype.forEach.call(
      body.querySelectorAll('p,div,li,tr,h1,h2,h3,h4,h5,h6,blockquote,pre'),
      function (node) { node.appendChild(doc.createTextNode('\n')); });
    return (body.textContent || '').replace(/[ \t]+/g, ' ')
      .replace(/ *\n */g, '\n').replace(/\n{3,}/g, '\n\n').trim();
  }

  // Every address in a message, for the list shown beside it: a link the reader
  // can follow deliberately, instead of one the message follows for them.
  function extractLinks(body, bodyHtml, format) {
    var found = [];
    var seen = {};
    function add(label, url) {
      url = absoluteUrl(url);
      if (!url || seen[url] || /^javascript:/i.test(url)) return;
      seen[url] = true;
      found.push({ label: (label || url).trim() || url, url: url });
    }
    if (format === 'html') {
      var doc = parseInert(bodyHtml || body);
      if (doc) {
        Array.prototype.forEach.call(doc.querySelectorAll('a[href]'), function (anchor) {
          add(anchor.textContent, anchor.getAttribute('href'));
        });
      }
      return found;
    }
    var text = String(body || '');
    text.replace(/\[([^\]]*)\]\(\s*([^)\s]+)[^)]*\)/g, function (all, label, url) {
      add(label, url); return all;
    });
    var match;
    BARE_URL.lastIndex = 0;
    while ((match = BARE_URL.exec(text)) !== null) {
      add(match[0], match[0].replace(/[.,;:!?]+$/, ''));
    }
    return found;
  }

  // The message's own HTML with the fetch policy put in front of it. This is
  // what goes into the sandboxed frame - never the raw body.
  function sealDocument(html, title) {
    var head = '<head><meta charset="utf-8"><title>' + escapeHtml(title || '') + '</title>' +
               CSP_TAGS + BASE_STYLE + '</head>';
    var lowered = String(html || '').toLowerCase();
    var start, end;
    if (lowered.indexOf('<head') >= 0) {
      start = lowered.indexOf('<head');
      end = html.indexOf('>', start) + 1;
      return html.slice(0, end) + CSP_TAGS + BASE_STYLE + html.slice(end);
    }
    if (lowered.indexOf('<html') >= 0) {
      start = lowered.indexOf('<html');
      end = html.indexOf('>', start) + 1;
      return html.slice(0, end) + head + html.slice(end);
    }
    return '<!DOCTYPE html><html>' + head + '<body>' + html + '</body></html>';
  }

  // What the composer sends: always a readable plain body, plus the formatted
  // alternative beside it.
  function buildOutgoing(body, format) {
    if (format === 'html') {
      return { body: htmlToText(body), body_html: body, content_type: 'text/html' };
    }
    if (format === 'markdown') {
      return { body: body, body_html: mdToHtml(body), content_type: 'text/markdown' };
    }
    return { body: body, body_html: '', content_type: 'text/plain' };
  }

  window.Titan = window.Titan || {};
  window.Titan.MailFormat = {
    detect: detect,
    absoluteUrl: absoluteUrl,
    escapeHtml: escapeHtml,
    mdToHtml: mdToHtml,
    textToHtml: textToHtml,
    htmlToText: htmlToText,
    extractLinks: extractLinks,
    sealDocument: sealDocument,
    buildOutgoing: buildOutgoing
  };
})();
