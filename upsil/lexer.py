import re
from typing import NamedTuple, List

class Token(NamedTuple):
    type: str
    value: str
    line: int
    column: int

class LexerError(Exception):
    pass

def lex(code: str) -> List[Token]:
    token_specification = [
        ('NUMBER',   r'\d+(\.\d+)?'),      
        ('ID',       r'[A-Za-z_][A-Za-z0-9_\.]*'), 
        ('RAG_OP',   r'=>'),               
        ('ARROW',    r'->'),               
        ('EQEQ',     r'=='),               
        ('ASSIGN',   r'='),                
        ('RANGE',    r'\.\.'),
        ('COMMENT',  r'//.*'),             
        ('OP',       r'[+\-*/@><]'),       
        ('PUNC',     r'[(){}\[\]:,]'),     
        ('STRING',   r'"[^"]*"'),          
        ('NEWLINE',  r'\n'),               
        ('SKIP',     r'[ \t]+'),           
    ]
    tok_regex = '|'.join('(?P<%s>%s)' % pair for pair in token_specification)
    line_num = 1
    line_start = 0
    tokens = []
    
    keywords = {
        'fun', 'val', 'var', 'tensor', 'prob', 'if', 'else', 'return', 
        'distributed', 'consensus', 'model', 'graph', 'import', 
        'vector_store', 'llm', 'for', 'while', 'in', 'and', 'or', 'not', 
        'true', 'false', 'gpu_kernel', 'malloc', 'free', 'class'
    }
    
    for mo in re.finditer(tok_regex, code):
        kind = mo.lastgroup
        value = mo.group()
        column = mo.start() - line_start
        if kind == 'NUMBER':
            pass
        elif kind == 'ID':
            if value in keywords:
                kind = value.upper()
        elif kind == 'NEWLINE':
            line_start = mo.end()
            line_num += 1
            continue
        elif kind == 'SKIP' or kind == 'COMMENT':
            continue
            
        tokens.append(Token(kind, value, line_num, column))
        
    return tokens
