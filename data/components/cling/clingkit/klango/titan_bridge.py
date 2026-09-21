# -*- coding: utf-8 -*-
"""Klango's own platform screens, answered by Titan's.

An emulated application's menu offers Settings and Help, and both of them were
Klango's: a language picker, a voice picker, an audio-theme picker, a knowledge
base, a terms-of-service page, a feedback form.  Run inside Cling they are the
wrong screens, and two of them are worse than wrong:

* **the voice picker changed nothing.**  A Cling application speaks through
  Titan's own TTS - that is the whole point of running it inside Titan - so
  Klango's list of SAPI voices was a screen that let the user choose and then
  went on speaking in the voice they already had.  The same is true of the
  language and the audio theme: Cling reads Titan's.
* **the rest of them talked to klango.net**, which has been gone for years.
  The knowledge base, the terms of service, the privacy policy and the
  feedback form all had a server behind them and now have none.

So the platform screens are Titan's.  `Settings` opens Titan's settings -
through whichever settings interface the user chose, like every other way in -
and `Help` opens Titan's help; feedback goes to the Feedback Hub, which is
where a Titan user's feedback goes.

What is deliberately NOT redirected is everything that belongs to the
APPLICATION rather than to the platform: its own help text (F1), its own
readme and changelog, its own version, its own exit.  Those are the
application talking about itself, and Titan has nothing to say about them.
"""

import threading

#: What the application is told after each of these, so somebody who cannot
#: see a window appear knows one did. Said through the host, which means it is
#: spoken in the user's own voice and written into the transcript.
SETTINGS_SAID = "Titan's settings are open."
HELP_SAID = "Titan's help is open."
FEEDBACK_SAID = 'The Titan Feedback Hub is open.'
NO_FEEDBACK_SAID = ('Feedback goes to Titan-Net, and nobody is signed in. '
                    'Open Titan-Net once and sign in, then try again.')


def _tr(text):
    """Cling's own catalogue, in Titan's language - these sentences are
    said to the user by a menu item, and they were the only English an
    emulated application spoke on a Polish desktop."""
    try:
        import gettext
        import os
        from src.titan_core.translation import language_code
        here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return gettext.translation('cling', os.path.join(here, 'languages'),
                                   languages=[language_code], fallback=True).gettext(text)
    except Exception:
        return text


def install(runtime, host):
    """Point Klango's platform screens at Titan's, on the running app object.

    `k_NewApp` is a global and every application calls it, so it is the one
    place where an application object can be reached before it is used. The
    methods are replaced on the object rather than on the class because there
    is no class: Klango copies its `suiapp` table for each instance.
    """
    give = runtime.set_global
    give('_cling_open_settings', lambda *_a: _say(host, open_settings()))
    give('_cling_open_help', lambda *_a: _say(host, open_help()))
    give('_cling_open_feedback', lambda *_a: _say(host, open_feedback()))
    # The application's own readme / changelog, in the user's language when
    # it has one - `k_KnowledgeBaseDialog2` shows it in Klango's own reader.
    give('_cling_app_text', lambda name=None, *_a: _app_text(host, name))
    give('_cling_titan_help_name', lambda *_a: _tr("Titan's help"))
    try:
        runtime.run(BRIDGE, 'cling: titan bridge')
    except Exception as error:
        print('[cling/klango] the Titan bridge could not be installed: %s'
              % error)
        return False
    return True


#: The two entries Cling puts in place of Klango's own submenus, named the
#: way `processDefaultMenuItems` names everything it handles.
SETTINGS_ITEM = '__!cling_settings!__'
HELP_ITEM = '__!cling_help!__'

#: Which of Klango's screens is which of Titan's. The names on the left are
#: `suiapp` methods, reached from the default menu and from the function keys
#: the application shell owns.
BRIDGE = """
    --- Every screen of Klango's that is Titan's here is patched on the
    --- CLASS, `suiapp`, and not on the object `k_NewApp` hands back.
    --- Klango copies the class table into each instance, so an instance
    --- made after this carries the patch - and an application that reaches
    --- the class's own methods directly (`suiapp.defaultMenus(self)`, which
    --- the Wikipedia browser does) sees it too, where a patch on the
    --- instance was simply walked past: its Settings entry still opened
    --- Klango's own sound-theme dialog. `k_NewApp` is kept as the fallback
    --- for an application object that is not a `suiapp` at all.
    local function patch( app )
        if app.__cling_patched then return app end
        app.__cling_patched = true
        local settings = { "_dialogSelectLang", "_dialogSelectSkin",
                           "_dialogSelectSynth", "_dialogTypingSettings",
                           "_dialogNameSuiElems", "_dialogSelectWaitingSound",
                           "_dialogSimpleSoundOpenClose", "_dialogKeyBindings",
                           "_dialogFormatsSettings", "_dialogAutoLogin" }
        for _, name in ipairs( settings ) do
            app[name] = function() return _cling_open_settings() end
        end
        local help = { "_dialogTermsOfService", "_dialogPrivacyPolicy" }
        for _, name in ipairs( help ) do
            app[name] = function() return _cling_open_help() end
        end
        local feedback = { "sendFeedback", "sendOpinions",
                           "sendErrorReport" }
        for _, name in ipairs( feedback ) do
            app[name] = function() return _cling_open_feedback() end
        end

        --- Settings and Help are ONE entry each, and they are
        --- Titan's.
        ---
        --- Redirecting the screens behind Klango's submenus was not
        --- enough: the user still walked into "Settings" and found
        --- four items - theme, language, synthesiser, interface -
        --- every one of which now did the same thing. What they
        --- asked for is Titan's settings, so that is what the entry
        --- is. The submenu is recognised by what is INSIDE it
        --- (`__!setskin!__`, `__!helpkeys!__`) rather than by its
        --- name, because the name is in the user's language.
        local function holds( item, wanted )
            if type(item) ~= "table" or type(item.submenu) ~= "table" then
                return false
            end
            for _, child in ipairs( item.submenu ) do
                if type(child) == "table" and type(child.user) == "table"
                        and child.user[1] == wanted then
                    return true
                end
            end
            return false
        end
        --- Help stays a submenu, made of what is really there: the
        --- application's own key help, its readme and changelog when
        --- it ships them, its version, and Titan's help. What goes is
        --- what pointed at klango.net - the knowledge base, the terms
        --- of service, the privacy policy, the feedback forms.
        local keep = { ["__!helpkeys!__"] = true, ["__!helpprogver!__"] = true }
        local function help_menu( submenu )
            local out = {}
            for _, child in ipairs( submenu ) do
                local marker = type(child) == "table" and type(child.user) == "table"
                               and child.user[1] or nil
                if keep[marker] then
                    table.insert( out, child )
                elseif marker == "__!helpreadme!__" and _cling_app_text( "readme" ) ~= "" then
                    table.insert( out, child )
                elseif marker == "__!helpchangelog!__" and _cling_app_text( "changelog" ) ~= "" then
                    table.insert( out, child )
                end
            end
            --- A menu item's name is a SPEECH SAMPLE spec, not a string:
            --- `"*text"` is Klango's "say this text" (Amazon writes its
            --- cart entries that way). A bare string is a sample the
            --- mediaset cannot prepare, and that is a FATAL error in
            --- `llib_suimenu.lua` - "Corrupted installation of Klango",
            --- and the engine killed, at the first menu of every
            --- application.
            table.insert( out, { name = "*" .. _cling_titan_help_name(), user = { "%(help)s" } } )
            return out
        end
        local _menus = app.defaultMenus
        app.defaultMenus = function( self, ... )
            local menu = _menus( self, ... )
            if type(menu) ~= "table" then return menu end
            for _, item in ipairs( menu ) do
                if holds( item, "__!setskin!__" ) then
                    item.submenu = nil
                    item.user = { "%(settings)s" }
                elseif holds( item, "__!helpkeys!__" ) then
                    item.submenu = help_menu( item.submenu )
                    item.user = nil
                end
            end
            return menu
        end
        local _process = app.processDefaultMenuItems
        app.processDefaultMenuItems = function( self, mi, ... )
            if type(mi) == "table" and type(mi.user) == "table" then
                if mi.user[1] == "%(settings)s" then
                    _cling_open_settings()
                    return true
                elseif mi.user[1] == "%(help)s" then
                    _cling_open_help()
                    return true
                end
            end
            return _process( self, mi, ... )
        end
        return app
    end
    --- `suiapp` is a file-local of `llib_suiapp.lua` and `k_SUINewApp` is
    --- `k_TableDuplicate( suiapp )`, so the class cannot be patched and the
    --- INSTANCE is. Every constructor an application calls is wrapped:
    --- `k_NewApp` (most of them) is the same function as `k_SUINewApp`
    --- (the Wikipedia browser calls that one directly), so both names get
    --- the wrapper - and `k_CreateNewApp` is a scaffolding tool that makes
    --- an application FOLDER, not an object, and is left alone.
    local _sui = k_SUINewApp
    local _new = k_NewApp
    local function wrap( make )
        return function( ... )
            local app = make( ... )
            if type(app) == "table" then patch( app ) end
            return app
        end
    end
    if type(_sui) == "function" then
        k_SUINewApp = wrap( _sui )
        if _new == _sui then k_NewApp = k_SUINewApp end
    end
    if type(_new) == "function" and _new ~= _sui then
        k_NewApp = wrap( _new )
    end
    -- The knowledge base is a global rather than a method, and it was a page
    -- on klango.net. Titan's own help is what a user of Titan wants here -
    -- EXCEPT for the application's own readme and changelog, which the
    -- library fetches through the same call (`suiapp:showReadme` is
    -- `k_KnowledgeBaseDialog2(self, id, lang, 'readme', nil, force)`), and
    -- calls at the application's FIRST start. Redirected wholesale, every
    -- Klango application opened Titan's help window the first time it was
    -- run. What Klango showed there was the application's own text in its
    -- own reader (`_dialogTextViever`), so that is what this shows; an
    -- application with no such text shows nothing, which is silence at
    -- start rather than a window nobody asked for.
    k_KnowledgeBaseDialog = function() return _cling_open_help() end
    k_KnowledgeBaseDialog2 = function( app, appid, lang, doc, summary, force )
        if doc == "readme" or doc == "changelog" then
            local text = _cling_app_text( doc )
            if type(text) == "string" and text ~= "" and type(app) == "table"
                    and type(app._dialogTextViever) == "function" then
                local title = doc
                if type(_mmenuspeech) == "table" and _mmenuspeech["help_" .. doc] ~= nil then
                    title = _mmenuspeech["help_" .. doc]
                end
                app:_dialogTextViever( text, title )
                return true
            end
            return false
        end
        return _cling_open_help()
    end
""" % {'settings': SETTINGS_ITEM, 'help': HELP_ITEM}


def _app_text(host, name):
    try:
        return host.text(str(name or '')) or ''
    except Exception:
        return ''


# ------------------------------------------------------------- the windows
def open_settings():
    """Titan's settings, through whichever interface the user chose."""
    def show():
        from src.settings.interfaces import open_settings as open_them
        return open_them()
    return _on_the_gui_thread(show, _tr(SETTINGS_SAID),
                              _tr("Titan's settings could not be opened"))


def open_help():
    def show():
        # `show_help()` TOGGLES, which is right for the key that opens it and
        # wrong for a menu item called Help - and it answers nothing either
        # way, so there would be no way to tell whether a window appeared.
        from src.ui.help import get_help_instance
        window = get_help_instance()
        if window is None:
            return None
        window.show_help()
        return window
    return _on_the_gui_thread(show, _tr(HELP_SAID),
                              _tr("Titan's help could not be opened"))


def open_feedback():
    """The Feedback Hub, which needs the Titan-Net account Cling already uses."""
    from .. import account as account_module

    client = account_module._live_client()
    if client is None:
        signed_in, _error = account_module.sign_in()
        if signed_in.online:
            client = account_module._live_client()
    if client is None:
        return _tr(NO_FEEDBACK_SAID)

    def show():
        import wx
        from src.network.feedback_hub import open_feedback_hub
        return open_feedback_hub(wx.GetApp().GetTopWindow() if wx.GetApp()
                                 else None, client)
    return _on_the_gui_thread(show, _tr(FEEDBACK_SAID),
                              _tr('The Feedback Hub could not be opened'))


# ------------------------------------------------------------------ pieces
def _say(host, sentence):
    """Tell the player what happened. A window that opens behind an
    application nobody can see is a window nobody knows about."""
    try:
        host.show(sentence)
    except Exception:
        pass
    return True


def _on_the_gui_thread(show, said, blamed):
    """Open a Titan window from the application's own thread.

    An emulated application runs on a thread of its own and every one of these
    is a wx window, so the call is marshalled; the answer is a sentence either
    way, because the caller is a menu item that has to say something.
    """
    try:
        import wx
    except Exception as error:
        return '%s: %s' % (blamed, error)

    outcome = {}
    done = threading.Event()

    def run():
        try:
            outcome['window'] = show()
        except Exception as error:
            outcome['error'] = error
        finally:
            done.set()

    try:
        if wx.IsMainThread():
            run()
        else:
            wx.CallAfter(run)
            # Long enough that a window which opens normally has, short
            # enough that an application never sits waiting on one.
            done.wait(5.0)
    except Exception as error:
        return '%s: %s' % (blamed, error)
    if outcome.get('error') is not None:
        return '%s: %s' % (blamed, outcome['error'])
    if not done.is_set():
        return '%s: it did not answer.' % blamed
    if not outcome.get('window'):
        # Titan's own openers report a failure by answering nothing and
        # printing to the console - which nobody using this can see. Saying
        # "the settings are open" when they are not is the one answer a
        # player must never get.
        return '%s.' % blamed
    return said
