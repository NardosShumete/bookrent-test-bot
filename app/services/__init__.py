"""Business logic service layer for BookRent Bot."""

from app.services.audit import record_audit_log
from app.services.book_catalog import (
    create_book,
    get_book_inventory_details,
    get_overall_inventory_summary,
    receive_stock_for_isbn,
    search_books,
)
from app.services.customer import (
    approve_customer,
    get_customer_by_telegram_id,
    get_customer_language,
    get_pending_customers,
    get_rejected_customers,
    is_owner,
    normalize_phone_number,
    reapprove_customer,
    register_customer,
    reject_customer,
    require_owner,
    set_customer_language,
    submit_customer_registration,
)
from app.services.inventory import (
    get_available_copies,
    get_inventory_counts,
    record_received_copies,
    transition_copy_status,
)
from app.services.isbn import (
    clean_isbn,
    convert_isbn10_to_isbn13,
    normalize_isbn,
    validate_isbn10,
    validate_isbn13,
)
from app.services.ledger import (
    get_customer_collateral_balance,
    get_rental_ledger_summary,
    record_ledger_entry,
)
from app.services.rental import (
    approve_extension,
    approve_rental_extension,
    confirm_rental_return,
    create_rental,
    get_customer_active_rentals,
    get_pending_extension_requests,
    get_rental_financial_reconciliation,
    reject_extension,
    reject_rental_extension,
    request_extension,
    return_rental,
    submit_extension_request,
    verify_and_approve_extension,
    verify_extension_payment,
)

from app.services.due_date import (
    calculate_due_date,
    calculate_extension_due_date,
    get_rental_timezone,
)
from app.services.notification import (
    announce_new_stock,
    notify_admins,
    notify_admins_sync,
    notify_customer,
    notify_customer_sync,
)
from app.services.overdue import (
    calculate_overdue_days_and_dates,
    get_all_overdue_rentals,
    get_rental_overdue_summary,
    process_overdue_rentals,
    send_overdue_notifications,
)
from app.services.rental_request import (
    approve_rental_request,
    cancel_rental_request,
    confirm_physical_handover,
    get_active_rental_requests,
    record_non_cash_guarantee,
    record_payment_verification,
    reject_rental_request,
    submit_rental_request,
)


__all__ = [
    # Customer & Auth
    "is_owner",
    "require_owner",
    "register_customer",
    "get_customer_by_telegram_id",
    "get_pending_customers",
    "get_rejected_customers",
    "approve_customer",
    "reject_customer",
    "reapprove_customer",
    "get_customer_language",
    "set_customer_language",
    "normalize_phone_number",
    "submit_customer_registration",
    # Book Catalog & Search
    "create_book",
    "receive_stock_for_isbn",
    "search_books",
    "get_book_inventory_details",
    "get_overall_inventory_summary",
    # ISBN
    "clean_isbn",
    "normalize_isbn",
    "validate_isbn10",
    "validate_isbn13",
    "convert_isbn10_to_isbn13",
    # Inventory
    "record_received_copies",
    "transition_copy_status",
    "get_inventory_counts",
    "get_available_copies",
    # Rental
    "create_rental",
    "request_extension",
    "approve_extension",
    "reject_extension",
    "return_rental",
    # Phase 5 Extensions & Returns
    "submit_extension_request",
    "verify_extension_payment",
    "approve_rental_extension",
    "verify_and_approve_extension",
    "reject_rental_extension",
    "confirm_rental_return",
    "get_rental_financial_reconciliation",
    "get_customer_active_rentals",
    "get_pending_extension_requests",
    # Phase 4 & 5 Due Date & Rental Requests
    "calculate_due_date",
    "calculate_extension_due_date",
    "get_rental_timezone",
    "submit_rental_request",
    "approve_rental_request",
    "reject_rental_request",
    "cancel_rental_request",
    "record_payment_verification",
    "record_non_cash_guarantee",
    "confirm_physical_handover",
    "get_active_rental_requests",
    # Phase 5 Overdue
    "calculate_overdue_days_and_dates",
    "process_overdue_rentals",
    "get_rental_overdue_summary",
    "get_all_overdue_rentals",
    "send_overdue_notifications",
    # Phase 8 Notifications
    "notify_customer",
    "notify_admins",
    "notify_customer_sync",
    "notify_admins_sync",
    "announce_new_stock",
    # Ledger
    "record_ledger_entry",
    "get_customer_collateral_balance",
    "get_rental_ledger_summary",
    # Audit
    "record_audit_log",
]


