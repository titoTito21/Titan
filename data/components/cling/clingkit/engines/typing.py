# -*- coding: utf-8 -*-
"""A touch-typing course, out of the lesson files the application ships.

Klango's Typing Lessons carries KTouch lecture files - the same XML the KDE
typing tutor uses - and a lecture is the whole of a course:

    <KTouchLecture>
      <Title>Keyboard fast-typing course</Title>
      <Levels>
        <Level><NewCharacters>jf</NewCharacters>
               <Line>ff jjj jf jfj j jff fjjf ff jfj j jff ff jjj fjj</Line>
               ...

so the engine has a title, a set of levels, the characters each level teaches
and the lines to type in it.  What Cling adds is the part that makes it usable
without a screen: every line is read out before it is typed, a wrong key is a
sound and the right character said back, and the line ends with the speed and
the accuracy said in words.  Progress is per Titan-Net account, so two people
sharing a machine are on their own lesson.
"""

import os
import time
import xml.etree.ElementTree as ElementTree

from .base import Engine

LESSON_FOLDERS = ('trainings', 'lessons', 'courses')
#: A run this short is a slip of the hand rather than a measured attempt.
MIN_LINE_FOR_SPEED = 5


class Lesson(object):
    """One course: its title, and the levels in it."""

    __slots__ = ('path', 'title', 'levels')

    def __init__(self, path, title, levels):
        self.path = path
        self.title = title
        self.levels = levels          # [(new_characters, [line, ...])]

    @property
    def name(self):
        return self.title or os.path.splitext(os.path.basename(self.path))[0]


def read_lesson(path):
    """A KTouch lecture, or None when the file is not one."""
    try:
        tree = ElementTree.parse(path)
    except (ElementTree.ParseError, OSError):
        return None
    root = tree.getroot()
    if root.tag not in ('KTouchLecture', 'KTouchLectureFile', 'Lecture'):
        return None
    title = ''
    found = root.find('Title')
    if found is not None and found.text:
        title = found.text.strip()
    levels = []
    for level in root.iter('Level'):
        characters = ''
        new = level.find('NewCharacters')
        if new is not None and new.text:
            characters = new.text.strip()
        lines = [line.text.strip() for line in level.iter('Line')
                 if line is not None and line.text and line.text.strip()]
        if lines:
            levels.append((characters, lines))
    if not levels:
        return None
    return Lesson(path, title, levels)


def find_lessons(root, language=''):
    """Every lesson the application ships, the user's language first."""
    lessons = []
    for folder in LESSON_FOLDERS:
        base = os.path.join(root, folder)
        if not os.path.isdir(base):
            continue
        for directory, _subdirs, files in os.walk(base):
            for leaf in sorted(files):
                if not leaf.lower().endswith('.xml'):
                    continue
                lesson = read_lesson(os.path.join(directory, leaf))
                if lesson is not None:
                    lessons.append(lesson)
    code = (language or '').split('-')[0].lower()
    if code:
        def rank(lesson):
            lowered = lesson.path.lower()
            return 0 if ('lang_%s' % code) in lowered or \
                ('%s.' % code) in os.path.basename(lowered) else 1
        lessons.sort(key=rank)
    return lessons


class TypingEngine(Engine):
    LABEL = 'course'

    def __init__(self, host):
        Engine.__init__(self, host)
        self.lessons = []
        self.lesson_index = 0
        self.level_index = 0
        self.line_index = 0
        self.position = 0
        self.mistakes = 0
        self.started_at = 0.0
        self.state = 'idle'       # idle / ready / typing / done

    # ------------------------------------------------------------- opening
    def start(self):
        self.running = True
        self.lessons = find_lessons(self.host.app.path, self.host.language)
        if not self.lessons:
            self.host.show(self.host.text(
                'no_lessons', default='This application ships no lessons.'))
            self.finished_reason = 'no lessons'
            return
        welcome = self.host.text('welcome')
        self.host.show(welcome or self.host.app.name(self.host.language))
        self.lesson_index = min(int(self.host.store.get('lesson', 0) or 0),
                                len(self.lessons) - 1)
        self.level_index = int(self.host.store.get('level', 0) or 0)
        if self.level_index >= len(self.lesson.levels):
            self.level_index = 0
        self.line_index = 0
        self.present()

    @property
    def lesson(self):
        return self.lessons[self.lesson_index]

    @property
    def level(self):
        return self.lesson.levels[self.level_index]

    @property
    def line(self):
        characters, lines = self.level
        return lines[self.line_index % len(lines)]

    # -------------------------------------------------------------- lesson
    def present(self):
        self.state = 'ready'
        self.position = 0
        self.mistakes = 0
        characters, lines = self.level
        self.host.show('%s - %d/%d' % (self.lesson.name, self.level_index + 1,
                                       len(self.lesson.levels)))
        if characters:
            self.host.show(self.host.text('new_characters',
                                          default='New keys: %s') % characters
                           if '%s' in self.host.text('new_characters',
                                                     default='%s')
                           else characters)
        self.host.show(self.line)
        self.host.show(self.host.text('press_space',
                                      default='Press space to begin typing.'))

    def begin(self):
        self.state = 'typing'
        self.position = 0
        self.mistakes = 0
        self.started_at = self.host.now()
        self.host.play('ui/focus')

    # --------------------------------------------------------------- input
    def key(self, name, modifiers=()):
        name = name or ''
        lowered = name.lower()
        if lowered == 'escape':
            self.stop()
            return True
        if self.state == 'ready':
            if lowered in ('space', 'enter'):
                self.begin()
                return True
            if lowered == 'pagedown':
                self.next_level(1)
                return True
            if lowered == 'pageup':
                self.next_level(-1)
                return True
            if lowered == 'tab':
                self.lesson_index = (self.lesson_index + 1) % len(self.lessons)
                self.level_index = 0
                self.line_index = 0
                self.host.store.set('lesson', self.lesson_index)
                self.present()
                return True
            return False
        if self.state != 'typing':
            if lowered in ('space', 'enter'):
                self.present()
                return True
            return False

        if lowered == 'backspace':
            if self.position:
                self.position -= 1
                self.host.play('ui/back')
            return True
        character = ' ' if lowered == 'space' else name
        if len(character) != 1:
            return False
        expected = self.line[self.position]
        if character == expected:
            self.position += 1
            self.host.play('ui/typing')
            if self.position >= len(self.line):
                self.finish_line()
            return True
        self.mistakes += 1
        self.host.play('ui/error')
        # The character that was WANTED is said, not the one that was typed:
        # a learner who cannot see the line needs to be told where to go, not
        # what they already know they did.
        self.host.say(expected if expected != ' ' else
                      self.host.text('space', default='space'))
        return True

    def finish_line(self):
        self.state = 'done'
        seconds = max(0.001, self.host.now() - self.started_at)
        characters = len(self.line)
        words_per_minute = (characters / 5.0) / (seconds / 60.0)
        accuracy = 100.0 * characters / max(1, characters + self.mistakes)
        self.host.show(self.host.text(
            'line_result', int(words_per_minute), int(accuracy),
            self.mistakes,
            default='%d words a minute, %d%% correct, %d mistakes.')
            if self.host.texts.has('line_result') else
            '%d words a minute, %d%% correct, %d mistakes.'
            % (int(words_per_minute), int(accuracy), self.mistakes))
        if characters >= MIN_LINE_FOR_SPEED:
            self.host.store.record_score(int(words_per_minute),
                                         name=self.host.whoami().name,
                                         table='wpm',
                                         extra={'accuracy': int(accuracy),
                                                'level': self.level_index + 1})
        self.line_index += 1
        _characters, lines = self.level
        if self.line_index >= len(lines):
            self.line_index = 0
            self.next_level(1)
            return
        self.host.show(self.host.text('press_space',
                                      default='Press space for the next line.'))

    def next_level(self, direction):
        self.level_index = (self.level_index + direction) % len(self.lesson.levels)
        self.line_index = 0
        self.host.store.set('level', self.level_index)
        self.present()

    # ------------------------------------------------------------- reading
    def status(self):
        if self.state == 'typing':
            return '%d/%d, %d mistakes' % (self.position, len(self.line),
                                           self.mistakes)
        if not self.lessons:
            return ''
        return '%s, level %d of %d' % (self.lesson.name, self.level_index + 1,
                                       len(self.lesson.levels))

    def rows(self):
        return [lesson.name for lesson in self.lessons]

    def help_text(self):
        own = self.host.text('help')
        if own:
            return own
        return ('Space starts a line and moves to the next one. Tab changes '
                'the course, Page Up and Page Down change the level, Escape '
                'leaves.')


def looks_like_course(root):
    for folder in LESSON_FOLDERS:
        base = os.path.join(root, folder)
        if not os.path.isdir(base):
            continue
        for directory, _subdirs, files in os.walk(base):
            for leaf in files:
                if leaf.lower().endswith('.xml') and \
                        read_lesson(os.path.join(directory, leaf)) is not None:
                    return True
    return False
