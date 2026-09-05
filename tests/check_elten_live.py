"""What the Elten API port does not know, asked of the Elten that is running.

`data/components/elten_bridge/` is a PORT: Elten's API re-implemented on top
of Titan so an `.eltenapp` runs inside Titan. Every bug it has ever had was
made the same way - a name or a signature guessed from how an application
calls it, instead of read from Elten:

    `text=` where Elten has `set_text`
    `alert` modelled as a dialog when Elten's is speech
    `Tasks.run` yielding one value where Elten yields two
    `player` simply absent, so playing a YouTube video did nothing
    `ChoiceListBox#value` answering the option's TEXT where Elten answers
        its INDEX, so MileByMile could not start a game

The TCE bridge (`elten-tce-bridge/`) is inside the real Elten and can be
ASKED. This is that: every bare function an installed application calls is
put to the running Elten, and anything Elten has and the port has not is
printed with its real signature.

    python tests/check_elten_live.py

It needs Elten open with the TCE bridge in it, and the bridge given
permission to share (it asks once). Without either it says so and stops -
there is nothing here it can invent.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TITAN = os.path.dirname(HERE)
sys.path.insert(0, TITAN)

PORT = os.path.join(TITAN, 'data', 'components', 'elten_bridge', 'eapi')
ELTEN_APPS = os.path.join(os.environ.get('APPDATA', ''), 'elten', 'apps', 'src')

DEF = re.compile(r'^\s*def\s+(?:self\.)?([a-z_][a-zA-Z0-9_]*[?!]?)', re.M)
CALL = re.compile(r'(?<![.:@$\w])([a-z_][a-zA-Z0-9_]*[?!]?)\s*\(')

#: Ruby's own, and things every object answers to - not the platform's.
RUBY = {
    'if', 'unless', 'while', 'until', 'case', 'when', 'return', 'raise',
    'puts', 'print', 'p', 'require', 'require_relative', 'loop', 'new',
    'lambda', 'proc', 'yield', 'super', 'begin', 'end', 'rescue', 'ensure',
    'catch', 'throw', 'format', 'sprintf', 'rand', 'sleep', 'open', 'send',
    'define_method', 'block_given?', 'freeze', 'dup', 'to_s', 'to_i',
    'instance_variable_get', 'instance_variable_set', 'respond_to?',
}


def names_defined_in(folder):
    found = set()
    for root, _dirs, files in os.walk(folder):
        for name in files:
            if name.endswith('.rb'):
                text = open(os.path.join(root, name), encoding='utf-8',
                            errors='replace').read()
                found |= set(DEF.findall(text))
    return found


def names_the_applications_call():
    """Every bare call in every installed `.eltenapp` that the application
    does not define ITSELF, unpacked in memory.

    Subtracting an application's own methods is what makes this a list of
    the PLATFORM's names: a package defines a few hundred of its own, and
    asking Elten about `accept_reveal_part` says nothing about the port.
    """
    if not os.path.isdir(ELTEN_APPS):
        return None
    sys.path.insert(0, os.path.join(TITAN, 'data', 'components', 'elten_bridge'))
    from eltenkit import package
    called = set()
    for entry in sorted(os.listdir(ELTEN_APPS)):
        full = os.path.join(ELTEN_APPS, entry)
        packages = [full] if entry.endswith('.eltenapp') else [
            os.path.join(full, one) for one in os.listdir(full)
            if one.endswith('.eltenapp')] if os.path.isdir(full) else []
        for one in packages:
            try:
                read = package.read(one)
            except Exception as error:
                print(f"  (could not read {os.path.basename(one)}: {error})")
                continue
            # `Package.files` is [(name, bytes)] - the sources and the
            # assets together, which is why the extension is checked.
            here, own = set(), set()
            for name, data in (read.files or []):
                if not str(name).endswith('.rb'):
                    continue
                text = data.decode('utf-8', 'replace') if isinstance(
                    data, bytes) else str(data)
                here |= set(CALL.findall(text))
                own |= set(DEF.findall(text))
            called |= (here - own)
    return called


def main():
    from src.titan_core import elten_client_actions as client
    if not client._connected():
        print("Elten is not running with the TCE bridge in it, so there is "
              "nothing to ask. Open Elten, open the TCE bridge once (it asks "
              "for permission to share the first time) and run this again.")
        return 2

    called = names_the_applications_call()
    if called is None:
        print(f"No Elten applications here ({ELTEN_APPS} is missing).")
        return 2
    known = names_defined_in(PORT)
    wanted = sorted(n for n in called if n not in known and n not in RUBY)
    print(f"{len(called)} name(s) called by the installed applications, "
          f"{len(wanted)} the port does not define. Asking Elten...")

    missing = []
    for start in range(0, len(wanted), 200):
        batch = wanted[start:start + 200]
        table = client.elten_client_api_batch(batch)
        if table is None:
            print("Elten stopped answering.")
            return 1
        for name in batch:
            entry = table.get(name)
            if isinstance(entry, dict) and entry.get('defined'):
                missing.append((name, entry))

    if not missing:
        print("Nothing: every name an application calls that the port does "
              "not define is not Elten's either.")
        return 0
    print(f"\n{len(missing)} name(s) the REAL Elten has and the port has not:")
    for name, entry in missing:
        signature = client._signature(entry.get('parameters') or [])
        where = entry.get('source') or ''
        print(f"  {name}({signature})" + (f"   {where}" if where else ''))
    return 1


if __name__ == '__main__':
    sys.exit(main())
