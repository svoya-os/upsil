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
    DiagnosticSeverity
)
from cortex.type_checker import check_types, CortexTypeError

logging.basicConfig(level=logging.INFO)
server = LanguageServer("cortex-lsp", "v0.1")

def validate_cortex(ls, uri, text):
    diagnostics = []
    try:
        check_types(text)
    except CortexTypeError as e:
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
    validate_cortex(ls, params.text_document.uri, doc.source)

@server.feature(TEXT_DOCUMENT_DID_CHANGE)
def did_change(ls: LanguageServer, params: DidChangeTextDocumentParams):
    doc = ls.workspace.get_document(params.text_document.uri)
    validate_cortex(ls, params.text_document.uri, doc.source)

def main():
    print("Starting Cortex LSP Server on stdio...")
    server.start_io()

if __name__ == '__main__':
    main()
