# -*- coding: utf-8 -*-
"""What a picture SHOWS, named on this machine.

The tier above this names the icons Windows itself drew - a folder, a
printer, the warning triangle - by comparing pictures, and measured on a
real desktop it names almost none of the ones that matter: every program
draws its own artwork, so Battle.net, GitHub Desktop, Elten and the
command prompt all came back "its own artwork". Naming those needs
something that has seen the world, and the tier below is the AI, which
costs a picture of the user's screen at a provider.

This is the one in between: **CLIP, quantised, on this machine.** It is
asked "which of these does this picture look most like" against a written
vocabulary of the things icons actually are - a warning, an arrow, a dog,
a padlock, a shopping trolley - and answers the nearest, or nothing.

**It answers nothing far more often than a classifier normally would**,
and that is the whole design. A zero-shot model always has a nearest
label: asked what the Battle.net logo is, it will confidently say
"a shield" or "a globe" because one of them is nearest. A reader that
announces a confident wrong noun is worse than one that says "icon", so
there is a floor (:data:`SURE_ENOUGH`) and a margin over the runner-up
(:data:`CLEAR_MARGIN`), and below either it says nothing and lets the
question fall to the AI.

Downloaded, never built in - see :mod:`local_model`, which this follows
in every respect: nothing imported at module level, absent is a normal
state, and the files live in the user's own folder rather than inside an
install.
"""

import os
import threading

_LOCK = threading.RLock()

#: What is needed. `onnxruntime` runs the two halves; `huggingface_hub`
#: is only used to FETCH them and is never needed to use one.
PACKAGES = ('onnxruntime',)
FETCHING = ('huggingface_hub',)

#: Where the model came from, and the files that make it up. The two
#: halves are quantised on purpose: the full pair is 860 MB against 154,
#: and this is a download.
REPOSITORY = 'Xenova/clip-vit-base-patch32'
FILES = ('onnx/vision_model_quantized.onnx',
         'onnx/text_model_quantized.onnx',
         'tokenizer.json', 'preprocessor_config.json', 'config.json')

#: How sure the model must be before the reader says a word at all, and
#: how far ahead of the runner-up. Both matter: a picture that is 30%
#: "a globe" and 29% "a shield" is a picture the model cannot tell, and
#: announcing either would be a confident lie.
SURE_ENOUGH = 0.22
CLEAR_MARGIN = 0.06

#: The things icons ARE. Written rather than learned, because the answer
#: has to be a word a person would use - "a warning", not "a triangular
#: sign with an exclamation mark". Each is phrased as CLIP expects, as a
#: sentence about a picture.
#:
#: The last few are the ESCAPES: a program's own logo, a letter, a
#: photograph. Without something for the model to put those in, every
#: logo lands on whichever real noun is nearest, which is exactly the
#: confident wrong answer this tier must not give.
VOCABULARY = (
    ('warning', 'a warning sign'),
    ('error', 'an error symbol, a red cross'),
    ('information', 'an information symbol, a letter i in a circle'),
    ('question', 'a question mark'),
    ('arrow', 'an arrow'),
    ('folder', 'a folder'),
    ('document', 'a document, a sheet of paper'),
    ('picture', 'a photograph or a picture frame'),
    ('printer', 'a printer'),
    ('camera', 'a camera'),
    ('microphone', 'a microphone'),
    ('speaker', 'a loudspeaker'),
    ('music', 'a musical note'),
    ('envelope', 'an envelope, an e-mail symbol'),
    ('telephone', 'a telephone'),
    ('padlock', 'a padlock'),
    ('key', 'a key'),
    ('shield', 'a shield'),
    ('magnifier', 'a magnifying glass'),
    ('gear', 'a gear wheel, a settings symbol'),
    ('house', 'a house'),
    ('person', 'a person, a silhouette of a head and shoulders'),
    ('group', 'a group of people'),
    ('dog', 'a dog'),
    ('cat', 'a cat'),
    ('bird', 'a bird'),
    ('tree', 'a tree'),
    ('flower', 'a flower'),
    ('car', 'a car'),
    ('aeroplane', 'an aeroplane'),
    ('ship', 'a ship'),
    ('globe', 'a globe, a picture of the earth'),
    ('map', 'a map'),
    ('clock', 'a clock'),
    ('calendar', 'a calendar'),
    ('star', 'a star'),
    ('heart', 'a heart'),
    ('flag', 'a flag'),
    ('basket', 'a shopping basket or trolley'),
    ('money', 'money, a coin or a banknote'),
    ('chart', 'a chart or a graph'),
    ('pencil', 'a pencil or a pen'),
    ('scissors', 'a pair of scissors'),
    ('bin', 'a waste bin'),
    ('disc', 'a disc, a compact disc'),
    ('computer', 'a computer or a monitor'),
    ('telephone handset', 'a mobile telephone'),
    ('battery', 'a battery'),
    ('cloud', 'a cloud'),
    ('fire', 'a flame'),
    ('lightning', 'a lightning bolt'),
    ('puzzle', 'a jigsaw piece'),
    ('book', 'a book'),
    ('bell', 'a bell'),
    ('lightbulb', 'a light bulb'),
    ('tick', 'a tick, a check mark'),
    ('cross', 'a cross, an X'),
    ('plus', 'a plus sign'),
    ('play', 'a play triangle, a media play button'),
    # The escapes.
    ('', "a company's logo"),
    ('', 'a letter of the alphabet'),
    ('', 'an abstract shape with no meaning'),
)

_state = {'reads': 0, 'named': 0, 'unsure': 0, 'ms': 0.0, 'why': ''}
_held = {'vision': None, 'text': None, 'labels': None}


def folder():
    from src.ai.ocr import local_model
    return os.path.join(local_model.folder(), 'clip')


def available():
    """Whether a picture can be named here and now. ``(ok, why)``."""
    for name in PACKAGES:
        try:
            __import__(name)
        except Exception:                            # noqa: BLE001
            return False, 'onnxruntime is not installed here'
    where = folder()
    for name in FILES:
        if not os.path.exists(os.path.join(where, name.replace('/', os.sep))):
            return False, ('the icon model has not been downloaded (%s is '
                           'missing)' % name)
    return True, ''


def installed():
    return available()[0]


def install(timeout=1800.0):
    """Fetch the model. ``(ok, sentence)``. A download, so it is asked for."""
    from src.ai.ocr import local_model
    for name in FETCHING:
        try:
            __import__(name)
        except Exception:                            # noqa: BLE001
            ok, said = local_model._pip(
                ['install', '--upgrade', '--user', name], timeout=timeout)
            if not ok:
                return False, 'huggingface_hub could not be installed: %s' \
                    % said[-200:]
    try:
        __import__('onnxruntime')
    except Exception:                                # noqa: BLE001
        ok, said = local_model._pip(
            ['install', '--upgrade', '--user', 'onnxruntime'],
            timeout=timeout)
        if not ok:
            return False, 'onnxruntime could not be installed: %s' \
                % said[-200:]
    try:
        from huggingface_hub import hf_hub_download
    except Exception as error:                       # noqa: BLE001
        return False, str(error)
    where = folder()
    os.makedirs(where, exist_ok=True)
    for name in FILES:
        try:
            hf_hub_download(REPOSITORY, name, local_dir=where)
        except Exception as error:                   # noqa: BLE001
            return False, '%s could not be fetched: %s' % (name, error)
    return True, ('The icon model is here. It names what a picture shows '
                  'without anything leaving this machine.')


# --------------------------------------------------------------------------- #
# Using it
# --------------------------------------------------------------------------- #
def _sessions():
    """The two halves, loaded once."""
    with _LOCK:
        if _held['vision'] is not None:
            return _held['vision'], _held['text']
    import onnxruntime
    where = folder()
    options = onnxruntime.SessionOptions()
    options.log_severity_level = 3
    vision = onnxruntime.InferenceSession(
        os.path.join(where, 'onnx', 'vision_model_quantized.onnx'),
        options, providers=['CPUExecutionProvider'])
    text = onnxruntime.InferenceSession(
        os.path.join(where, 'onnx', 'text_model_quantized.onnx'),
        options, providers=['CPUExecutionProvider'])
    with _LOCK:
        _held['vision'], _held['text'] = vision, text
    return vision, text


def _label_vectors():
    """The vocabulary, encoded once - which is the slow half and is the
    same for every picture ever asked about."""
    with _LOCK:
        if _held['labels'] is not None:
            return _held['labels']
    import numpy as np
    from tokenizers import Tokenizer
    _vision, text = _sessions()
    tokenizer = Tokenizer.from_file(os.path.join(folder(), 'tokenizer.json'))
    tokenizer.enable_padding(length=77, pad_id=49407, pad_token='<|endoftext|>')
    tokenizer.enable_truncation(max_length=77)
    said = ['a picture of %s' % phrase for _kind, phrase in VOCABULARY]
    encoded = tokenizer.encode_batch(said)
    ids = np.array([one.ids for one in encoded], dtype=np.int64)
    # **This export takes `input_ids` and nothing else.** Handing it an
    # attention mask as well is refused outright ("Invalid input name"),
    # and the padding is already what the model expects - so what it is
    # given is read off the session rather than assumed.
    wanted = {one.name for one in text.get_inputs()}
    fed = {'input_ids': ids}
    if 'attention_mask' in wanted:
        fed['attention_mask'] = np.array(
            [one.attention_mask for one in encoded], dtype=np.int64)
    found = text.run(None, fed)[0]
    found = found / (np.linalg.norm(found, axis=1, keepdims=True) + 1e-9)
    with _LOCK:
        _held['labels'] = found
    return found


def _prepared(picture):
    """One RGB array as CLIP wants it: 224x224, normalised."""
    import numpy as np
    height, width = picture.shape[0], picture.shape[1]
    # Nearest-neighbour, because an icon is small, hard-edged artwork and
    # a smooth resize turns a 16-pixel symbol into a smudge.
    rows = (np.arange(224) * height // 224).clip(0, height - 1)
    columns = (np.arange(224) * width // 224).clip(0, width - 1)
    small = picture[rows][:, columns].astype(np.float32) / 255.0
    mean = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
    deviation = np.array([0.26862954, 0.26130258, 0.27577711],
                         dtype=np.float32)
    small = (small - mean) / deviation
    return small.transpose(2, 0, 1)[None, :, :, :]


def describe(picture):
    """What that RGB array shows, in a word. ``(ok, word_or_why)``.

    ``(False, ...)`` where the model is not sure enough, which is a real
    answer and the commonest one for a program's own logo.
    """
    import time
    ok, why = available()
    if not ok:
        return False, why
    started = time.time()
    try:
        import numpy as np
        vision, _text = _sessions()
        labels = _label_vectors()
        found = vision.run(None, {'pixel_values': _prepared(picture)})[0]
        found = found / (np.linalg.norm(found) + 1e-9)
        scores = (labels @ found.reshape(-1))
        # Softmax, so the numbers are comparable between pictures.
        weights = np.exp((scores - scores.max()) * 100.0)
        weights = weights / weights.sum()
        order = np.argsort(-weights)
    except Exception as error:                       # noqa: BLE001
        with _LOCK:
            _state['why'] = '%s: %s' % (type(error).__name__, error)
        return False, _state['why']
    best = int(order[0])
    runner_up = float(weights[int(order[1])]) if len(order) > 1 else 0.0
    with _LOCK:
        _state['reads'] += 1
        _state['ms'] = round((time.time() - started) * 1000.0, 1)
    kind = VOCABULARY[best][0]
    sure = float(weights[best])
    if not kind:
        # It looks most like a logo, a letter or nothing in particular -
        # which is the honest answer for most program icons.
        with _LOCK:
            _state['unsure'] += 1
        return False, 'it is a logo or an abstract shape'
    if sure < SURE_ENOUGH or (sure - runner_up) < CLEAR_MARGIN:
        with _LOCK:
            _state['unsure'] += 1
        return False, ('not sure enough: %s at %.0f%%, next %.0f%%'
                       % (kind, sure * 100, runner_up * 100))
    with _LOCK:
        _state['named'] += 1
    return True, kind


def report():
    with _LOCK:
        found = dict(_state)
    found.update({'installed': installed(), 'folder': folder(),
                  'loaded': _held['vision'] is not None,
                  'vocabulary': len([one for one in VOCABULARY if one[0]])})
    return found


def forget():
    with _LOCK:
        _held['vision'] = _held['text'] = _held['labels'] = None


# --------------------------------------------------------------------------- #
# Measured, and not yet good enough to speak
# --------------------------------------------------------------------------- #
#: **This tier is deliberately reached by nothing that speaks.**
#:
#: Measured on this machine, 2026-09-10, against the icons really on it:
#:
#: * Windows' own stock icons, drawn on white and asked of the model:
#:   10 asked, 6 answered, and 3 of those 6 were wrong - information as
#:   "error", folder as "envelope", shield as "disc". Those particular
#:   icons never reach here anyway, because `iconNames` names them
#:   EXACTLY by comparing pictures, which is what that tier is for.
#: * The real program icons, which are what this tier exists for:
#:   9 asked, it declined 6 (including Battle.net, correctly, as a logo)
#:   and spoke 3 times - GitHub Desktop, and two folder windows, all
#:   three announced as "information". Every one wrong.
#:
#: A reader that says "envelope" for a folder is worse than one that says
#: "icon", so the honest thing is to leave it unreached until it is
#: right. What is most likely to make it right is a BIGGER picture: a
#: window's icon is 32 pixels and CLIP wants 224, so what it is being
#: shown is an eightfold upscale of flat artwork. Most executables carry
#: a 256-pixel icon (`SHDefExtractIconW` reaches it), and that is the
#: next thing to try rather than a different model.
#:
#: Until then the order is: `iconNames` for what Windows drew (exact,
#: free, instant), and the AI for everything else - which describes a
#: program's logo well and is remembered per program, so it costs one
#: request in that program's life.
NOT_YET_SPOKEN = True
