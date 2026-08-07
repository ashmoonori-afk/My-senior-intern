# My Senior Intern

My Senior Intern is a local document-work assistant for Windows and macOS. It is designed to organize office documents while the user is away, prepare evidence-linked drafts for review, and summarize the work in a Morning Memo.

## Product boundary

This is not a general-purpose autonomous agent. It only scans folders the user explicitly selects. User-approved deterministic rules take precedence over AI suggestions.

## Safety principles

- User documents are never deleted, trashed, overwritten, or edited.
- Automatic moves are limited to verified same-filesystem, no-replace atomic renames.
- Cross-volume, network, cloud-synchronized, linked, uncertain, locked, or conflicting files are not moved automatically.
- Every move is journaled, verified, auditable, and eligible for collision-safe undo when the file remains unchanged.
- The selected AI provider receives only the minimum approved information.
- The AI cannot access paths, filesystems, shells, browsers, email, tools, or move execution.
- Document content, metadata, filenames, OCR output, comments, notes, links, and provider responses are always treated as untrusted data.
- Provider failures never cause a silent switch to another provider.
- Credentials are stored through Windows Credential Manager or macOS Keychain, not plaintext files.

## Planned full-suite capabilities

- Korean-first guided TUI for onboarding, review, settings, and undo
- Separate scheduled headless worker
- DOCX, XLSX, PDF, CSV, and PPTX extraction
- Korean and English OCR
- Easy, natural-language, and advanced deterministic rules
- OAuth, SDK/API, installed CLI, enterprise gateway, and compatible custom API connections
- Evidence-based document-need proposals and risk-tiered editable drafts
- Approval-gated standard-document candidates and templates
- TUI Morning Summary and TXT Morning Memo
- Windows and macOS packaged applications with equal supported functionality

## Development status

The repository is being delivered in verified atomic waves. A feature is not considered complete until its failing-first proof, strict diagnostics, focused tests, full regression checks where applicable, and matching real-surface QA have passed on the supported operating systems.

Do not use unreleased builds on irreplaceable documents.
