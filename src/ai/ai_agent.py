"""Titan AI Agent engine: a provider-agnostic tool-calling loop that lets an AI
model operate the computer through a set of typed tools (see
:mod:`src.ai.agent_tools`).

Supports Anthropic (Tools), Google Gemini (function calling) and OpenAI (tools)
behind one common tool spec. The loop streams the assistant's text and each tool
call out as events so the accessible conversation view can show and SPEAK them,
supports cooperative cancellation (Shift+Escape) and a tiered confirmation
policy for risky tools.

A tool is a dict::

    {
      'name': 'type_text',
      'description': 'Type text at the current focus.',
      'parameters': {   # JSON-schema subset (object with properties)
          'type': 'object',
          'properties': {'text': {'type': 'string', 'description': '...'}},
          'required': ['text'],
      },
      'run': lambda text: '...result string...',
      'risk': 'auto' | 'confirm',
    }

The engine keeps a normalized, provider-independent message history and converts
it to each provider's native shape per step, so no provider SDK object leaks out.
"""

import base64
import json
import traceback

from src.ai import ai_provider


class AgentCancelled(Exception):
    """Raised inside the loop when the cancel event is set."""


# --------------------------------------------------------------------------- #
# Tool-schema conversion (common spec -> each provider)
# --------------------------------------------------------------------------- #
def _to_openai_tools(tools):
    return [{
        'type': 'function',
        'function': {
            'name': t['name'],
            'description': t.get('description', ''),
            'parameters': t.get('parameters', {'type': 'object', 'properties': {}}),
        },
    } for t in tools]


def _to_anthropic_tools(tools):
    return [{
        'name': t['name'],
        'description': t.get('description', ''),
        'input_schema': t.get('parameters', {'type': 'object', 'properties': {}}),
    } for t in tools]


def _jsonschema_to_gemini(schema):
    """Convert a JSON-schema-subset dict into a genai protos.Schema."""
    import google.generativeai as genai
    Type = genai.protos.Type
    type_map = {
        'object': Type.OBJECT, 'string': Type.STRING, 'number': Type.NUMBER,
        'integer': Type.INTEGER, 'boolean': Type.BOOLEAN, 'array': Type.ARRAY,
    }
    if not schema:
        return genai.protos.Schema(type=Type.OBJECT)
    stype = type_map.get(schema.get('type', 'string'), Type.STRING)
    kwargs = {'type': stype}
    if 'description' in schema:
        kwargs['description'] = schema['description']
    if stype == Type.OBJECT:
        props = {k: _jsonschema_to_gemini(v)
                 for k, v in schema.get('properties', {}).items()}
        if props:
            kwargs['properties'] = props
        if schema.get('required'):
            kwargs['required'] = list(schema['required'])
    elif stype == Type.ARRAY:
        kwargs['items'] = _jsonschema_to_gemini(schema.get('items', {'type': 'string'}))
    if 'enum' in schema:
        kwargs['enum'] = [str(e) for e in schema['enum']]
    return genai.protos.Schema(**kwargs)


def _to_gemini_tools(tools):
    import google.generativeai as genai
    decls = [genai.protos.FunctionDeclaration(
        name=t['name'],
        description=t.get('description', ''),
        parameters=_jsonschema_to_gemini(t.get('parameters')),
    ) for t in tools]
    return [genai.protos.Tool(function_declarations=decls)]


# --------------------------------------------------------------------------- #
# Per-provider step: normalized history -> {'text', 'tool_calls'}
# --------------------------------------------------------------------------- #
def _openai_messages(system, history):
    msgs = [{'role': 'system', 'content': system}]
    for m in history:
        if m['role'] == 'user':
            msgs.append({'role': 'user', 'content': m['content']})
        elif m['role'] == 'assistant':
            entry = {'role': 'assistant', 'content': m.get('content') or None}
            if m.get('tool_calls'):
                entry['tool_calls'] = [{
                    'id': c['id'], 'type': 'function',
                    'function': {'name': c['name'], 'arguments': json.dumps(c['args'])},
                } for c in m['tool_calls']]
            msgs.append(entry)
        elif m['role'] == 'tool':
            msgs.append({'role': 'tool', 'tool_call_id': m['tool_call_id'],
                         'content': m['content']})
        elif m['role'] == 'images':
            content = [{'type': 'text', 'text': 'Requested screenshot(s):'}]
            for png in m['images']:
                b64 = base64.b64encode(png).decode('ascii')
                content.append({'type': 'image_url',
                                'image_url': {'url': 'data:image/png;base64,' + b64}})
            msgs.append({'role': 'user', 'content': content})
    return msgs


def _step_openai(model, system, history, tools, api_key):
    import openai
    client = openai.OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=model, messages=_openai_messages(system, history),
        tools=_to_openai_tools(tools) or None, max_tokens=4000)
    msg = resp.choices[0].message
    calls = []
    for tc in (msg.tool_calls or []):
        try:
            args = json.loads(tc.function.arguments or '{}')
        except Exception:
            args = {}
        calls.append({'id': tc.id, 'name': tc.function.name, 'args': args})
    return {'text': msg.content or '', 'tool_calls': calls}


def _anthropic_messages(history):
    msgs = []
    for m in history:
        if m['role'] == 'user':
            msgs.append({'role': 'user', 'content': m['content']})
        elif m['role'] == 'assistant':
            blocks = []
            if m.get('content'):
                blocks.append({'type': 'text', 'text': m['content']})
            for c in m.get('tool_calls', []):
                blocks.append({'type': 'tool_use', 'id': c['id'],
                               'name': c['name'], 'input': c['args']})
            msgs.append({'role': 'assistant', 'content': blocks})
        elif m['role'] == 'tool':
            block = {'type': 'tool_result', 'tool_use_id': m['tool_call_id'],
                     'content': m['content']}
            # Merge consecutive tool results into one user message.
            if msgs and msgs[-1]['role'] == 'user' and isinstance(msgs[-1]['content'], list):
                msgs[-1]['content'].append(block)
            else:
                msgs.append({'role': 'user', 'content': [block]})
        elif m['role'] == 'images':
            blocks = [{'type': 'image', 'source': {
                'type': 'base64', 'media_type': 'image/png',
                'data': base64.b64encode(png).decode('ascii')}} for png in m['images']]
            # Attach images to the tool-result user message when possible.
            if msgs and msgs[-1]['role'] == 'user' and isinstance(msgs[-1]['content'], list):
                msgs[-1]['content'].extend(blocks)
            else:
                msgs.append({'role': 'user', 'content': blocks})
    return msgs


def _step_anthropic(model, system, history, tools, api_key):
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model, system=system, max_tokens=4000,
        tools=_to_anthropic_tools(tools), messages=_anthropic_messages(history))
    text, calls = '', []
    for block in resp.content:
        btype = getattr(block, 'type', '')
        if btype == 'text':
            text += getattr(block, 'text', '')
        elif btype == 'tool_use':
            calls.append({'id': block.id, 'name': block.name,
                          'args': dict(block.input or {})})
    return {'text': text, 'tool_calls': calls}


def _gemini_contents(history):
    import google.generativeai as genai
    proto = genai.protos
    contents = []
    for m in history:
        if m['role'] == 'user':
            contents.append(proto.Content(role='user',
                            parts=[proto.Part(text=m['content'])]))
        elif m['role'] == 'assistant':
            # Gemini 3.x rejects replayed function calls unless the ORIGINAL
            # proto parts (which carry an internal thought signature not exposed
            # as a Python attribute) are sent back verbatim. So reuse the raw
            # parts captured from the response when available.
            raw = m.get('_gemini_raw_parts')
            if raw is not None:
                contents.append(proto.Content(role='model', parts=list(raw)))
            else:
                parts = []
                if m.get('content'):
                    parts.append(proto.Part(text=m['content']))
                for c in m.get('tool_calls', []):
                    parts.append(proto.Part(function_call=proto.FunctionCall(
                        name=c['name'], args=c['args'])))
                contents.append(proto.Content(role='model', parts=parts))
        elif m['role'] == 'tool':
            contents.append(proto.Content(role='user', parts=[proto.Part(
                function_response=proto.FunctionResponse(
                    name=m['name'], response={'result': m['content']}))]))
        elif m['role'] == 'images':
            parts = [proto.Part(inline_data=proto.Blob(mime_type='image/png', data=png))
                     for png in m['images']]
            # Merge into the preceding user content to avoid consecutive user turns.
            if contents and contents[-1].role == 'user':
                for p in parts:
                    contents[-1].parts.append(p)
            else:
                contents.append(proto.Content(role='user', parts=parts))
    return contents


def _step_gemini(model, system, history, tools, api_key):
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    gmodel = genai.GenerativeModel(model, system_instruction=system,
                                   tools=_to_gemini_tools(tools))
    resp = gmodel.generate_content(_gemini_contents(history))
    text, calls = '', []
    try:
        parts = resp.candidates[0].content.parts
    except (IndexError, AttributeError):
        parts = []
    for i, part in enumerate(parts):
        fc = getattr(part, 'function_call', None)
        if fc and getattr(fc, 'name', ''):
            calls.append({'id': f'{fc.name}_{i}', 'name': fc.name,
                          'args': _proto_to_dict(fc.args)})
        elif getattr(part, 'text', ''):
            text += part.text
    # Keep the raw proto parts so the assistant turn can be replayed verbatim
    # (preserves Gemini 3.x thought signatures).
    return {'text': text, 'tool_calls': calls, '_raw_parts': list(parts)}


def _step_gemini_stream(model, system, history, tools, api_key, on_delta):
    """Streaming variant of :func:`_step_gemini`: emits text deltas to
    ``on_delta`` as they arrive (so the caller can start speaking mid-reply)
    while still collecting tool calls and the raw proto parts. Returns the same
    dict shape. Used only when a text-delta consumer is supplied; the caller
    falls back to the non-streaming step if this raises."""
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    gmodel = genai.GenerativeModel(model, system_instruction=system,
                                   tools=_to_gemini_tools(tools))
    resp = gmodel.generate_content(_gemini_contents(history), stream=True)
    text, calls, raw_parts = '', [], []
    idx = 0
    for chunk in resp:
        try:
            parts = chunk.candidates[0].content.parts
        except (IndexError, AttributeError):
            parts = []
        for part in parts:
            raw_parts.append(part)
            fc = getattr(part, 'function_call', None)
            if fc and getattr(fc, 'name', ''):
                calls.append({'id': f'{fc.name}_{idx}', 'name': fc.name,
                              'args': _proto_to_dict(fc.args)})
                idx += 1
            else:
                delta = getattr(part, 'text', '')
                if delta:
                    text += delta
                    try:
                        on_delta(delta)
                    except Exception:
                        pass
    return {'text': text, 'tool_calls': calls, '_raw_parts': raw_parts}


def _proto_to_dict(args):
    """Convert a Gemini proto MapComposite / Struct into a plain dict."""
    out = {}
    try:
        for k, v in args.items():
            out[k] = _proto_value(v)
    except Exception:
        pass
    return out


def _proto_value(v):
    # google proto values expose list/map via python iteration.
    if hasattr(v, 'items'):
        return {k: _proto_value(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)) or (hasattr(v, '__iter__') and not isinstance(v, str)):
        try:
            return [_proto_value(x) for x in v]
        except Exception:
            return v
    return v


_STEP_FUNCS = {
    'anthropic': _step_anthropic,
    'gemini': _step_gemini,
    'openai': _step_openai,
}


# --------------------------------------------------------------------------- #
# Agent loop
# --------------------------------------------------------------------------- #
DEFAULT_SYSTEM = (
    "You are the Titan AI Agent. You operate the user's Windows computer on "
    "their behalf to accomplish their goal. The user is likely blind and relies "
    "on a screen reader, so PREFER reading the screen via accessibility tools "
    "before acting, describe what you are doing in short plain sentences, and "
    "keep actions deliberate. Use the provided tools to observe and act. You "
    "can also call screenshot() to SEE the screen as an image and then click by "
    "coordinates -- always give click/move coordinates in ACTUAL screen pixels "
    "as reported by the screenshot, not image pixels. Prefer reading text via "
    "read_focused_window when it is enough, and use the screenshot only when you "
    "need to see layout or find something visually. When the goal is done, reply "
    "with a short final summary and no further tool calls. If you cannot "
    "proceed, say why.")


def run_agent(goal, tools, *, provider=None, model=None, system=None,
              on_text=None, on_tool_start=None, on_tool_result=None,
              on_text_delta=None,
              confirm=None, confirm_all=False, cancel_event=None, max_steps=25):
    """Run the tool-calling loop until the model stops requesting tools, the
    step budget is exhausted, or cancellation is requested.

    Callbacks (all optional, invoked on the CALLING thread -> marshal to the GUI
    with wx.CallAfter): ``on_text(str)`` per assistant message, ``on_tool_start
    (name, args)``, ``on_tool_result(name, result)``. ``confirm(tool, args) ->
    bool`` gates a tool run (return False to skip). ``cancel_event`` is a
    threading.Event checked between steps and tool calls. Returns the final
    assistant text. Raises :class:`AgentCancelled` if cancelled, or the provider
    error on failure."""
    provider = provider or ai_provider.get_ai_provider()
    api_key = ai_provider.get_ai_key(provider)
    if not api_key:
        raise RuntimeError(f"No API key configured for provider '{provider}'")
    if not model:
        model = ai_provider.resolve_latest_model(provider, api_key)
    system = system or DEFAULT_SYSTEM
    step_fn = _STEP_FUNCS.get(provider)
    if step_fn is None:
        raise RuntimeError(f"Agent does not support provider '{provider}'")
    tool_by_name = {t['name']: t for t in tools}

    def _check_cancel():
        if cancel_event is not None and cancel_event.is_set():
            raise AgentCancelled()

    history = [{'role': 'user', 'content': goal}]
    final_text = ''
    # Stream text deltas (for a voice caller to speak mid-reply) only when a
    # consumer is supplied and the provider supports it (Gemini). The streaming
    # step falls back to the proven non-streaming one on any error, so the agent
    # path is never destabilised.
    use_stream = on_text_delta is not None and provider == 'gemini'
    for _step in range(max_steps):
        _check_cancel()
        if use_stream:
            try:
                result = _step_gemini_stream(model, system, history, tools,
                                             api_key, on_text_delta)
            except Exception as e:
                print(f"[ai_agent] streaming step failed ({e}); using non-stream.")
                use_stream = False
                result = step_fn(model, system, history, tools, api_key)
        else:
            result = step_fn(model, system, history, tools, api_key)
        text = (result.get('text') or '').strip()
        calls = result.get('tool_calls') or []
        if text and on_text:
            on_text(text)
        if not calls:
            return text  # done
        assistant_entry = {'role': 'assistant', 'content': text, 'tool_calls': calls}
        # Opaque per-provider passthrough (Gemini needs the raw parts replayed).
        if result.get('_raw_parts') is not None:
            assistant_entry['_gemini_raw_parts'] = result['_raw_parts']
        history.append(assistant_entry)
        step_images = []
        for call in calls:
            _check_cancel()
            name, args = call['name'], call.get('args', {})
            tool = tool_by_name.get(name)
            # Ask the confirm callback when: policy confirms everything, the tool
            # is a 'confirm'-tier tool, or the tool demands it unconditionally
            # (e.g. run_shell) — the callback itself applies the user's policy.
            needs_confirm = confirm is not None and (
                confirm_all or (tool and (tool.get('risk') == 'confirm'
                                          or tool.get('always_confirm'))))
            if tool is None:
                out = f"Error: unknown tool '{name}'."
            elif needs_confirm and not confirm(tool, args):
                out = "The user declined this action."
            else:
                if on_tool_start:
                    on_tool_start(name, args)
                try:
                    raw_out = tool['run'](**args)
                except AgentCancelled:
                    raise
                except Exception as e:
                    traceback.print_exc()
                    raw_out = f"Error running {name}: {e}"
                # A tool may return an image (e.g. screenshot): its 'text' is the
                # tool result, and the image is fed back as a follow-up user turn
                # so the model can actually see it.
                if isinstance(raw_out, dict) and raw_out.get('image_png'):
                    out = str(raw_out.get('text') or 'Image captured.')
                    step_images.append(raw_out['image_png'])
                else:
                    out = '' if raw_out is None else str(raw_out)
            if on_tool_result:
                on_tool_result(name, out)
            history.append({'role': 'tool', 'tool_call_id': call['id'],
                            'name': name, 'content': out})
        if step_images:
            history.append({'role': 'images', 'images': step_images})
        final_text = text
    return final_text or "Reached the step limit before finishing."
