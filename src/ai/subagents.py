# -*- coding: utf-8 -*-
"""
Subagents: an AI run that hands part of its work to another AI run.

The agent, both assistants and AI OCR's tools all go through one loop
(`ai_agent.run_agent`). A request with several independent parts - "check
the weather, find the cheapest train and read me what the installer on the
screen says" - used to be one long run holding every tool and every result
in one history. A subagent is the same loop started for one part only: its
own short history, its own instructions, a narrower toolset, a step budget,
and nothing to say to the user except the result it hands back.

* **One at a time or side by side.** ``ai_run_subagent`` runs one and waits;
  ``ai_run_subagents`` runs up to :data:`MAX_PARALLEL` at once on threads of
  their own and hands back every result together.
* **They are the parent's.** A subagent uses the provider and model of the run
  that started it, asks through the SAME confirmation (so the user's policy
  and "allow for this session" apply), is cancelled by the same Shift+Escape,
  and its actions are narrated through the parent's transcript.
* **They can be added.** Beside the built-in kinds (:data:`BUILTIN`) the user -
  or the AI on the user's behalf - can define their own: a name, what it is
  for, its instructions and which groups of tools it gets
  (``%APPDATA%/titosoft/Titan/ai/subagents.json``; Settings -> AI features ->
  Subagents..., or ``ai_create_subagent``).
* **No recursion without end.** A subagent may start subagents of its own
  down to :data:`MAX_DEPTH`; past that it is not given the tools at all.
* **Reachable from everywhere**: they are tools of the agent and the
  assistants, and the ``subagents`` provider of the Action API, so a macro, a
  Titan Script or a screen reader's add-on can start one too.
"""

import io
import json
import os
import re
import threading
import time

try:
    from src.titan_core.translation import set_language
    from src.settings.settings import get_setting
    _ = set_language(get_setting('language', 'pl'))
except Exception:                                    # noqa: BLE001
    def _(text):
        return text


MAX_DEPTH = 3           # the agent (1) -> a subagent (2) -> one more (3)
MAX_PARALLEL = 4        # side by side at once
MAX_TASKS = 8           # in one ai_run_subagents call
DEFAULT_STEPS = 15
MAX_STEPS = 40

#: The groups of tools a subagent can be given, and what each is.
GROUPS = {
    'desktop': "the windows, keyboard, mouse, files and programs",
    'ui': "the controls of any window by name (Windows' accessibility)",
    'ocr': "AI OCR: reading and pressing a window that has no accessibility",
    'browser': "a real web browser: pages, forms, buttons",
    'web': "web search, the weather and definitions",
    'titan': "Titan itself: its settings, components, add-ons, media",
    'services': "Titan's services: Titan-Net, Elten, Titan IM, the "
                "computer's settings, AI OCR",
    'actions': "every function the installed add-ons declare",
    'memory': "what the AI remembers between conversations",
    'all': "everything above",
}

#: Kinds that exist without anybody defining them. A user's own of the same
#: name wins.
BUILTIN = {
    'general': {
        'description': "A helper with every tool Titan has.",
        'instructions': "Do the task you are given completely, with whatever "
                        "tools it needs.",
        'tools': ['all'],
    },
    'screen': {
        'description': "Reads and operates what is on the screen, including "
                       "windows that expose nothing (games, installers) "
                       "through AI OCR.",
        'instructions': "Find out what is on the screen and do what the task "
                        "asks there. Try the window's accessibility first; "
                        "when it answers nothing, read it with AI OCR.",
        'tools': ['desktop', 'ui', 'ocr'],
    },
    'web': {
        'description': "Looks things up on the web and in web pages.",
        'instructions': "Find the information the task asks for on the web. "
                        "Report what you found and where, briefly.",
        'tools': ['web', 'browser'],
    },
    'titan': {
        'description': "Works inside Titan: its settings, add-ons and "
                       "services.",
        'instructions': "Do the task inside Titan, preferring Titan's own "
                        "tools and the add-ons' functions over the screen.",
        'tools': ['titan', 'services', 'actions'],
    },
}

def shown_description(name, entry):
    """What a subagent is for, in the user's language. The model is given
    the English of a built-in one; the person reading the list is not."""
    if entry.get('builtin'):
        words = {
            'general': _("A helper with every tool Titan has."),
            'screen': _("Reads and operates what is on the screen, including "
                        "windows that expose nothing (games, installers) "
                        "through AI OCR."),
            'web': _("Looks things up on the web and in web pages."),
            'titan': _("Works inside Titan: its settings, add-ons and "
                       "services."),
        }
        if name in words:
            return words[name]
    return entry.get('description') or ''


_SUBAGENT_FRAME = (
    "You are a SUBAGENT of Titan's AI: another run of the AI started you for "
    "one task and is waiting for your result. You cannot talk to the user "
    "and must not ask them anything - do the task with your tools, and when "
    "it is done reply with the result only, briefly and completely, in the "
    "language the task is written in. If the task cannot be done, say why "
    "in one sentence. Your role: {name} - {description}. {instructions}")

_lock = threading.Lock()


# --------------------------------------------------------------------------- #
# The user's own
# --------------------------------------------------------------------------- #
def store_path():
    base = os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~'),
                        'titosoft', 'Titan', 'ai')
    return os.path.join(base, 'subagents.json')


def _read_store():
    try:
        with io.open(store_path(), encoding='utf-8') as handle:
            data = json.load(handle)
    except Exception:                                # noqa: BLE001
        return {}
    if not isinstance(data, dict):
        return {}
    found = data.get('subagents', data)
    return {str(k): v for k, v in found.items() if isinstance(v, dict)}


def _write_store(entries):
    path = store_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + '.tmp'
    with io.open(temporary, 'w', encoding='utf-8') as handle:
        json.dump({'subagents': entries}, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def slug(name):
    """A name as it is stored and matched: lower case, words joined by _."""
    text = re.sub(r'[^\w]+', '_', str(name or '').strip().lower(),
                  flags=re.UNICODE).strip('_')
    return text[:40]


def clean_groups(tools):
    """Groups out of a list or a comma-separated string; unknown ones are
    dropped, nothing at all means 'all'."""
    if isinstance(tools, str):
        tools = [part for part in re.split(r'[,\s;]+', tools) if part]
    wanted = []
    for group in tools or ():
        group = str(group).strip().lower()
        if group in GROUPS and group not in wanted:
            wanted.append(group)
    return wanted or ['all']


def definitions():
    """Every kind there is, built in and the user's own, by slug."""
    found = {name: dict(entry, builtin=True) for name, entry in BUILTIN.items()}
    for name, entry in _read_store().items():
        key = slug(name)
        if not key:
            continue
        found[key] = {
            'description': str(entry.get('description') or '').strip(),
            'instructions': str(entry.get('instructions') or '').strip(),
            'tools': clean_groups(entry.get('tools')),
            'max_steps': entry.get('max_steps'),
            'builtin': False,
        }
    return found


def find(name):
    return definitions().get(slug(name) or 'general')


def save(name, description='', instructions='', tools=None, max_steps=None):
    """Add or change a subagent of the user's own. Returns its slug."""
    key = slug(name)
    if not key:
        raise ValueError("A subagent needs a name.")
    entry = {
        'description': str(description or '').strip(),
        'instructions': str(instructions or '').strip(),
        'tools': clean_groups(tools),
    }
    steps = _steps(max_steps, None)
    if steps:
        entry['max_steps'] = steps
    with _lock:
        entries = _read_store()
        entries = {slug(k): v for k, v in entries.items()}
        entries[key] = entry
        _write_store(entries)
    return key


def remove(name):
    """Take a subagent of the user's own away. A built-in one cannot be."""
    key = slug(name)
    with _lock:
        entries = {slug(k): v for k, v in _read_store().items()}
        if key not in entries:
            return False
        del entries[key]
        _write_store(entries)
    return True


def _steps(value, default):
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    if number <= 0:
        return default
    return min(number, MAX_STEPS)


# --------------------------------------------------------------------------- #
# Tools for a subagent
# --------------------------------------------------------------------------- #
def _group_tools(group):
    from src.ai import agent_tools
    if group == 'desktop':
        return agent_tools.get_desktop_tools()
    if group == 'ui':
        return agent_tools._ui_tools()
    if group == 'browser':
        return agent_tools._browser_tools()
    if group == 'titan':
        return agent_tools._titan_tools()
    if group == 'services':
        return agent_tools._subsystem_tools()
    if group == 'actions':
        return agent_tools._action_tools()
    if group == 'memory':
        return agent_tools._memory_tools()
    if group == 'ocr':
        try:
            from src.ai.tools.ocr_tools import get_ocr_tools
            return get_ocr_tools()
        except Exception as e:                       # noqa: BLE001
            print(f"[subagents] AI OCR tools unavailable: {e}")
            return []
    if group == 'web':
        try:
            from src.ai.assistant.assistant_tools import \
                get_assistant_only_tools
            return [tool for tool in get_assistant_only_tools()
                    if tool['name'] in ('web_search', 'get_weather',
                                        'get_definition')]
        except Exception as e:                       # noqa: BLE001
            print(f"[subagents] Web lookup tools unavailable: {e}")
            return []
    if group == 'all':
        tools = agent_tools.get_tools()
        return tools + _group_tools('web')
    return []


def tools_for(groups, depth):
    """The toolset of a subagent that will run at ``depth``. Deduplicated by
    name; a subagent at the deepest level is not given the subagent tools."""
    seen = set()
    tools = []
    for group in clean_groups(groups):
        for tool in _group_tools(group):
            name = tool.get('name')
            if not name or name in seen:
                continue
            if name in SUBAGENT_TOOL_NAMES and depth >= MAX_DEPTH:
                continue
            seen.add(name)
            tools.append(tool)
    if depth < MAX_DEPTH:
        for tool in get_subagent_tools():
            if tool['name'] not in seen:
                seen.add(tool['name'])
                tools.append(tool)
    return tools


# --------------------------------------------------------------------------- #
# Running one
# --------------------------------------------------------------------------- #
def _parent_context():
    from src.ai import ai_agent
    return ai_agent.current_run()


def _fallback_context():
    """A subagent started by a macro, a script or an add-on: nobody's run.
    The confirmation is the ordinary dialog under the user's policy."""
    from src.ai import confirmation
    try:
        from src.ai import ai_provider
        confirm_all = ai_provider.get_agent_confirm() == 'all'
    except Exception:                                # noqa: BLE001
        confirm_all = False
    return {'provider': None, 'model': None,
            'confirm': confirmation.make_confirm(who='subagent'),
            'confirm_all': confirm_all, 'cancel_event': None,
            'on_tool_start': None, 'on_tool_result': None, 'depth': 0}


def run(task, name='general', context='', parent=None):
    """Run one subagent to the end and return its answer as text. Raises
    ``AgentCancelled`` when the parent run is cancelled."""
    from src.ai import ai_agent
    task = str(task or '').strip()
    if not task:
        return "A subagent needs a task."
    definition = find(name)
    if definition is None:
        known = ", ".join(sorted(definitions()))
        return f"There is no subagent called '{name}'. Known: {known}."
    parent = parent or _parent_context() or _fallback_context()
    depth = int(parent.get('depth') or 0) + 1
    if depth > MAX_DEPTH:
        return ("Subagents cannot be nested deeper than this; do the task "
                "yourself.")
    label = slug(name) or 'general'
    system = _SUBAGENT_FRAME.format(
        name=label, description=definition.get('description') or label,
        instructions=definition.get('instructions') or '')
    try:
        system = system + "\n\n" + ai_agent.default_system()
    except Exception:                                # noqa: BLE001
        pass
    goal = task if not context else f"{task}\n\nContext:\n{context}"
    tools = tools_for(definition.get('tools'), depth)
    steps = _steps(definition.get('max_steps'), DEFAULT_STEPS)
    answer = ai_agent.run_agent(
        goal, tools, provider=parent.get('provider'), model=parent.get('model'),
        system=system, confirm=parent.get('confirm'),
        confirm_all=bool(parent.get('confirm_all')),
        cancel_event=parent.get('cancel_event'),
        on_tool_start=parent.get('on_tool_start'),
        on_tool_result=parent.get('on_tool_result'),
        max_steps=steps, remember=False)
    return (answer or '').strip() or "The subagent finished without an answer."


def run_many(tasks, parent=None):
    """Several subagents side by side; a list of (label, answer) in the order
    the tasks were given. A cancelled parent cancels them all."""
    from src.ai import ai_agent
    parent = parent or _parent_context() or _fallback_context()
    results = [None] * len(tasks)
    gate = threading.Semaphore(MAX_PARALLEL)
    cancelled = threading.Event()

    def work(index, entry):
        with gate:
            if cancelled.is_set():
                results[index] = "Not started: the run was cancelled."
                return
            # Each thread is its own: the parent's context has to be carried
            # there for confirmations, cancelling and nesting to work.
            ai_agent.push_run(parent)
            try:
                results[index] = run(entry.get('task'),
                                     entry.get('subagent') or 'general',
                                     entry.get('context') or '', parent=parent)
            except ai_agent.AgentCancelled:
                cancelled.set()
                results[index] = "Cancelled."
            except Exception as e:                   # noqa: BLE001
                results[index] = f"The subagent failed: {e}"
            finally:
                ai_agent.pop_run()

    threads = [threading.Thread(target=work, args=(i, entry), daemon=True,
                                name=f"TitanSubagent{i + 1}")
               for i, entry in enumerate(tasks)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    event = parent.get('cancel_event')
    if cancelled.is_set() or (event is not None and event.is_set()):
        raise ai_agent.AgentCancelled()
    return [(entry.get('subagent') or 'general', results[i])
            for i, entry in enumerate(tasks)]


# --------------------------------------------------------------------------- #
# In the background: the answer now, the result later
# --------------------------------------------------------------------------- #
# ai_run_subagent(s) WAIT - the reply is held until every subagent is done,
# which for a long task means the user listening to silence. A background
# subagent is started and left by the run that started it: that run answers
# at once, and when the subagent finishes the result is delivered on its own -
# a Titan notification (sound and speech) and a line in the AI buffer -
# whether or not any AI window is still open.
MAX_BACKGROUND = 4

_jobs = {}
_jobs_lock = threading.Lock()
_next_job = [0]


def _deliver(job):
    """Tell the user a background subagent has finished."""
    if job['state'] == 'failed':
        title = _("Subagent {name} failed").format(name=job['name'])
    else:
        title = _("Subagent {name} finished").format(name=job['name'])
    message = job.get('result') or ''
    try:
        from src.buffers import ai_buffer
        ai_buffer.push_assistant(message, author=title)
    except Exception as e:                           # noqa: BLE001
        print(f"[subagents] could not add the result to the AI buffer: {e}")
    try:
        import wx
        from src.ui.notificationcenter import show_notification
        if wx.GetApp() is not None:
            wx.CallAfter(show_notification, title, message)
        else:
            show_notification(title, message)
    except Exception as e:                           # noqa: BLE001
        print(f"[subagents] could not announce the result: {e}")


def start_background(task, name='general', context=''):
    """Start a subagent nobody waits for. Returns its job number, or raises
    ValueError saying why it was not started."""
    from src.ai import ai_agent, confirmation
    task = str(task or '').strip()
    if not task:
        raise ValueError("A subagent needs a task.")
    if find(name) is None:
        known = ", ".join(sorted(definitions()))
        raise ValueError(f"There is no subagent called '{name}'. Known: {known}.")
    with _jobs_lock:
        running = sum(1 for job in _jobs.values() if job['state'] == 'running')
        if running >= MAX_BACKGROUND:
            raise ValueError(f"{running} background subagents are already "
                             f"running; wait for one to finish.")
        _next_job[0] += 1
        number = _next_job[0]
    parent = _parent_context() or {}
    cancel = threading.Event()
    job = {'id': number, 'name': slug(name) or 'general', 'task': task,
           'state': 'running', 'result': '', 'cancel': cancel,
           'started': time.time(), 'finished': None}
    # A context of its own: the run that started it will be over long before
    # it is, so nothing of that run - its window, its cancel event - is used.
    own = {'provider': parent.get('provider'), 'model': parent.get('model'),
           'confirm': confirmation.make_confirm(cancel_event=cancel,
                                                who='subagent'),
           'confirm_all': bool(parent.get('confirm_all')),
           'cancel_event': cancel, 'on_tool_start': None,
           'on_tool_result': None, 'depth': int(parent.get('depth') or 0)}
    with _jobs_lock:
        _jobs[number] = job

    def work():
        ai_agent.push_run(own)
        try:
            job['result'] = run(task, name, context, parent=own)
            job['state'] = 'done'
        except ai_agent.AgentCancelled:
            job['state'] = 'cancelled'
            job['result'] = "Cancelled."
        except Exception as e:                       # noqa: BLE001
            job['state'] = 'failed'
            job['result'] = f"The subagent failed: {e}"
        finally:
            ai_agent.pop_run()
            job['finished'] = time.time()
        if job['state'] != 'cancelled':
            _deliver(job)

    threading.Thread(target=work, daemon=True,
                     name=f"TitanBackgroundSubagent{number}").start()
    return number


def jobs():
    with _jobs_lock:
        return [dict(job) for _n, job in sorted(_jobs.items())]


def cancel_job(number):
    with _jobs_lock:
        job = _jobs.get(number)
    if job is None or job['state'] != 'running':
        return False
    job['cancel'].set()
    return True


def _job_number(value):
    try:
        return int(str(value).strip().lstrip('#'))
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# The tools
# --------------------------------------------------------------------------- #
def ai_run_subagent(task, subagent='general', context='', **_):
    """Hand one task to a subagent and wait for its result."""
    if not _ai_on():
        return "AI features are switched off."
    return f"Subagent '{slug(subagent) or 'general'}': " + run(
        task, subagent or 'general', context)


def _parse_tasks(tasks):
    if isinstance(tasks, str):
        try:
            tasks = json.loads(tasks)
        except Exception as e:                       # noqa: BLE001
            return None, (f"'tasks' is not valid JSON: {e}. It should be a "
                          f'list like [{{"task": "...", "subagent": "web"}}]')
    if not isinstance(tasks, list) or not tasks:
        return None, ("'tasks' must be a non-empty list of "
                      '{"task": ..., "subagent": ...} objects.')
    clean = []
    for entry in tasks:
        if isinstance(entry, str):
            entry = {'task': entry}
        if not isinstance(entry, dict) or not str(entry.get('task') or '').strip():
            return None, "Every entry in 'tasks' needs a 'task'."
        clean.append(entry)
    if len(clean) > MAX_TASKS:
        return None, f"At most {MAX_TASKS} subagents in one call."
    return clean, ''


def ai_run_subagents(tasks, **_):
    """Several independent tasks at once, each to a subagent of its own."""
    if not _ai_on():
        return "AI features are switched off."
    clean, error = _parse_tasks(tasks)
    if error:
        return error
    results = run_many(clean)
    lines = []
    for number, (label, answer) in enumerate(results, 1):
        lines.append(f"{number}. ({label}) {answer}")
    return "\n".join(lines)


def ai_start_subagent(task, subagent='general', context='', **_):
    """Start a subagent in the background and answer at once."""
    if not _ai_on():
        return "AI features are switched off."
    try:
        number = start_background(task, subagent or 'general', context)
    except ValueError as e:
        return str(e)
    return (f"Started background subagent #{number} "
            f"({slug(subagent) or 'general'}). It works on its own and the "
            f"user is told the result when it finishes, so do not wait for "
            f"it - tell the user it is running and carry on.")


def ai_subagent_status(job='', **_):
    """What the background subagents are doing, or one of them."""
    number = _job_number(job) if job not in (None, '') else None
    found = [j for j in jobs() if number is None or j['id'] == number]
    if not found:
        return ("There is no such background subagent." if number is not None
                else "No background subagents have been started.")
    lines = []
    for entry in found:
        line = f"#{entry['id']} {entry['name']} - {entry['state']}: {entry['task']}"
        if entry['state'] != 'running' and entry['result']:
            line += f"\n   Result: {entry['result']}"
        lines.append(line)
    return "\n".join(lines)


def ai_cancel_subagent(job, **_):
    number = _job_number(job)
    if number is None:
        return "Say which background subagent, by its number."
    if cancel_job(number):
        return f"Background subagent #{number} is being stopped."
    return f"Background subagent #{number} is not running."


def ai_list_subagents(**_):
    lines = []
    for name, entry in sorted(definitions().items()):
        kind = "built in" if entry.get('builtin') else "the user's own"
        lines.append(f"- {name} ({kind}; tools: {', '.join(entry['tools'])}): "
                     f"{entry.get('description') or ''}")
    groups = "; ".join(f"{k} = {v}" for k, v in GROUPS.items())
    return "Subagents:\n" + "\n".join(lines) + f"\nTool groups: {groups}"


def ai_create_subagent(name, instructions, description='', tools='',
                       max_steps='', **_):
    try:
        key = save(name, description, instructions, tools, max_steps)
    except ValueError as e:
        return str(e)
    except Exception as e:                           # noqa: BLE001
        return f"The subagent could not be saved: {e}"
    entry = definitions()[key]
    return (f"Saved the subagent '{key}' (tools: {', '.join(entry['tools'])}). "
            f"Start it with ai_run_subagent.")


def ai_delete_subagent(name, **_):
    if slug(name) in BUILTIN and slug(name) not in _store_slugs():
        return f"'{slug(name)}' is built in and cannot be deleted."
    if remove(name):
        return f"Deleted the subagent '{slug(name)}'."
    return f"There is no subagent of the user's own called '{name}'."


def _store_slugs():
    return {slug(k) for k in _read_store()}


def _ai_on():
    try:
        from src.ai import ai_provider
        return ai_provider.is_ai_enabled()
    except Exception:                                # noqa: BLE001
        return True


SUBAGENT_TOOL_NAMES = frozenset({'ai_run_subagent', 'ai_run_subagents',
                                 'ai_start_subagent', 'ai_subagent_status',
                                 'ai_cancel_subagent',
                                 'ai_list_subagents', 'ai_create_subagent',
                                 'ai_delete_subagent'})


def get_subagent_tools():
    from src.ai.agent_tools import _tool
    S = {'type': 'string'}
    N = {'type': 'number'}
    return [
        _tool('ai_run_subagent',
              "Hand one part of the work to a SUBAGENT - another AI run with "
              "its own short history, its own instructions and only the tools "
              "it needs - and wait for its result. Use it for a self-contained "
              "part of a bigger request (look something up, read a window, do "
              "one thing in Titan) so your own conversation stays short. "
              "ai_list_subagents says which kinds exist.",
              ai_run_subagent, needs_gui=False,
              properties={'task': dict(S, description="The whole task, with "
                                       "every detail the subagent needs - it "
                                       "sees nothing of your conversation."),
                          'subagent': dict(S, description="Which kind: "
                                           "general (default), screen, web, "
                                           "titan, or one the user defined."),
                          'context': dict(S, description="Optional: what you "
                                          "already know that it should use.")},
              required=['task']),
        _tool('ai_run_subagents',
              "Run several INDEPENDENT tasks at the same time, each in a "
              "subagent of its own, and get every result back together. "
              f"At most {MAX_TASKS}, {MAX_PARALLEL} at once.",
              ai_run_subagents, needs_gui=False,
              properties={'tasks': dict(S, description=
                          'A JSON list, e.g. [{"task": "What is the weather in '
                          'Krakow?", "subagent": "web"}, {"task": "Read the '
                          'installer window", "subagent": "screen"}]')},
              required=['tasks']),
        _tool('ai_start_subagent',
              "Start a subagent IN THE BACKGROUND and answer at once instead "
              "of waiting: for anything that takes a while (research, a long "
              "check) when the user does not need the result in this reply. "
              "Titan tells the user the result by itself when it is done. "
              "Tell the user it is running; do not wait or poll for it.",
              ai_start_subagent, needs_gui=False,
              properties={'task': dict(S, description="The whole task, with "
                                       "every detail - it sees nothing of "
                                       "your conversation."),
                          'subagent': dict(S, description="Which kind "
                                           "(default general)."),
                          'context': dict(S, description="Optional: what you "
                                          "already know.")},
              required=['task']),
        _tool('ai_subagent_status',
              "What the background subagents are doing, and the result of a "
              "finished one. Use it when the user asks about one.",
              ai_subagent_status, needs_gui=False,
              properties={'job': dict(S, description="Optional: its number.")}),
        _tool('ai_cancel_subagent', "Stop a background subagent.",
              ai_cancel_subagent, needs_gui=False,
              properties={'job': dict(S, description="Its number.")},
              required=['job']),
        _tool('ai_list_subagents',
              "The kinds of subagent there are (built in and the user's own) "
              "and the tool groups one can be given.",
              ai_list_subagents, needs_gui=False),
        _tool('ai_create_subagent',
              "Add (or change) a subagent of the user's own: a name, what it "
              "is for, its instructions and which tool groups it gets. Do it "
              "when the user asks for a helper they will use again.",
              ai_create_subagent, needs_gui=False,
              properties={'name': dict(S, description="Short name."),
                          'instructions': dict(S, description="How it should "
                                               "work."),
                          'description': dict(S, description="One sentence: "
                                              "what it is for."),
                          'tools': dict(S, description="Tool groups, comma "
                                        "separated: " + ", ".join(GROUPS)),
                          'max_steps': dict(N, description=f"Step budget "
                                            f"(default {DEFAULT_STEPS}, at "
                                            f"most {MAX_STEPS}).")},
              required=['name', 'instructions']),
        _tool('ai_delete_subagent', "Delete a subagent of the user's own.",
              ai_delete_subagent, risk='confirm', needs_gui=False,
              properties={'name': dict(S, description="Its name.")},
              required=['name']),
    ]
