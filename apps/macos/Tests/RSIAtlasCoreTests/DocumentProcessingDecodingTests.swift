import Foundation
import Testing
@testable import RSIAtlasCore

struct DocumentProcessingDecodingTests {
    @Test func statusAndPageDecodeStrictContracts() throws {
        let statusJSON = Data(
            """
            {
              "schema_version": "rsi-atlas.document-processing.status.v1",
              "acquisition_id": "55555555-5555-4555-8555-555555555555",
              "state": "canonicalized",
              "parse_attempt_id": null,
              "document_version_id": "canonical:\(String(repeating: "a", count: 64))",
              "canonical_content_hash": "\(String(repeating: "a", count: 64))",
              "page_count": 1,
              "warnings": [],
              "failure_code": null
            }
            """.utf8
        )
        let status = try JSONDecoder().decode(DocumentProcessingStatus.self, from: statusJSON)
        #expect(status.state == .canonicalized)
        #expect(status.pageCount == 1)

        let pageJSON = Data(
            """
            {
              "schema_version": "rsi-atlas.canonical-page.v1",
              "document_version_id": "canonical:\(String(repeating: "a", count: 64))",
              "page_number": 1,
              "raw_text": "Hello",
              "normalized_text": "Hello",
              "element_count": 1,
              "elements": [
                {
                  "kind": "text",
                  "role": "paragraph",
                  "reading_order": 0,
                  "raw_text": "Hello",
                  "normalized_text": "Hello",
                  "source_box": {"left": "0.000000", "bottom": "0.000000", "right": "1.000000", "top": "1.000000", "coordinate_system": "pdf_bottom_left_points"},
                  "normalized_box": {"left": "0.000000", "bottom": "1.000000", "right": "1.000000", "top": "0.000000", "coordinate_system": "normalized_top_left"},
                  "source_span_id": "span_0000",
                  "raw_text_hash": "\(String(repeating: "b", count: 64))",
                  "normalized_text_hash": "\(String(repeating: "b", count: 64))"
                }
              ],
              "source_artifact_digest": "\(String(repeating: "c", count: 64))",
              "canonical_content_hash": "\(String(repeating: "a", count: 64))",
              "parser_name": "pypdf",
              "parser_version": "6.14.2"
            }
            """.utf8
        )
        let page = try JSONDecoder().decode(CanonicalPageEvidence.self, from: pageJSON)
        #expect(page.rawText == "Hello")
        #expect(page.elements.count == 1)
    }
}
