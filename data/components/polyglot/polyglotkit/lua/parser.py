# -*- coding: utf-8 -*-
"""Lua, parsed into the tree the interpreter walks.

Recursive descent with Lua 5.1's own precedence table.  The tree is tuples
rather than classes on purpose: it is walked once per statement in a game loop
that has to keep up with a mole appearing every third of a second, and an
attribute lookup per node is a cost with nothing to show for it.

    expression      ('num'|'str', value) ('nil',) ('true',) ('false',)
                    ('vararg',) ('name', n) ('index', object, key)
                    ('call', f, args, line) ('method', object, name, args, line)
                    ('func', params, is_vararg, body, name)
                    ('table', array, hash) ('binop', op, l, r, line)
                    ('unop', op, e, line) ('and', l, r) ('or', l, r)

    statement       ('local', names, exprs) ('assign', targets, exprs, line)
                    ('callstat', call) ('do', block) ('while', cond, block)
                    ('repeat', block, cond) ('if', arms, otherwise)
                    ('fornum', name, a, b, step, block, line)
                    ('forin', names, exprs, block, line)
                    ('localfunc', name, func) ('return', exprs, line) ('break',)
"""

from .lexer import LuaSyntaxError, tokenise

#: Lua 5.1 binary precedence: (left, right). `..` and `^` are right associative,
#: which is why their two numbers differ.
_BINARY = {
    'or': (1, 1), 'and': (2, 2),
    '<': (3, 3), '>': (3, 3), '<=': (3, 3), '>=': (3, 3),
    '~=': (3, 3), '==': (3, 3),
    '..': (9, 8),
    '+': (10, 10), '-': (10, 10),
    '*': (11, 11), '/': (11, 11), '%': (11, 11),
    '^': (14, 13),
}
_UNARY_PRIORITY = 12
_BLOCK_ENDERS = frozenset(('end', 'else', 'elseif', 'until'))


class Parser(object):
    def __init__(self, source, chunk='chunk'):
        self.chunk = chunk
        self.tokens = tokenise(source, chunk)
        self.position = 0

    # ------------------------------------------------------------- helpers
    def peek(self, ahead=0):
        index = min(self.position + ahead, len(self.tokens) - 1)
        return self.tokens[index]

    def next(self):
        token = self.tokens[self.position]
        if token.kind != 'eof':
            self.position += 1
        return token

    def fail(self, message, token=None):
        token = token or self.peek()
        raise LuaSyntaxError(message, token.line, self.chunk)

    def check(self, kind, value=None):
        token = self.peek()
        return token.kind == kind and (value is None or token.value == value)

    def accept(self, kind, value=None):
        if self.check(kind, value):
            return self.next()
        return None

    def expect(self, kind, value=None):
        token = self.peek()
        if not self.check(kind, value):
            self.fail("expected %r, found %r" % (value or kind, token.value))
        return self.next()

    # -------------------------------------------------------------- blocks
    def parse(self):
        block = self.block()
        if self.peek().kind != 'eof':
            self.fail("unexpected %r" % (self.peek().value,))
        return block

    def block(self):
        statements = []
        while True:
            token = self.peek()
            if token.kind == 'eof':
                break
            if token.kind == 'keyword' and token.value in _BLOCK_ENDERS:
                break
            if token.kind == 'keyword' and token.value == 'return':
                line = self.next().line
                expressions = []
                if not self._block_over():
                    expressions = self.expression_list()
                self.accept('symbol', ';')
                statements.append(('return', expressions, line))
                break
            if token.kind == 'keyword' and token.value == 'break':
                self.next()
                self.accept('symbol', ';')
                statements.append(('break',))
                break
            statement = self.statement()
            if statement is not None:
                statements.append(statement)
        return statements

    def _block_over(self):
        token = self.peek()
        if token.kind == 'eof':
            return True
        if token.kind == 'keyword' and token.value in _BLOCK_ENDERS:
            return True
        return token.kind == 'symbol' and token.value == ';'

    # ---------------------------------------------------------- statements
    def statement(self):
        token = self.peek()

        if token.kind == 'symbol' and token.value == ';':
            self.next()
            return None

        if token.kind == 'keyword':
            handler = getattr(self, '_statement_' + token.value, None)
            if handler is not None:
                return handler()

        line = token.line
        first = self.suffixed_expression()
        if self.check('symbol', '=') or self.check('symbol', ','):
            targets = [first]
            while self.accept('symbol', ','):
                targets.append(self.suffixed_expression())
            self.expect('symbol', '=')
            for target in targets:
                if target[0] not in ('name', 'index'):
                    self.fail('cannot assign to this')
            return ('assign', targets, self.expression_list(), line)
        if first[0] not in ('call', 'method'):
            self.fail('syntax error near %r' % (token.value,), token)
        return ('callstat', first)

    def _statement_local(self):
        self.next()
        if self.accept('keyword', 'function'):
            name = self.expect('name').value
            return ('localfunc', name, self.function_body(name))
        names = [self.expect('name').value]
        while self.accept('symbol', ','):
            names.append(self.expect('name').value)
        expressions = self.expression_list() if self.accept('symbol', '=') else []
        return ('local', names, expressions)

    def _statement_do(self):
        self.next()
        body = self.block()
        self.expect('keyword', 'end')
        return ('do', body)

    def _statement_while(self):
        self.next()
        condition = self.expression()
        self.expect('keyword', 'do')
        body = self.block()
        self.expect('keyword', 'end')
        return ('while', condition, body)

    def _statement_repeat(self):
        self.next()
        body = self.block()
        self.expect('keyword', 'until')
        return ('repeat', body, self.expression())

    def _statement_if(self):
        self.next()
        arms = []
        condition = self.expression()
        self.expect('keyword', 'then')
        arms.append((condition, self.block()))
        while self.accept('keyword', 'elseif'):
            condition = self.expression()
            self.expect('keyword', 'then')
            arms.append((condition, self.block()))
        otherwise = self.block() if self.accept('keyword', 'else') else None
        self.expect('keyword', 'end')
        return ('if', arms, otherwise)

    def _statement_for(self):
        line = self.next().line
        first = self.expect('name').value
        if self.accept('symbol', '='):
            start = self.expression()
            self.expect('symbol', ',')
            stop = self.expression()
            step = self.expression() if self.accept('symbol', ',') else None
            self.expect('keyword', 'do')
            body = self.block()
            self.expect('keyword', 'end')
            return ('fornum', first, start, stop, step, body, line)
        names = [first]
        while self.accept('symbol', ','):
            names.append(self.expect('name').value)
        self.expect('keyword', 'in')
        expressions = self.expression_list()
        self.expect('keyword', 'do')
        body = self.block()
        self.expect('keyword', 'end')
        return ('forin', names, expressions, body, line)

    def _statement_function(self):
        line = self.next().line
        target = ('name', self.expect('name').value)
        pretty = target[1]
        is_method = False
        while True:
            if self.accept('symbol', '.'):
                key = self.expect('name').value
                pretty += '.' + key
                target = ('index', target, ('str', key), line)
            elif self.accept('symbol', ':'):
                key = self.expect('name').value
                pretty += ':' + key
                target = ('index', target, ('str', key))
                is_method = True
                break
            else:
                break
        return ('assign', [target],
                [self.function_body(pretty, is_method)], line)

    # --------------------------------------------------------- expressions
    def expression_list(self):
        expressions = [self.expression()]
        while self.accept('symbol', ','):
            expressions.append(self.expression())
        return expressions

    def expression(self, limit=0):
        token = self.peek()
        if (token.kind == 'keyword' and token.value == 'not') or \
                (token.kind == 'symbol' and token.value in ('-', '#')):
            self.next()
            operand = self.expression(_UNARY_PRIORITY)
            left = ('unop', token.value, operand, token.line)
        else:
            left = self.simple_expression()

        while True:
            token = self.peek()
            operator = token.value
            if token.kind == 'keyword' and operator in ('and', 'or'):
                pass
            elif token.kind == 'symbol' and operator in _BINARY:
                pass
            else:
                break
            left_priority, right_priority = _BINARY[operator]
            if left_priority <= limit:
                break
            self.next()
            right = self.expression(right_priority)
            if operator == 'and':
                left = ('and', left, right)
            elif operator == 'or':
                left = ('or', left, right)
            else:
                left = ('binop', operator, left, right, token.line)
        return left

    def simple_expression(self):
        token = self.peek()
        if token.kind == 'number':
            self.next()
            return ('num', token.value)
        if token.kind == 'string':
            self.next()
            return ('str', token.value)
        if token.kind == 'keyword':
            if token.value == 'nil':
                self.next()
                return ('nil',)
            if token.value == 'true':
                self.next()
                return ('true',)
            if token.value == 'false':
                self.next()
                return ('false',)
            if token.value == 'function':
                self.next()
                return self.function_body('')
        if token.kind == 'symbol':
            if token.value == '...':
                self.next()
                return ('vararg',)
            if token.value == '{':
                return self.table_constructor()
        return self.suffixed_expression()

    def primary_expression(self):
        token = self.peek()
        if token.kind == 'name':
            self.next()
            return ('name', token.value)
        if token.kind == 'symbol' and token.value == '(':
            self.next()
            inner = self.expression()
            self.expect('symbol', ')')
            # Parentheses truncate a multiple-value expression to one value,
            # which is a real difference in Lua: `f((g()))` passes one argument
            # however many `g` returned.
            return ('paren', inner)
        self.fail('unexpected %r' % (token.value,))

    def suffixed_expression(self):
        expression = self.primary_expression()
        while True:
            token = self.peek()
            if token.kind == 'symbol' and token.value == '.':
                self.next()
                expression = ('index', expression,
                              ('str', self.expect('name').value), token.line)
            elif token.kind == 'symbol' and token.value == '[':
                self.next()
                key = self.expression()
                self.expect('symbol', ']')
                expression = ('index', expression, key, token.line)
            elif token.kind == 'symbol' and token.value == ':':
                self.next()
                name = self.expect('name').value
                expression = ('method', expression, name,
                              self.call_arguments(), token.line)
            elif (token.kind == 'symbol' and token.value in ('(', '{')) \
                    or token.kind == 'string':
                expression = ('call', expression, self.call_arguments(),
                              token.line)
            else:
                return expression

    def call_arguments(self):
        token = self.peek()
        if token.kind == 'string':
            self.next()
            return [('str', token.value)]
        if token.kind == 'symbol' and token.value == '{':
            return [self.table_constructor()]
        self.expect('symbol', '(')
        if self.accept('symbol', ')'):
            return []
        arguments = self.expression_list()
        self.expect('symbol', ')')
        return arguments

    def table_constructor(self):
        self.expect('symbol', '{')
        array = []
        hash_part = []
        while not self.check('symbol', '}'):
            if self.check('symbol', '['):
                self.next()
                key = self.expression()
                self.expect('symbol', ']')
                self.expect('symbol', '=')
                hash_part.append((key, self.expression()))
            elif self.peek().kind == 'name' and self.peek(1).kind == 'symbol' \
                    and self.peek(1).value == '=':
                key = self.next().value
                self.next()
                hash_part.append((('str', key), self.expression()))
            else:
                array.append(self.expression())
            if not (self.accept('symbol', ',') or self.accept('symbol', ';')):
                break
        self.expect('symbol', '}')
        return ('table', array, hash_part)

    def function_body(self, name, is_method=False):
        self.expect('symbol', '(')
        parameters = ['self'] if is_method else []
        is_vararg = False
        if not self.check('symbol', ')'):
            while True:
                if self.accept('symbol', '...'):
                    is_vararg = True
                    break
                parameters.append(self.expect('name').value)
                if not self.accept('symbol', ','):
                    break
        self.expect('symbol', ')')
        body = self.block()
        self.expect('keyword', 'end')
        return ('func', parameters, is_vararg, body, name)


def parse(source, chunk='chunk'):
    return Parser(source, chunk).parse()
