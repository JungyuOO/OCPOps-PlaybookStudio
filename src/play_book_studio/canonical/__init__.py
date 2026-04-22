"""코퍼스와 플레이북 문서가 같이 바라보는 canonical AST 패키지.

이 패키지는 ingestion/intake 어느 한쪽 출력이 아니라, 둘 다 공유하는
원천 구조를 담는다. 이후 AST -> corpus, AST -> playbook projection이
여기서 갈라진다.
"""

from .models import (
    AnchorBlock,
    AstProvenance,
    CanonicalDocumentAst,
    CanonicalSectionAst,
    CodeBlock,
    NoteBlock,
    ParagraphBlock,
    PlaybookDocumentArtifact,
    PlaybookSectionArtifact,
    PrerequisiteBlock,
    ProcedureBlock,
    ProcedureStep,
    TableBlock,
)
from .html import build_web_document_ast
from .asciidoc import build_source_repo_document_ast
from .project_corpus import CorpusSectionProjection, project_corpus_sections
from .project_playbook import project_playbook_document, write_playbook_documents
from .translate import translate_document_ast
from .validate import CanonicalValidationIssue, validate_document_ast

__all__ = [
    "AnchorBlock",
    "AstProvenance",
    "CanonicalDocumentAst",
    "CanonicalSectionAst",
    "CodeBlock",
    "build_source_repo_document_ast",
    "CorpusSectionProjection",
    "build_web_document_ast",
    "NoteBlock",
    "ParagraphBlock",
    "PlaybookDocumentArtifact",
    "PlaybookSectionArtifact",
    "PrerequisiteBlock",
    "ProcedureBlock",
    "ProcedureStep",
    "TableBlock",
    "CanonicalValidationIssue",
    "project_corpus_sections",
    "project_playbook_document",
    "translate_document_ast",
    "write_playbook_documents",
    "validate_document_ast",
]
