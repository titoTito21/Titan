"""Titan's own subsystems, exposed to the AI.

``src/titan_core/actions/`` is how *add-ons* offer their functions. This
package is the other half: Titan's built-in services - its settings, the
computer's settings, Titan-Net, Elten, the Titan IM clients and AI OCR - are
not add-ons and have no manifest, so each gets a hand-written tool module here
against the real Python API it already exposes.

Every module offers ``get_*_tools()`` returning agent tools, and they are all
collected by ``get_subsystem_tools()``. A module that cannot import (a missing
optional dependency, a service that is not installed) is skipped with a note
rather than taking the whole toolset down with it.
"""


def get_subsystem_tools():
    """Every tool from every Titan subsystem that is available right now."""
    tools = []
    modules = (
        ('src.ai.tools.settings_tools', 'get_settings_tools'),
        ('src.ai.tools.system_tools', 'get_system_tools'),
        ('src.ai.tools.titannet_tools', 'get_titannet_tools'),
        ('src.ai.tools.elten_tools', 'get_elten_tools'),
        ('src.ai.tools.elten_client_tools', 'get_elten_client_tools'),
        ('src.ai.tools.im_tools', 'get_im_tools'),
        ('src.ai.tools.ocr_tools', 'get_ocr_tools'),
    )
    for module_name, factory_name in modules:
        try:
            module = __import__(module_name, fromlist=[factory_name])
            tools.extend(getattr(module, factory_name)())
        except Exception as e:
            print(f"[ai.tools] {module_name} unavailable: {e}")
    return tools
