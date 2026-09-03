import logging
from pygls.server import LanguageServer
from lsprotocol.types import (
    TEXT_DOCUMENT_DID_OPEN,
    TEXT_DOCUMENT_DID_CHANGE,
    DidOpenTextDocumentParams,
    DidChangeTextDocumentParams,
    Diagnostic,
    Position,
    Range,
    DiagnosticSeverity,
    TEXT_DOCUMENT_COMPLETION,
    CompletionParams,
    CompletionList,
    CompletionItem,
    CompletionItemKind
)
from upsil.type_checker import check_types, upsilTypeError

logging.basicConfig(level=logging.INFO)
server = LanguageServer("upsil-lsp", "v0.1")

def validate_upsil(ls, uri, text):
    diagnostics = []
    try:
        check_types(text)
    except upsilTypeError as e:
        # Mocking the position since our lexer/parser doesn't track full ranges perfectly yet
        d = Diagnostic(
            range=Range(
                start=Position(line=0, character=0),
                end=Position(line=0, character=100)
            ),
            message=str(e),
            severity=DiagnosticSeverity.Error
        )
        diagnostics.append(d)
    except SyntaxError as e:
        d = Diagnostic(
            range=Range(
                start=Position(line=0, character=0),
                end=Position(line=0, character=100)
            ),
            message=str(e),
            severity=DiagnosticSeverity.Error
        )
        diagnostics.append(d)
        
    ls.publish_diagnostics(uri, diagnostics)

@server.feature(TEXT_DOCUMENT_DID_OPEN)
def did_open(ls: LanguageServer, params: DidOpenTextDocumentParams):
    doc = ls.workspace.get_document(params.text_document.uri)
    validate_upsil(ls, params.text_document.uri, doc.source)

@server.feature(TEXT_DOCUMENT_DID_CHANGE)
def did_change(ls: LanguageServer, params: DidChangeTextDocumentParams):
    doc = ls.workspace.get_document(params.text_document.uri)
    validate_upsil(ls, params.text_document.uri, doc.source)

@server.feature(TEXT_DOCUMENT_COMPLETION)
def completions(ls: LanguageServer, params: CompletionParams):
    """
    upsil AI Copilot - Intelligent Autocompletion
    Analyzes context and provides network/struct generation.
    """
    items = []
    
    # 1. Neural Network Architecture Template
    items.append(CompletionItem(
        label='upsil Copilot: Neural Network',
        kind=CompletionItemKind.Snippet,
        detail='AI generated standard PyTorch-compatible model',
        insert_text='model MyNet {\n    var fc1 = [llm] => "Generate a dense layer (128 units)"\n    var fc2 = [llm] => "Generate a classification head (10 classes)"\n    \n    fun forward(x: tensor) -> tensor {\n        // AI: write forward pass\n    }\n}'
    ))
    
    # 2. File I/O Copilot Template
    items.append(CompletionItem(
        label='upsil Copilot: Read File',
        kind=CompletionItemKind.Snippet,
        detail='AI generated File Reading loop',
        insert_text='val file_ptr = fopen("data.txt", "r")\n// AI: read contents\nfclose(file_ptr)'
    ))
    
    # 3. Web Server Copilot Template
    items.append(CompletionItem(
        label='upsil Copilot: Web Server',
        kind=CompletionItemKind.Snippet,
        detail='AI generated TCP WinSock Server',
        insert_text='val server = socket(2, 1, 0) // AF_INET, SOCK_STREAM\nbind(server, 8080)\nlisten(server, 10)\nprint("upsil AI Server is running...")'
    ))

    return CompletionList(is_incomplete=False, items=items)

def main():
    print("Starting upsil LSP Server on stdio...")
    server.start_io()

if __name__ == '__main__':
    main()
