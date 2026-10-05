# -*- coding: utf-8 -*-
"""NVDA's `speechXml`: a speech sequence turned into well-formed XML
(SSML and the like). Written for Titan Access.

A converter turns each item of the sequence into a BALANCER command - set
an attribute on a tag, take it off, put a self-closing tag here, enclose
the whole thing - and the balancer keeps the tags properly nested: when an
attribute changes, the tags that carry it are closed and opened again, so
synthesizers that subclass the converter (RHVoice does) get valid XML."""

from xml.sax.saxutils import escape, quoteattr

from .speech import commands as _c


def toXmlLang(nvdaLang):
    return str(nvdaLang or '').replace('_', '-')


class _Command(object):
    pass


class SetAttrCommand(_Command):
    def __init__(self, tag, attr, val):
        self.tag, self.attr, self.val = tag, attr, val


class DelAttrCommand(_Command):
    def __init__(self, tag, attr):
        self.tag, self.attr = tag, attr


class EncloseAllCommand(_Command):
    def __init__(self, tag, attrs):
        self.tag, self.attrs = tag, dict(attrs or {})


class EncloseTextCommand(_Command):
    def __init__(self, tag, attrs, text):
        self.tag, self.attrs, self.text = tag, dict(attrs or {}), text


class StandAloneTagCommand(_Command):
    def __init__(self, tag, attrs, content):
        self.tag, self.attrs, self.content = tag, dict(attrs or {}), content


def _attrs(attrs):
    return ''.join(' %s=%s' % (name, quoteattr(str(value)))
                   for name, value in attrs.items())


class XmlBalancer(object):
    """Keeps tags balanced while attributes come and go."""

    def __init__(self):
        self._wanted = {}             # tag -> {attr: value}, in first-set order
        self._open = []               # [(tag, attrs)] currently open, outer first
        self._outer = []              # EncloseAll tags, outermost first

    def _sync(self, out):
        wanted = [(tag, dict(attrs)) for tag, attrs in self._wanted.items()
                  if attrs]
        keep = 0
        while keep < len(self._open) and keep < len(wanted) \
                and self._open[keep] == wanted[keep]:
            keep += 1
        for tag, _attrs_open in reversed(self._open[keep:]):
            out.append('</%s>' % tag)
        self._open = self._open[:keep]
        for tag, attrs in wanted[keep:]:
            out.append('<%s%s>' % (tag, _attrs(attrs)))
            self._open.append((tag, attrs))

    def generateXml(self, commands):
        out = []
        started = False
        for command in commands:
            if isinstance(command, EncloseAllCommand):
                out.append('<%s%s>' % (command.tag, _attrs(command.attrs)))
                self._outer.append(command.tag)
                continue
            if isinstance(command, SetAttrCommand):
                self._wanted.setdefault(command.tag, {})[command.attr] = \
                    command.val
                continue
            if isinstance(command, DelAttrCommand):
                self._wanted.get(command.tag, {}).pop(command.attr, None)
                continue
            self._sync(out)
            started = True
            if isinstance(command, str):
                out.append(escape(command))
            elif isinstance(command, EncloseTextCommand):
                out.append('<%s%s>%s</%s>' % (command.tag,
                                              _attrs(command.attrs),
                                              escape(str(command.text or '')),
                                              command.tag))
            elif isinstance(command, StandAloneTagCommand):
                if command.content is None:
                    out.append('<%s%s/>' % (command.tag,
                                            _attrs(command.attrs)))
                else:
                    out.append('<%s%s>%s</%s>' % (
                        command.tag, _attrs(command.attrs),
                        escape(str(command.content)), command.tag))
        for tag, _a in reversed(self._open):
            out.append('</%s>' % tag)
        self._open = []
        for tag in reversed(self._outer):
            out.append('</%s>' % tag)
        self._outer = []
        del started
        return ''.join(out)


class SpeechXmlConverter(object):
    """A sequence -> balancer commands, one ``convert<Name>`` per command
    class; a command with no converter is left out."""

    def generateBalancerCommands(self, speechSequence):
        for item in speechSequence or ():
            if isinstance(item, str):
                yield item
                continue
            method = getattr(self, 'convert%s' % type(item).__name__, None)
            if method is None:
                for base in type(item).__mro__[1:]:
                    method = getattr(self, 'convert%s' % base.__name__, None)
                    if method is not None:
                        break
            if method is None:
                continue
            found = method(item)
            if found is None:
                continue
            if isinstance(found, (list, tuple)):
                for one in found:
                    yield one
            else:
                yield found

    def convertToXml(self, speechSequence):
        return XmlBalancer().generateXml(
            self.generateBalancerCommands(speechSequence))


class SsmlConverter(SpeechXmlConverter):

    def __init__(self, defaultLanguage):
        self.defaultLanguage = toXmlLang(defaultLanguage)

    def generateBalancerCommands(self, speechSequence):
        yield EncloseAllCommand('speak', {
            'version': '1.0',
            'xmlns': 'http://www.w3.org/2001/10/synthesis',
            'xml:lang': self.defaultLanguage})
        for command in super().generateBalancerCommands(speechSequence):
            yield command

    def convertIndexCommand(self, command):
        return StandAloneTagCommand('mark', {'name': command.index}, None)

    def convertCharacterModeCommand(self, command):
        if command.state:
            return SetAttrCommand('say-as', 'interpret-as', 'characters')
        return DelAttrCommand('say-as', 'interpret-as')

    def convertLangChangeCommand(self, command):
        if command.lang:
            return SetAttrCommand('voice', 'xml:lang',
                                  toXmlLang(command.lang))
        return DelAttrCommand('voice', 'xml:lang')

    def convertBreakCommand(self, command):
        return StandAloneTagCommand('break', {'time': '%dms' % command.time},
                                    None)

    def _convertProsody(self, command, attr):
        if command.multiplier == 1:
            return DelAttrCommand('prosody', attr)
        return SetAttrCommand('prosody', attr,
                              '%d%%' % int(command.multiplier * 100))

    def convertPitchCommand(self, command):
        return self._convertProsody(command, 'pitch')

    def convertRateCommand(self, command):
        return self._convertProsody(command, 'rate')

    def convertVolumeCommand(self, command):
        return self._convertProsody(command, 'volume')

    def convertPhonemeCommand(self, command):
        return EncloseTextCommand('phoneme', {'alphabet': 'ipa',
                                              'ph': command.ipa},
                                  command.text)


__all__ = ['toXmlLang', 'SetAttrCommand', 'DelAttrCommand',
           'EncloseAllCommand', 'EncloseTextCommand', 'StandAloneTagCommand',
           'XmlBalancer', 'SpeechXmlConverter', 'SsmlConverter']
_c = _c


from . import permissive as _permissive  # noqa: E402
_permissive(globals())
