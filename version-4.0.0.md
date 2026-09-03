Version 4.0.0 release notes

Highlights:

    Unified ZATCA XML and QR workflow: Sales Invoices use one ZATCA generation path,
    retain one QR attachment, and support local QR regeneration without contacting ZATCA.

    Legacy compatibility: Migrations detect available field names, repair stale fetch mappings,
    normalize layouts, and preserve existing transaction values across ERPNext versions.

    Customer and address validation: Configurable Saudi B2B buyer-ID, TIN/Tax ID, UNN (700),
    National Address, and Arabic/English address rules with translated messages.

    Advance-payment workflow: Payment Entries can create linked ADV- invoices and final invoices
    can safely allocate submitted advances with VAT, account, currency, and credit-note checks.

    Correct machine timestamps: XML IssueTime and QR Tag 3 preserve 24-hour HH:mm:ss values.

Hard Disk Efficiency: 

    The single-output policy minimizes redundant files while preserving the authoritative XML and QR payload.

    Improved Performance: Faster XML generation and reduced I/O operations on the server.

Impact:

    Users receive a cleaner file structure with one authoritative XML/QR output per invoice.

    Improved server storage management, especially for high-volume invoice generation.

Upgrade Notes:

    Run the standard site migration after updating:

        bench --site yoursite.example migrate
        bench restart

    Existing sites retain their transaction data; compatibility migrations only repair metadata and settings where needed.
