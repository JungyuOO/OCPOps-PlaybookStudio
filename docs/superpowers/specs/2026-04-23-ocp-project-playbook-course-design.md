# OCP Project Playbook Course Design

Date: 2026-04-23  
Status: Active design baseline

## 1. Core Direction

The course is built from real project PPT artifacts in `study-docs/*.pptx`.

The system must teach users in project order:

1. architecture
2. unit test
3. integration test
4. performance test
5. completion

The key design decision is this:

- do **not** treat slide-wide reading order as the main problem,
- do **not** treat full-slide renders as the main chunk source,
- do treat each slide as a semantic layout containing zones, relations, and optional image assets,
- then derive parent/child retrieval chunks from that intermediate representation.

The correct pipeline is:

```text
raw shapes -> semantic zones/relations -> slide_graph -> chunk templates -> retrieval/index
```

## 2. Why Reading Order Alone Is Wrong

This corpus mixes very different layouts:

- numbered flow diagrams
- two-column mapping slides
- table + note + chart hybrids
- component/network diagrams
- completion-report narrative sections

Global reading order is not stable enough for RAG.  
The main objective is not “how a human would read the whole slide”, but “what semantic unit a user question should hit”.

Priority for semantic interpretation:

1. explicit step/number markers
2. table structure
3. same-row / same-column pairing
4. caption / note proximity
5. only then top-left -> bottom-right fallback

## 3. Storage Model: Two Layers

### 3.1 slide_graph.json

This is the intermediate artifact.

Purpose:

- parser debugging
- re-chunking without reopening PPT
- relation-aware quality tuning

This is **not** the direct retrieval/indexing layer.

### 3.2 chunk.json

This is the actual retrieval unit.

Purpose:

- Qdrant indexing
- sparse/BM25 indexing
- answer generation
- UI drilldown

## 4. slide_graph_v1

Each deck should produce a `slide_graph_v1` artifact.

High-level shape:

```json
{
  "schema_version": "ppt_slide_graph_v1",
  "deck": {
    "deck_id": "service_mesh",
    "family": "architecture",
    "source_file": "KMSC-COCP-RECR-005_아키텍처설계서_서비스메쉬_20260116_FINAL.pptx"
  },
  "slides": [
    {
      "slide": {
        "slide_no": 14,
        "slide_uid": "service_mesh#14",
        "design_id": "DSGN-005-209",
        "design_title": "서비스메쉬 POD별 URL 맵핑",
        "design_variant": "default",
        "part_no": null,
        "part_total": null,
        "layout_type": "mapping_2col"
      },
      "layout_hints": {
        "has_numbered_steps": false,
        "has_swimlanes": false,
        "has_table": false,
        "has_large_image": false,
        "has_repeated_header_footer": true
      },
      "zones": [],
      "relations": [],
      "attachments": [],
      "discarded_zones": [],
      "qa_refs": {
        "full_slide_png": "slides/service_mesh/14.png"
      }
    }
  ]
}
```

### Required semantic components

- `zones`
- `relations`
- `attachments`
- `discarded_zones`

`discarded_zones` is important for debugging.  
It explains why repeated headers, footers, or decorative labels were excluded from search/index text.

## 5. Chunk Model: parent/child

Final retrieval units are parent/child chunks.

High-level structure:

```json
{
  "schema_version": "ppt_chunk_v1",
  "chunk_id": "architecture:DSGN-005-209:default:none:mapping_row:mb-v1-to-svc-member",
  "parent_chunk_id": "architecture:DSGN-005-209:default:none:design_summary",
  "root_chunk_id": "architecture:DSGN-005-209:default:none:design_summary",
  "bundle_id": "architecture:DSGN-005-209:default",
  "source_kind": "project_artifact"
}
```

### Chunk field categories

#### content

Human-readable content:

- `title`
- `summary`
- `body_md`
- `visual_summary`
- `captions`

#### structured

Typed, domain-aware fields:

- `route_prefixes`
- `service_names`
- `namespace_names`
- `pvc_names`
- `storage_classes`
- `capacity_raw`
- `actors`
- `tools`
- `envs`

#### facets

Exact filters and lookup anchors:

- `design_ids`
- `route_prefixes`
- `service_names`
- `namespace_names`
- `storage_classes`
- `pvc_names`
- `hostnames`
- `ips`
- `envs`

#### index_texts

This separation is critical:

- `dense_text`
- `sparse_text`
- `title_text`
- `visual_text`

`visual_text` is **not** metadata-only.  
It must be searchable auxiliary text, but it must not replace the main body.

#### provenance

- shape ids
- bbox union
- parser version
- layout confidence
- chunk confidence

## 6. Chunk ID Rule

Do not use `slide_no` as the stable ID.

Use:

```text
{family}:{design_id}:{variant}:{part}:{chunk_kind}:{local_key}
```

Examples:

- `architecture:DSGN-005-202:default:none:design_summary`
- `architecture:DSGN-005-202:default:none:step:03`
- `architecture:DSGN-005-209:default:none:mapping_row:mb-v1-to-svc-member`
- `architecture:DSGN-005-030:detail:01of05:table_row:openshift-monitoring-prometheus-pvc-prometheus-k8s-0`
- `cicd:DSGN-005-401:default:none:step:build-image`

Implementation note:

- the storage/URL-safe `chunk_id` may be shortened internally for filesystem/runtime constraints,
- but the semantic shape above is the design-level source of truth,
- `native_id`, `bundle_id`, `chunk_kind`, `variant`, and `part_no/part_total` must preserve that structure.

## 7. layout_type -> chunk_kind mapping

### flow / swimlane_flow

- 1 parent `design_summary`
- many child `step`
- optional `actor_lane_summary`

Use for:

- `DSGN-005-202`
- `DSGN-005-401`
- similar numbered process slides

### mapping_2col

- 1 parent `design_summary`
- many child `mapping_row`

Use for:

- `DSGN-005-209`

### table / table_with_notes

- 1 parent `design_summary`
- optional `part_summary`
- many child `table_row`
- optional `table_group_summary`

Use for:

- `DSGN-005-030`

### component_diagram / network_topology

- 1 parent `design_summary`
- a few child `component_group`

Do **not** split every icon into its own chunk.

### comparison

- 1 parent `design_summary`
- 2 child `comparison_side`
- 1 child `comparison_delta`

### narrative

- `section_summary`
- child `narrative_section` or `note`

Use for completion reports.

## 8. Image Attachment Policy

Images are supporting assets, not the main chunk body.

Attachment model:

```json
{
  "attachment_id": "att_03",
  "type": "image_shape",
  "asset_path": "attachments/ocp/slide_25/att_03.png",
  "zone_id": "z032",
  "bbox_norm": [0.58, 0.20, 0.92, 0.76],
  "role": "diagram",
  "caption_text": "",
  "visual_summary": "OpenShift 노드 또는 구성 요소 연결을 보여주는 그림",
  "searchable": true,
  "confidence": 0.87
}
```

Rules:

- save image shapes as attachments
- keep full-slide render only as QA/debug support
- connect attachments to `zone_id`
- allow short searchable visual summary

## 9. Retrieval Strategy

Hybrid retrieval remains required.

The corpus contains many exact anchors:

- `DSGN-005-209`
- `/mb/v1/*`
- `svc-member`
- `komsco-storage-class`
- `prometheus-pvc-prometheus-k8s-0`
- IPs, hostnames, PVC names, route prefixes

Therefore:

- dense-only is insufficient
- sparse/BM25 support is mandatory

Search layering:

- `dense_text` for semantic retrieval
- `sparse_text` for exact anchor retrieval
- `visual_text` for image-assisted support
- `facets` for precise filtering

## 10. Course Chat

`/course/chat` must eventually use:

- `course_pbs_ko`
- `gold_manualbook_ko`

in parallel search, then merge and rerank.

When a child chunk is hit, answer assembly should also consider:

- its parent chunk
- nearby sibling chunks in the same bundle

This bundle-aware behavior is important for slides like:

- flow diagrams
- 2-column mappings
- large tables with multiple rows

## 11. Current Implementation Reality

As of now:

- the pipeline exists and runs
- all 12 decks are classified
- chunk + manifest outputs are generated
- `slide_graph_v1` artifacts are persisted
- course APIs exist
- `/course` UI exists
- stage-level guided learning routes now exist
- route overrides can be curated in `manifests/course_learning_routes_overrides.json`
- image attachments are annotated through the company VLM endpoint instead of full-slide OCR fallback

But the parser quality is still transitional.

Current implementation already aligns with:

- text-first chunking
- image attachments
- parent/child model
- relative-path persistence
- bundle-aware retrieval assembly
- route-first learning UX on top of generated chunks

Still in progress:

- deeper layout-aware parser quality for all slide families
- curated review approval beyond heuristic route/review generation
- final visual QA / polish for the course UI

Current dataset status is best described as:

- **gold-ready**, not fully gold

Why:

- generated chunks, routes, and attachment annotations are now strong enough to support a guided learning experience
- but final gold quality still requires human review and approval of route order, review statuses, and selected attachment descriptions

## 12. Immediate Next Steps

1. Keep refining layout-aware parser behavior where fallback native IDs still appear
2. Promote heuristic guided routes into explicitly reviewed gold routes
3. Stabilize `approved / needs_review` review metadata and expose it consistently in UI/API
4. Improve attachment summaries that still contain low-value OCR noise
5. Run final Playwright visual QA for timeline, stage, and chunk screens

## 13. Immediate Corrections Adopted From Evaluation

The following items are now part of the active design, not optional follow-up notes.

### 13.1 Path normalization is mandatory

Persisted course artifacts must not store developer-machine absolute paths such as:

- `C:\Users\...`
- local OneDrive paths
- local tmp/render paths

This applies to:

- `source_pptx`
- `slide_refs.pptx`
- `slide_refs.png_path`
- `image_attachments.asset_path`
- any similar persisted file reference

Design rule:

- persisted JSON stores only project-relative or course-relative paths
- runtime may resolve them to real local paths internally
- API responses must avoid leaking machine-local absolute paths

### 13.2 Title extraction must be treated as a first-class parser requirement

`Slide 7`, `Slide 11` style fallback titles are acceptable only as a last resort.

Parsers should prefer, in order:

1. semantic title zones
2. design/test identifiers with nearby labels
3. structured table/mapping headers
4. slide placeholder title only when nothing else exists

### 13.3 slide_graph and chunk responsibilities must remain separated

`slide_graph_v1` is the semantic intermediate representation.

`ppt_chunk_v1` is the retrieval representation.

This means:

- chunk payloads should not become a second copy of the full slide graph
- only the fields required for retrieval, display, and provenance should remain in chunks
- heavy/debug-only graph detail must stay in the slide graph layer

### 13.4 Parent/child chunk emission must stay conservative

Parent chunks are the default exploration unit.

Child chunks should be emitted only when they materially improve:

- exact retrieval
- semantic drilldown
- visual explanation

Do not emit child chunks just because a slide exists.

### 13.5 Retrieval quality must balance dense and exact-anchor matching

The corpus contains many exact operational anchors:

- design ids
- route prefixes
- service names
- PVC names
- storage classes
- IPs / hostnames

Therefore:

- dense retrieval alone is not enough
- sparse/BM25-friendly index text remains required
- official-doc matching should prefer embedding/Qdrant-backed matching where possible

### 13.6 Global reading order must not be the parser objective

The parser must not try to flatten each slide into one universal top-left to bottom-right reading order.

Required interpretation order:

1. explicit numbered steps / step markers
2. table row and column structure
3. same-row or same-column semantic pairing
4. nearby captions / notes / legends
5. geometric fallback order only as the last resort

This especially applies to:

- service flow diagrams
- two-column URL-to-service mapping slides
- large PVC / configuration tables
- CICD lane or process diagrams

### 13.7 Group shapes and discarded zones are first-class semantic signals

The parser must treat group shapes as semantic candidates before flattening all children.

Required rules:

- evaluate a group shape as a possible zone boundary first
- only flatten inside the group after zone intent is understood
- preserve repeated headers, footers, and decorative labels in `discarded_zones`
- record the discard reason so missing-search debugging remains possible

This is required to avoid:

- ghost text from off-canvas or decorative shapes
- repeated deck boilerplate polluting retrieval text
- broken relation extraction in grouped diagrams

### 13.8 Bundle-aware retrieval assembly is part of the target behavior

When retrieval lands on a child chunk, answer assembly should expand around the bundle.

Default assembly policy:

- include the matched child chunk
- include its parent chunk
- include one or two nearby sibling chunks from the same bundle when they add context

This rule matters for:

- `step` chunks in flow slides
- `mapping_row` chunks in URL/service mapping slides
- `table_row` chunks in large infrastructure tables

### 13.9 search text and facets must be populated intentionally

Chunk generation must separate human-readable content from retrieval-oriented text.

Minimum required behavior:

- `content.body_md` remains the readable primary body
- `index_texts.dense_text` carries natural-language retrieval context
- `index_texts.sparse_text` carries exact anchors such as IDs, paths, service names, PVC names, hostnames, and IPs
- `index_texts.visual_text` carries short searchable visual context
- `facets` exposes exact filterable anchors without forcing full-text search
