"""Centralized localization strings and keyboard builders for Amharic and English."""

from typing import Any, Dict, List, Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = ("en", "am")

TRANSLATIONS: Dict[str, Dict[str, str]] = {
    # --------------------------------------------------------------------------
    # Language Selection
    # --------------------------------------------------------------------------
    "lang_prompt": {
        "en": "🇬🇧 Welcome to BookRent! Please choose your language to continue.\n\n"
              "🇪🇹 ወደ BookRent እንኳን በደህና መጡ! ለመቀጠል ቋንቋዎን ይምረጡ።",
        "am": "🇪🇹 ወደ BookRent እንኳን በደህና መጡ! ለመቀጠል ቋንቋዎን ይምረጡ።\n\n"
              "🇬🇧 Welcome to BookRent! Please choose your language to continue.",
    },
    "lang_selected_en": {
        "en": "🇬🇧 Language set to <b>English</b>. Welcome to BookRent!",
        "am": "🇬🇧 Language set to <b>English</b>. Welcome to BookRent!",
    },
    "lang_selected_am": {
        "en": "🇪🇹 ቋንቋዎ ወደ <b>አማርኛ</b> ተቀናብሯል። እንኳን ወደ BookRent በደህና መጡ!",
        "am": "🇪🇹 ቋንቋዎ ወደ <b>አማርኛ</b> ተቀናብሯል። እንኳን ወደ BookRent በደህና መጡ!",
    },
    "choose_language": {
        "en": "Please choose your preferred language:",
        "am": "እባክዎን የሚፈልጉትን ቋንቋ ይምረጡ፦",
    },

    # --------------------------------------------------------------------------
    # Customer Status & Welcome
    # --------------------------------------------------------------------------
    "welcome_admin": {
        "en": "👑 <b>Welcome, Owner {name}!</b>\n\n"
              "BookRent Bot Owner Console is ready. Available management commands:\n"
              "• /pending - View and review pending customer registrations\n"
              "• /addbook - Add new book title\n"
              "• /requests - View pending/active rental requests\n"
              "• /inventory - View inventory breakdown\n\n"
              "Use the buttons below or type commands to manage the library.",
        "am": "👑 <b>እንኳን በደህና መጡ፣ አስተዳዳሪ {name}!</b>\n\n"
              "የBookRent ቦት የአስተዳዳሪ መቆጣጠሪያ (Owner Console) ዝግጁ ነው።\n"
              "• /pending - በመጠባበቅ ላይ ያሉ ደንበኞችን ለማየት\n"
              "• /addbook - አዲስ መጽሐፍ ለማስገባት\n"
              "• /requests - የኪራይ ጥያቄዎችን ለማየት\n\n"
              "ለመጠቀም ከታች ያሉትን ቁልፎች ወይም ትዕዛዞች ይጠቀሙ።",
    },
    "welcome_approved": {
        "en": "👋 Welcome back, <b>{name}</b>!\n\n"
              "Your account is <b>APPROVED</b> and active. Explore our library services:\n"
              "• /search &lt;query&gt; - Search books by title, author, category, or ISBN\n"
              "• /books - Browse all available books in our catalogue\n"
              "• /rent &lt;book_id&gt; [guarantee note] - Request to rent a book\n"
              "• /myrentals - View your active rentals and due dates\n"
              "• /extend &lt;rental_id&gt; - Request a 5-calendar-day extension (10 ETB)\n"
              "• /myextensions - Check status of your extension requests\n"
              "• /overdue - View overdue rentals and late charges (5 ETB/day)\n\n"
              "Use the buttons below to navigate quickly.",
        "am": "👋 እንኳን ደህና መጡ <b>{name}</b>!\n\n"
              "መለያዎ <b>የጸደቀ</b> እና ንቁ ነው። ከታች ያሉትን ቁልፎች በመጫን ወይም ትዕዛዞችን በመላክ ይጠቀሙ፦\n"
              "• /search &lt;ቃል&gt; - በመጽሐፍ ርዕስ፣ በደራሲ ወይም በISBN ይፈልጉ\n"
              "• /books - ያሉትን መጻሕፍት በሙሉ ይመልከቱ\n"
              "• /rent &lt;የመጽሐፍ_ቁጥር&gt; [ዋስትና] - የኪራይ ጥያቄ ያቅርቡ\n"
              "• /myrentals - ንቁ ኪራዮችንና የመመለሻ ቀንን ይመልከቱ\n"
              "• /extend &lt;የኪራይ_ቁጥር&gt; - የ5 ቀን ማራዘሚያ ይጠይቁ (10 ብር)\n"
              "• /myextensions - የማራዘሚያ ሁኔታዎችን ይከታተሉ\n"
              "• /overdue - የዘገዩ ኪራዮችንና ክፍያዎችን ይመልከቱ\n\n"
              "በፍጥነት ለመጠቀም ከታች ያሉትን ቁልፎች ይጫኑ።",
    },
    "welcome_pending": {
        "en": "👋 Hello, <b>{name}</b>!\n\n"
              "Your account registration is currently <b>PENDING</b> owner review.\n\n"
              "⏳ You will receive access to borrow books once an administrator approves your account. Thank you for your patience!",
        "am": "👋 ሰላም <b>{name}</b>!\n\n"
              "የመለያዎ ምዝገባ በአስተዳዳሪው <b>በመጠባበቅ ላይ</b> ነው።\n\n"
              "⏳ አስተዳዳሪው መለያዎን እንዳጸደቀ መጻሕፍትን መዋስ ይችላሉ። በትዕግስት ስለጠበቁ እናመሰግናለን!",
    },
    "welcome_rejected": {
        "en": "👋 Hello, <b>{name}</b>.\n\n"
              "Your account registration was <b>REJECTED</b> by the library owner.\n"
              "{reason_info}\n"
              "ℹ️ If you believe this was an error, please contact the library owner for assistance.",
        "am": "👋 ሰላም <b>{name}</b>።\n\n"
              "የመለያዎ ምዝገባ በመጽሐፍ አስተዳዳሪው <b>ተቀባይነት አላገኘም</b>።\n"
              "{reason_info}\n"
              "ℹ️ ስህተት ነው ብለው ካሰቡ እባክዎን የመጽሐፍ አስተዳዳሪውን ያነጋግሩ።",
    },
    "rejection_reason_label": {
        "en": "• Reason: <i>{reason}</i>\n",
        "am": "• ምክንያት፦ <i>{reason}</i>\n",
    },
    "rejection_no_reason": {
        "en": "",
        "am": "",
    },
    "welcome_other": {
        "en": "👋 Hello, <b>{name}</b>.\n\n"
              "Your account status is currently <b>{status}</b>. Please contact the library owner for further assistance.",
        "am": "👋 ሰላም <b>{name}</b>።\n\n"
              "የመለያዎ ሁኔታ በአሁን ወቅት <b>{status}</b> ነው። እባክዎን የመጽሐፍ አስተዳዳሪውን ያነጋግሩ።",
    },

    # --------------------------------------------------------------------------
    # Customer Menu Buttons
    # --------------------------------------------------------------------------
    "btn_cust_search": {
        "en": "🔎 Search Books",
        "am": "🔎 መጻሕፍት ፈልግ",
    },
    "btn_cust_browse": {
        "en": "📚 Browse Books",
        "am": "📚 መጻሕፍትን ተመልከት",
    },
    "btn_cust_rent": {
        "en": "📖 Request a Rental",
        "am": "📖 የኪራይ ጥያቄ አቅርብ",
    },
    "btn_cust_myrentals": {
        "en": "📋 My Rentals",
        "am": "📋 ኪራዮቼ",
    },
    "btn_cust_extensions": {
        "en": "⏳ My Extensions",
        "am": "⏳ የማራዘሚያ ጥያቄዎቼ",
    },
    "btn_change_language": {
        "en": "🌐 Change Language",
        "am": "🌐 ቋንቋ ቀይር",
    },
    "btn_cust_help": {
        "en": "❓ Help",
        "am": "❓ እገዛ",
    },

    # --------------------------------------------------------------------------
    # Customer Action Explanations
    # --------------------------------------------------------------------------
    "desc_cust_search": {
        "en": "🔎 <b>Search Books</b>\n\n"
              "Search by book title, author, ISBN, or category. Choose a book to view its details and availability.\n\n"
              "💡 <i>How to use:</i> Type <code>/search &lt;query&gt;</code>\n"
              "<i>Example:</i> <code>/search Python</code> or <code>/search Kandel</code>",
        "am": "🔎 <b>መጻሕፍት ፈልግ</b>\n\n"
              "በመጽሐፍ ርዕስ፣ በደራሲ፣ በISBN ወይም በምድብ መፈለግ ይችላሉ። ዝርዝሩንና ተገኝነቱን ለማየት መጽሐፉን ይምረጡ።\n\n"
              "💡 <i>አጠቃቀም፦</i> <code>/search &lt;የሚፈልጉት ቃል&gt;</code> ይላኩ\n"
              "<i>ምሳሌ፦</i> <code>/search Python</code> ወይም <code>/search ታሪክ</code>",
    },
    "desc_cust_browse": {
        "en": "📚 <b>Browse Catalogue</b>\n\n"
              "Browse our library catalogue to discover available titles, authors, and rental prices.\n\n"
              "💡 <i>How to use:</i> Type <code>/books</code> to view all active books.",
        "am": "📚 <b>ካታሎግ ተመልከት</b>\n\n"
              "የቤተ-መጽሐፍቱን ሙሉ ካታሎግ፣ ደራሲያንንና የኪራይ ዋጋን ለመመልከት ይጠቀሙበት።\n\n"
              "💡 <i>አጠቃቀም፦</i> ሁሉንም መጻሕፍት ለማየት <code>/books</code> ብለው ይላኩ።",
    },
    "desc_cust_rent": {
        "en": "📖 <b>Request a Rental</b>\n\n"
              "Select an available book to submit a rental request. The owner must approve your request before the rental can proceed.\n\n"
              "💡 <i>How to use:</i> Send <code>/rent &lt;book_id&gt; [guarantee note]</code>\n"
              "<i>Example:</i> <code>/rent 1 Student ID 12345</code>",
        "am": "📖 <b>የኪራይ ጥያቄ አቅርብ</b>\n\n"
              "የኪራይ ጥያቄ ለማቅረብ ያለ መጽሐፍ ይምረጡ። ኪራዩ ከመቀጠሉ በፊት የመጽሐፍ አስተዳዳሪው ማጽደቅ አለበት።\n\n"
              "💡 <i>አጠቃቀም፦</i> <code>/rent &lt;የመጽሐፍ_ቁጥር&gt; [የዋስትና ማስታወሻ]</code> ይላኩ\n"
              "<i>ምሳሌ፦</i> <code>/rent 1 የተማሪ መታወቂያ 12345</code>",
    },
    "desc_cust_myrentals": {
        "en": "📋 <b>My Rentals</b>\n\n"
              "View your active book rentals, upcoming return due dates, and overdue status.\n\n"
              "💡 <i>How to use:</i> Type <code>/myrentals</code> or <code>/overdue</code>.",
        "am": "📋 <b>ኪራዮቼ</b>\n\n"
              "የተዋሷቸውን ንቁ መጻሕፍት፣ የመመለሻ ቀነ-ገደብና የዘገየበትን ሁኔታ ይመልከቱ።\n\n"
              "💡 <i>አጠቃቀም፦</i> <code>/myrentals</code> ወይም <code>/overdue</code> ብለው ይላኩ።",
    },
    "desc_cust_extensions": {
        "en": "⏳ <b>Rental Extensions</b>\n\n"
              "• Duration: <b>5 calendar days</b> per extension\n"
              "• Fee: Fixed <b>10 ETB</b>\n"
              "• Note: Overdue late charge is 5 ETB/day if not returned on time.\n"
              "• Extensions require manual fee verification and owner approval.\n\n"
              "💡 <i>How to use:</i> Send <code>/extend &lt;rental_id&gt;</code> to request, and <code>/myextensions</code> to track status.",
        "am": "⏳ <b>የኪራይ ማራዘሚያ</b>\n\n"
              "• የጊዜ ርዝማኔ፦ <b>5 የቀን መቁጠሪያ ቀናት</b>\n"
              "• ክፍያ፦ ቋሚ <b>10 የኢትዮጵያ ብር</b>\n"
              "• ማሳሰቢያ፦ መጽሐፉ በሰዓቱ ካልተመለሰ በቀን 5 ብር ቅጣት ይታሰባል።\n"
              "• ማራዘሚያው የክፍያ ማረጋገጫና የአስተዳዳሪ ፈቃድ ይፈልጋል።\n\n"
              "💡 <i>አጠቃቀም፦</i> ለመጠየቅ <code>/extend &lt;የኪራይ_ቁጥር&gt;</code>፣ ሁኔታውን ለማየት ደግሞ <code>/myextensions</code> ይላኩ።",
    },
    "desc_cust_help": {
        "en": "❓ <b>BookRent Bot Help Guide</b>\n\n"
              "Use the menu buttons below to navigate quickly, or use the following commands:\n\n"
              "• /start — Register or check account status\n"
              "• /search &lt;query&gt; — Search catalogued books\n"
              "• /books — Browse available titles\n"
              "• /rent &lt;book_id&gt; [guarantee note] — Request to rent a book\n"
              "• /myrentals — View active rentals & due dates\n"
              "• /extend &lt;rental_id&gt; — Request a 5-day extension (10 ETB)\n"
              "• /myextensions — Check extension request status\n"
              "• /overdue — View overdue rentals and charges\n"
              "• /language — Change English/Amharic preference\n"
              "• /help — View this help guide",
        "am": "❓ <b>የBookRent ቦት አጋዥ መመሪያ</b>\n\n"
              "በፍጥነት ለመጠቀም ከታች ያሉትን ቁልፎች ይጫኑ ወይም የሚከተሉትን ትዕዛዞች ይጠቀሙ፦\n\n"
              "• /start — መለያ ለመመዝገብ ወይም ሁኔታውን ለማየት\n"
              "• /search &lt;ቃል&gt; — መጻሕፍትን ለመፈለግ\n"
              "• /books — ያሉትን መጻሕፍት ለመመልከት\n"
              "• /rent &lt;የመጽሐፍ_ቁጥር&gt; [ማስታወሻ] — የኪራይ ጥያቄ ለማቅረብ\n"
              "• /myrentals — ንቁ ኪራዮችንና የመመለሻ ቀንን ለማየት\n"
              "• /extend &lt;የኪራይ_ቁጥር&gt; — የ5 ቀን ማራዘሚያ ለመጠየቅ (10 ብር)\n"
              "• /myextensions — የማራዘሚያ ጥያቄ ሁኔታን ለመከታተል\n"
              "• /overdue — የዘገዩ ኪራዮችንና ክፍያዎችን ለማየት\n"
              "• /language — ቋንቋ ለመቀየር\n"
              "• /help — ይህን አጋዥ መመሪያ ለማየት",
    },

    # --------------------------------------------------------------------------
    # Admin Menu Buttons & Guided Book Workflows
    # --------------------------------------------------------------------------
    "btn_admin_add_book": {
        "en": "➕ Add New Book",
        "am": "➕ አዲስ መጽሐፍ ጨምር",
    },
    "btn_admin_pending": {
        "en": "👥 Pending Customers",
        "am": "👥 በመጠባበቅ ላይ ያሉ ደንበኞች",
    },
    "btn_admin_rejected": {
        "en": "🚫 Rejected Customers",
        "am": "🚫 የተከለከሉ ደንበኞች",
    },
    "btn_admin_books": {
        "en": "📚 Manage Books & Stock",
        "am": "📚 መጻሕፍትና ክምችት ማስተዳደር",
    },
    "btn_admin_requests": {
        "en": "📝 Rental Requests",
        "am": "📝 የኪራይ ጥያቄዎች",
    },
    "btn_admin_payments": {
        "en": "💳 Payment Verification",
        "am": "💳 የክፍያ ማረጋገጫ",
    },
    "btn_admin_extensions": {
        "en": "⏳ Extension Requests",
        "am": "⏳ የማራዘሚያ ጥያቄዎች",
    },
    "btn_admin_overdue": {
        "en": "⚠️ Overdue Rentals",
        "am": "⚠️ ጊዜያቸው ያለፈባቸው",
    },
    "btn_admin_returns": {
        "en": "📦 Confirm Returns",
        "am": "📦 የመመለሻ ማረጋገጫ",
    },
    "btn_admin_inventory": {
        "en": "📊 Inventory Summary",
        "am": "📊 የክምችት ማጠቃለያ",
    },
    "btn_admin_help": {
        "en": "❓ Admin Help",
        "am": "❓ የአስተዳዳሪ እገዛ",
    },
    "btn_skip": {
        "en": "⏭️ Skip",
        "am": "⏭️ እለፍ",
    },
    "btn_confirm_save": {
        "en": "✅ Confirm & Save",
        "am": "✅ አረጋግጥና አስቀምጥ",
    },
    "btn_add_copies": {
        "en": "➕ Add Physical Copies",
        "am": "➕ ቅጂዎችን ጨምር",
    },
    "btn_req_this_book": {
        "en": "📖 Request This Book",
        "am": "📖 ይህን መጽሐፍ ተዋስ",
    },
    "btn_out_of_stock": {
        "en": "🔴 Out of Stock",
        "am": "🔴 በአሁን ወቅት አልቋል",
    },
    "btn_cash_collat": {
        "en": "💵 Cash Collateral",
        "am": "💵 የጥሬ ገንዘብ ዋስትና",
    },
    "btn_guarantee_collat": {
        "en": "🪪 ID / Document Guarantee",
        "am": "🪪 የመታወቂያ/ሰነድ ዋስትና",
    },
    "btn_submit_request": {
        "en": "✅ Submit Rental Request",
        "am": "✅ የኪራይ ጥያቄውን ላክ",
    },
    "btn_search_title": {
        "en": "🔤 Search by Title",
        "am": "🔤 በርዕስ ፈልግ",
    },
    "btn_search_author": {
        "en": "✍️ Search by Author",
        "am": "✍️ በደራሲ ፈልግ",
    },
    "btn_search_category": {
        "en": "🏷️ Search by Category",
        "am": "🏷️ በምድብ ፈልግ",
    },
    "btn_search_browse": {
        "en": "📚 Browse All Books",
        "am": "📚 ሁሉንም ተመልከት",
    },

    # --------------------------------------------------------------------------
    # Guided Add Book Flow Templates
    # --------------------------------------------------------------------------
    "add_book_step_isbn": {
        "en": "📖 <b>Step 1 of 6: Book ISBN</b>\n\n"
              "Please enter the 10 or 13-digit International Standard Book Number (ISBN).\n"
              "<i>Example:</i> <code>978-0-306-40615-7</code> or <code>0306406152</code>\n\n"
              "ℹ️ <i>What is an ISBN?</i> It is the unique identification number printed on the back cover of the book above the barcode.\n\n"
              "💡 <i>Tip: Experienced users can also use:</i>\n"
              "<code>/addbook &lt;isbn&gt; | &lt;title&gt; | &lt;author&gt; | &lt;price&gt;</code> and <code>/receive &lt;isbn&gt; &lt;quantity&gt;</code>",
        "am": "📖 <b>ደረጃ 1 ከ 6፦ የመጽሐፉ ISBN</b>\n\n"
              "እባክዎን ባለ 10 ወይም 13 አሃዝ የISBN ቁጥር ያስገቡ።\n"
              "<i>ምሳሌ፦</i> <code>978-0-306-40615-7</code> ወይም <code>0306406152</code>\n\n"
              "ℹ️ <i>ISBN ምንድን ነው?</i> በመጽሐፉ የጀርባ ሽፋን ላይ ከባርኮዱ በላይ የሚገኝ ልዩ መለያ ቁጥር ነው።\n\n"
              "💡 <i>ፈጣን ትዕዛዝ መጠቀም ለሚፈልጉ፦</i>\n"
              "<code>/addbook &lt;isbn&gt; | &lt;ርዕስ&gt; | &lt;ደራሲ&gt; | &lt;ዋጋ&gt;</code> እና <code>/receive &lt;isbn&gt; &lt;ብዛት&gt;</code>",
    },
    "add_book_step_title": {
        "en": "📖 <b>Step 2 of 6: Book Title</b>\n\n"
              "Please enter the full title of the book.\n"
              "<i>Example:</i> <code>Principles of Neural Science</code>",
        "am": "📖 <b>ደረጃ 2 ከ 6፦ የመጽሐፉ ርዕስ</b>\n\n"
              "እባክዎን የመጽሐፉን ሙሉ ርዕስ ያስገቡ።\n"
              "<i>ምሳሌ፦</i> <code>Principles of Neural Science</code>",
    },
    "add_book_step_author": {
        "en": "✍️ <b>Step 3 of 6: Author</b>\n\n"
              "Please enter the author or primary editor name.\n"
              "<i>Example:</i> <code>Eric R. Kandel</code>",
        "am": "✍️ <b>ደረጃ 3 ከ 6፦ ደራሲ</b>\n\n"
              "እባክዎን የደራሲውን ወይም ዋና አዘጋጁን ስም ያስገቡ።\n"
              "<i>ምሳሌ፦</i> <code>Eric R. Kandel</code>",
    },
    "add_book_step_price": {
        "en": "💵 <b>Step 4 of 6: Rental Fee (ETB)</b>\n\n"
              "Please enter the standard 10-day rental price in Ethiopian Birr.\n"
              "<i>Example:</i> <code>15.00</code> or <code>20</code>",
        "am": "💵 <b>ደረጃ 4 ከ 6፦ የኪራይ ዋጋ (ብር)</b>\n\n"
              "እባክዎን የ10 ቀናት የኪራይ ዋጋ በኢትዮጵያ ብር ያስገቡ።\n"
              "<i>ምሳሌ፦</i> <code>15.00</code> ወይም <code>20</code>",
    },
    "add_book_step_metadata": {
        "en": "📚 <b>Step 5 of 6: Optional Details</b>\n\n"
              "Optionally enter <b>Category</b>, <b>Page Count</b>, and <b>Description</b> separated by <code>|</code>, or tap <b>Skip</b>.\n"
              "<i>Example:</i> <code>Science | 1414 | Neurobiology reference</code>",
        "am": "📚 <b>ደረጃ 5 ከ 6፦ ተጨማሪ መረጃዎች</b>\n\n"
              "ምድብ፣ የገጽ ብዛትና መግለጫ በ <code>|</code> ለይተው ማስገባት ይችላሉ ወይም <b>እለፍ</b> የሚለውን ይጫኑ።\n"
              "<i>ምሳሌ፦</i> <code>Science | 1414 | የሳይንስ መጽሐፍ</code>",
    },
    "add_book_step_copies": {
        "en": "📦 <b>Step 6 of 6: Physical Copies Received</b>\n\n"
              "How many physical copies of this book did you receive to put on the shelf?\n"
              "<i>Example:</i> <code>3</code> (Must be at least 1)",
        "am": "📦 <b>ደረጃ 6 ከ 6፦ የተቀበሏቸው ቅጂዎች ብዛት</b>\n\n"
              "ለመደርደሪያ ስንት ቅጂዎችን ተቀብለዋል?\n"
              "<i>ምሳሌ፦</i> <code>3</code> (ቢያንስ 1 መሆን አለበት)",
    },
    "add_book_confirm_summary": {
        "en": "📋 <b>Review New Book & Stock:</b>\n\n"
              "• <b>Title:</b> <b>{title}</b>\n"
              "• <b>Author:</b> <b>{author}</b>\n"
              "• <b>ISBN:</b> <code>{isbn}</code>\n"
              "• <b>Rental Fee:</b> <b>{price} ETB</b> (10 days)\n"
              "• <b>Copies to Add:</b> <b>{quantity} ON_SHELF copies</b>\n"
              "• <b>Category:</b> {category}\n"
              "• <b>Pages:</b> {page_count}\n"
              "• <b>Description:</b> <i>{description}</i>\n\n"
              "Press <b>Confirm & Save</b> to catalogue this title and create physical copies.",
        "am": "📋 <b>አዲስ መጽሐፍና ክምችት ማጠቃለያ፦</b>\n\n"
              "• <b>ርዕስ፦</b> <b>{title}</b>\n"
              "• <b>ደራሲ፦</b> <b>{author}</b>\n"
              "• <b>ISBN፦</b> <code>{isbn}</code>\n"
              "• <b>የኪራይ ዋጋ፦</b> <b>{price} ብር</b> (10 ቀናት)\n"
              "• <b>የሚጨመሩ ቅጂዎች፦</b> <b>{quantity} ቅጂዎች</b>\n"
              "• <b>ምድብ፦</b> {category}\n"
              "• <b>ገጾች፦</b> {page_count}\n"
              "• <b>መግለጫ፦</b> <i>{description}</i>\n\n"
              "ለመመዝገብና ቅጂዎችን ለማስገባት <b>አረጋግጥና አስቀምጥ</b> የሚለውን ይጫኑ።",
    },
    "add_book_isbn_exists": {
        "en": "ℹ️ <b>Book Already Catalogued!</b>\n\n"
              "• <b>Title:</b> <i>{title}</i>\n"
              "• <b>Author:</b> {author}\n"
              "• <b>Current Stock:</b> <b>{available} available</b> ({total} total)\n\n"
              "This title is already in your catalogue. How many additional physical copies would you like to receive to put on shelf?",
        "am": "ℹ️ <b>መጽሐፉ ቀደም ሲል ተመዝግቧል!</b>\n\n"
              "• <b>ርዕስ፦</b> <i>{title}</i>\n"
              "• <b>ደራሲ፦</b> {author}\n"
              "• <b>ያለ ክምችት፦</b> <b>{available} ዝግጁ</b> ({total} ጠቅላላ)\n\n"
              "ይህ መጽሐፍ ቀደም ሲል በካታሎግ ውስጥ አለ። ለመደርደሪያ ስንት ተጨማሪ ቅጂዎችን መቀበል ይፈልጋሉ?",
    },
    "add_book_saved_success": {
        "en": "🎉 <b>Book & Stock Added Successfully!</b>\n\n"
              "• Title: <b>{title}</b>\n"
              "• Author: <b>{author}</b>\n"
              "• ISBN: <code>{isbn}</code>\n"
              "• Rental Fee: <b>{price} ETB</b>\n"
              "• Copies Added: <b>+{quantity}</b>\n"
              "• Total Available: <b>{available} copies (ON_SHELF)</b>\n"
              "• Generated Barcodes: {barcodes}",
        "am": "🎉 <b>መጽሐፍና ቅጂዎች በተሳካ ሁኔታ ተመዝግበዋል!</b>\n\n"
              "• ርዕስ፦ <b>{title}</b>\n"
              "• ደራሲ፦ <b>{author}</b>\n"
              "• ISBN፦ <code>{isbn}</code>\n"
              "• የኪራይ ዋጋ፦ <b>{price} ብር</b>\n"
              "• የተጨመሩ ቅጂዎች፦ <b>+{quantity}</b>\n"
              "• ዝግጁ የሆኑ ቅጂዎች፦ <b>{available} ቅጂዎች</b>\n"
              "• የተፈጠሩ ባርኮዶች፦ {barcodes}",
    },
    "add_book_cancelled": {
        "en": "❌ Add book operation cancelled. No changes were made.",
        "am": "❌ መጽሐፍ የማስገባት ሂደት ተሰርዟል። ምንም ለውጥ አልተደረገም።",
    },
    "add_book_isbn_required_note": {
        "en": "ℹ️ <b>Database Schema Limitation: ISBN is Mandatory</b>\n\n"
              "Under the current database schema, book cataloguing requires a mandatory, unique ISBN (<code>books.isbn NOT NULL UNIQUE</code>). Storing a missing or NULL ISBN is not permitted.\n\n"
              "💡 <i>Proposed Smallest Safe Change:</i>\n"
              "An Alembic database migration altering <code>books.isbn</code> to <code>nullable=True</code> (with a unique index on non-null values) is needed before books without ISBNs can be catalogued without generating fake data.\n\n"
              "Please enter a valid 10- or 13-digit ISBN (or tap <b>Cancel</b>):",
        "am": "ℹ️ <b>የዳታቤዝ ገደብ፦ ISBN የግድ ያስፈልጋል</b>\n\n"
              "በአሁኑ የዳታቤዝ መዋቅር መሠረት እያንዳንዱ መጽሐፍ የግድ ልዩ የISBN ቁጥር ሊኖረው ይገባል (<code>books.isbn NOT NULL UNIQUE</code>)። ያለ ISBN ማስመዝገብ አይቻልም።\n\n"
              "💡 <i>የሚመከር አስተማማኝ ለውጥ፦</i>\n"
              "ያለ ISBN ያሉ መጻሕፍትን ለማስመዝገብ በዳታቤዙ ላይ <code>books.isbn</code> ባዶ እንዲሆን (<code>nullable=True</code>) የአለምቢክ (Alembic) ማሻሻያ ማድረግ ያስፈልጋል።\n\n"
              "እባክዎን ትክክለኛ የISBN ቁጥር ያስገቡ (ወይም <b>ሰርዝ</b> የሚለውን ይጫኑ)፦",
    },
    "desc_admin_books": {
        "en": "📚 <b>Manage Books & Stock</b>\n\n"
              "• Add new book title: <code>/addbook &lt;isbn&gt; | &lt;title&gt; | &lt;author&gt; | &lt;price&gt; [| pages | category | desc]</code>\n"
              "• Receive physical copies: <code>/receive &lt;isbn&gt; &lt;quantity&gt;</code>\n"
              "• Inspect stock copies: <code>/inventory &lt;isbn_or_id&gt;</code>\n"
              "• View all books: <code>/books</code>",
        "am": "📚 <b>መጻሕፍትና ክምችት ማስተዳደር</b>\n\n"
              "• አዲስ መጽሐፍ ለማስገባት፦ <code>/addbook &lt;isbn&gt; | &lt;ርዕስ&gt; | &lt;ደራሲ&gt; | &lt;ዋጋ&gt; [| ገጾች | ምድብ | መግለጫ]</code>\n"
              "• ቅጂዎችን ለመቀበል፦ <code>/receive &lt;isbn&gt; &lt;ብዛት&gt;</code>\n"
              "• ቅጂዎችን ለመመርመር፦ <code>/inventory &lt;isbn_ወይም_id&gt;</code>\n"
              "• ሁሉንም ለማየት፦ <code>/books</code>",
    },
    "desc_admin_requests": {
        "en": "📝 <b>Rental Requests</b>\n\n"
              "Review submitted rental requests and reserve available copies:\n"
              "• View requests: <code>/requests [status]</code>\n"
              "• Approve request & reserve copy: <code>/approvereq &lt;id&gt; [copy_id]</code>\n"
              "• Reject request: <code>/rejectreq &lt;id&gt; [reason]</code>\n"
              "• Confirm physical handover: <code>/checkout &lt;id&gt;</code>",
        "am": "📝 <b>የኪራይ ጥያቄዎች</b>\n\n"
              "የቀረቡ የኪራይ ጥያቄዎችን ይገምግሙና ያሉ ቅጂዎችን ይያዙ፦\n"
              "• ጥያቄዎችን ለማየት፦ <code>/requests [ሁኔታ]</code>\n"
              "• ለማጽደቅና ቅጂ ለመያዝ፦ <code>/approvereq &lt;id&gt; [ቅጂ_id]</code>\n"
              "• ውድቅ ለማድረግ፦ <code>/rejectreq &lt;id&gt; [ምክንያት]</code>\n"
              "• መጽሐፉን በአካል ለማስረከብ፦ <code>/checkout &lt;id&gt;</code>",
    },
    "desc_admin_payments": {
        "en": "💳 <b>Payment Verification & Guarantees</b>\n\n"
              "Record verified manual payments or non-cash guarantees:\n"
              "• Record cash/bank payment: <code>/recordpayment &lt;req_id&gt; &lt;fee|collateral&gt; &lt;cash|bank&gt; &lt;amount&gt; [ref]</code>\n"
              "• Record non-cash guarantee: <code>/recordguarantee &lt;req_id&gt; &lt;details&gt;</code>\n\n"
              "⚠️ <i>Note: Non-cash guarantees do not count as cash received.</i>",
        "am": "💳 <b>የክፍያ ማረጋገጫና ዋስትና</b>\n\n"
              "የተፈጸሙ ክፍያዎችን ወይም ጥሬ-ገንዘብ ያልሆኑ ዋስትናዎችን ይመዝግቡ፦\n"
              "• ክፍያ ለመመዝገብ፦ <code>/recordpayment &lt;ጥያቄ_id&gt; &lt;fee|collateral&gt; &lt;cash|bank&gt; &lt;መጠን&gt; [የማጣቀሻ_ቁጥር]</code>\n"
              "• ዋስትና ለመመዝገብ፦ <code>/recordguarantee &lt;ጥያቄ_id&gt; &lt;ዝርዝር&gt;</code>\n\n"
              "⚠️ <i>ማሳሰቢያ፦ ጥሬ-ገንዘብ ያልሆነ ዋስትና እንደተቀበሉት ገንዘብ አይቆጠርም።</i>",
    },
    "desc_admin_returns": {
        "en": "📦 <b>Confirm Physical Returns & Inspections</b>\n\n"
              "Inspect returned copies and reconcile rental balances:\n"
              "• Normal return: <code>/return &lt;rental_id&gt; &lt;good|damaged|lost&gt; [notes]</code>\n"
              "• Return with collateral deduction: <code>/returndeduct &lt;rental_id&gt; &lt;good|damaged|lost&gt; &lt;amount&gt; &lt;reason&gt;</code>\n"
              "• Full financial reconciliation: <code>/reconcile &lt;rental_id&gt;</code>",
        "am": "📦 <b>የመመለሻ ማረጋገጫና ምርመራ</b>\n\n"
              "የተመለሱ መጻሕፍትን ይመርምሩና ሂሳብ ያወራርዱ፦\n"
              "• መደበኛ መመለሻ፦ <code>/return &lt;የኪራይ_id&gt; &lt;good|damaged|lost&gt; [ማስታወሻ]</code>\n"
              "• ከዋስትና ተቀናሽ በማድረግ፦ <code>/returndeduct &lt;የኪራይ_id&gt; &lt;good|damaged|lost&gt; &lt;መጠን&gt; &lt;ምክንያት&gt;</code>\n"
              "• ሙሉ የፋይናንስ ማወራረጃ፦ <code>/reconcile &lt;የኪራይ_id&gt;</code>",
    },
    "desc_admin_help": {
        "en": "👑 <b>Owner Administration Command Guide</b>\n\n"
              "<b>Customer Approvals:</b>\n"
              "• /pending — Review pending customer registrations\n"
              "• /approve &lt;id&gt; — Approve customer\n"
              "• /reject &lt;id&gt; [reason] — Reject customer\n\n"
              "<b>Catalogue & Inventory:</b>\n"
              "• /addbook &lt;isbn&gt; | &lt;title&gt; | &lt;author&gt; | &lt;price&gt; [| pages | category | desc]\n"
              "• /receive &lt;isbn&gt; &lt;quantity&gt; — Add stock\n"
              "• /inventory [isbn_or_id] — View inventory breakdown or copy details\n\n"
              "<b>Rental & Checkout:</b>\n"
              "• /requests [status] — View rental requests\n"
              "• /approvereq &lt;id&gt; [copy_id] — Approve & reserve\n"
              "• /rejectreq &lt;id&gt; [reason] — Reject request\n"
              "• /recordpayment &lt;id&gt; &lt;fee|collateral&gt; &lt;cash|bank&gt; &lt;amt&gt; [ref]\n"
              "• /recordguarantee &lt;id&gt; &lt;details&gt;\n"
              "• /checkout &lt;id&gt; — Handover book\n\n"
              "<b>Overdue, Extensions & Returns:</b>\n"
              "• /overdue — View overdue rentals & fees (5 ETB/day)\n"
              "• /checkoverdue — Run manual overdue sweep\n"
              "• /extensions — View extension requests\n"
              "• /approveext &lt;id&gt; &lt;cash|bank&gt; [ref] — Approve 5-day extension (10 ETB)\n"
              "• /rejectext &lt;id&gt; [reason] — Reject extension\n"
              "• /return &lt;id&gt; &lt;good|damaged|lost&gt; [notes]\n"
              "• /returndeduct &lt;id&gt; &lt;good|damaged|lost&gt; &lt;amt&gt; &lt;reason&gt;\n"
              "• /reconcile &lt;id&gt; — Financial breakdown\n"
              "• /language — Switch language preference",
        "am": "👑 <b>የአስተዳዳሪ ሙሉ የትዕዛዝ መመሪያ</b>\n\n"
              "<b>የደንበኞች ማስተዳደሪያ፦</b>\n"
              "• /pending — በመጠባበቅ ላይ ያሉ ደንበኞችን ለማየት\n"
              "• /approve &lt;id&gt; — ደንበኛ ለማጽደቅ\n"
              "• /reject &lt;id&gt; [ምክንያት] — ደንበኛ ውድቅ ለማድረግ\n\n"
              "<b>ካታሎግና ክምችት፦</b>\n"
              "• /addbook &lt;isbn&gt; | &lt;ርዕስ&gt; | &lt;ደራሲ&gt; | &lt;ዋጋ&gt; [| ገጾች | ምድብ | መግለጫ]\n"
              "• /receive &lt;isbn&gt; &lt;ብዛት&gt; — አዳዲስ ቅጂዎችን ለመቀበል\n"
              "• /inventory [isbn_ወይም_id] — የክምችት ዝርዝር ለማየት\n\n"
              "<b>ኪራይና ርክክብ፦</b>\n"
              "• /requests [ሁኔታ] — የኪራይ ጥያቄዎችን ለማየት\n"
              "• /approvereq &lt;id&gt; [ቅጂ_id] — ጥያቄ አጽድቆ ቅጂ ለመያዝ\n"
              "• /rejectreq &lt;id&gt; [ምክንያት] — ጥያቄ ውድቅ ለማድረግ\n"
              "• /recordpayment &lt;id&gt; &lt;fee|collateral&gt; &lt;cash|bank&gt; &lt;መጠን&gt; [ማጣቀሻ]\n"
              "• /recordguarantee &lt;id&gt; &lt;ዝርዝር&gt; — ዋስትና ለመመዝገብ\n"
              "• /checkout &lt;id&gt; — መጽሐፍ ለማስረከብ\n\n"
              "<b>ማራዘሚያና መመለሻ፦</b>\n"
              "• /overdue — የዘገዩ ኪራዮችንና ቅጣቶችን ለማየት (በቀን 5 ብር)\n"
              "• /checkoverdue — የዘገዩትን አሁን ለመመርመር\n"
              "• /extensions — የማራዘሚያ ጥያቄዎችን ለማየት\n"
              "• /approveext &lt;id&gt; &lt;cash|bank&gt; [ማጣቀሻ] — የ5 ቀን ማራዘሚያ ለማጽደቅ (10 ብር)\n"
              "• /rejectext &lt;id&gt; [ምክንያት] — ማራዘሚያ ውድቅ ለማድረግ\n"
              "• /return &lt;id&gt; &lt;good|damaged|lost&gt; [ማስታወሻ]\n"
              "• /returndeduct &lt;id&gt; &lt;good|damaged|lost&gt; &lt;መጠን&gt; &lt;ምክንያት&gt;\n"
              "• /reconcile &lt;id&gt; — የሂሳብ ማወራረጃ\n"
              "• /language — ቋንቋ ለመቀየር",
    },

    # --------------------------------------------------------------------------
    # Rejected Customers Section
    # --------------------------------------------------------------------------
    "rejected_list_header": {
        "en": "🚫 <b>Rejected Customers ({total}):</b> (Page {page}/{total_pages})",
        "am": "🚫 <b>የተከለከሉ ደንበኞች ({total})፦</b> (ገጽ {page}/{total_pages})",
    },
    "rejected_empty": {
        "en": "✅ There are currently no rejected customer accounts in the database.",
        "am": "✅ በአሁን ወቅት በመረጃ ቋቱ ውስጥ የተከለከለ የደንበኛ መለያ የለም።",
    },
    "rejected_card": {
        "en": "🚫 <b>Customer #{id}</b>\n"
              "• Name: <b>{name}</b>\n"
              "• Username: {username}\n"
              "• Telegram ID: <code>{telegram_id}</code>\n"
              "• Rejected At: {rejected_at}\n"
              "• Reason: <i>{reason}</i>",
        "am": "🚫 <b>ደንበኛ #{id}</b>\n"
              "• ስም፦ <b>{name}</b>\n"
              "• የተጠቃሚ ስም፦ {username}\n"
              "• ቴሌግራም ID፦ <code>{telegram_id}</code>\n"
              "• የተከለከለበት ቀን፦ {rejected_at}\n"
              "• ምክንያት፦ <i>{reason}</i>",
    },
    "reason_not_specified": {
        "en": "No reason specified",
        "am": "ምክንያት አልተገለጸም",
    },
    "btn_reapprove": {
        "en": "🔄 Reapprove Customer #{id}",
        "am": "🔄 ደንበኛ #{id} እንደገና አጽድቅ",
    },
    "btn_back_admin": {
        "en": "🔙 Back to Admin Menu",
        "am": "🔙 ወደ አስተዳዳሪ ምናሌ ተመለስ",
    },
    "btn_prev": {
        "en": "⬅️ Previous",
        "am": "⬅️ ወደኋላ",
    },
    "btn_next": {
        "en": "Next ➡️",
        "am": "ወደፊት ➡️",
    },
    "reapproved_success": {
        "en": "✅ Customer <b>{name}</b> (#{id}) has been successfully <b>REAPPROVED</b>.",
        "am": "✅ ደንበኛ <b>{name}</b> (#{id}) በተሳካ ሁኔታ <b>እንደገና ጸድቋል</b>።",
    },

    # --------------------------------------------------------------------------
    # General Navigation & Fallback
    # --------------------------------------------------------------------------
    "access_denied_admin": {
        "en": "⛔ Access denied: This action is restricted to library owners.",
        "am": "⛔ መዳረሻ ተከልክሏል፦ ይህ ተግባር የተፈቀደው ለመጽሐፍ አስተዳዳሪዎች ብቻ ነው።",
    },
    "action_not_permitted_status": {
        "en": "⚠️ Your account is currently <b>{status}</b>. Book borrowing and catalogue searching require an approved account.",
        "am": "⚠️ የመለያዎ ሁኔታ በአሁን ወቅት <b>{status}</b> ነው። መጻሕፍትን ለመዋስና ለመፈለግ የጸደቀ መለያ ያስፈልጋል።",
    },
    "unexpected_text_guidance": {
        "en": "ℹ️ I didn't recognize that message. Please use the menu buttons below or type /help for available commands.",
        "am": "ℹ️ የላኩትን መልዕክት መረዳት አልተቻለም። እባክዎን ከታች ያሉትን ቁልፎች ይጠቀሙ ወይም /help ብለው ይላኩ።",
    },

    # --------------------------------------------------------------------------
    # Phase 8: Registration & Verification Flow
    # --------------------------------------------------------------------------
    "reg_consent_prompt": {
        "en": "📋 <b>Customer Verification & Privacy Consent</b>\n\n"
              "To borrow physical books from BookRent, we verify customer identity through:\n"
              "• A clear photo of your <b>National ID</b> (Fayda / Kebele / Passport / Student ID)\n"
              "• A verified <b>phone number</b>\n"
              "• Your residential <b>location or address</b>\n\n"
              "🔒 <i>Privacy Guarantee:</i> Your information is strictly used for rental verification and collateral protection. "
              "It is never sold or shared with third parties (Policy v{version}).\n\n"
              "Do you agree to continue?",
        "am": "📋 <b>የደንበኛ ማረጋገጫና የግል መረጃ ፈቃድ</b>\n\n"
              "ከBookRent መጻሕፍትን ለመዋስ የሚከተሉትን ማረጋገጫዎች እንሰበስባለን፦\n"
              "• ግልጽ የ<b>ብሔራዊ መታወቂያ</b> ፎቶ (ፋይዳ / የቀበሌ / ፓስፖርት / የተማሪ መታወቂያ)\n"
              "• የተረጋገጠ የ<b>ስልክ ቁጥር</b>\n"
              "• የመኖሪያ <b>አድራሻዎ</b>\n\n"
              "🔒 <i>የግላዊነት ዋስትና፦</i> መረጃዎ ለኪራይ ማረጋገጫና ለዋስትና ጥበቃ ብቻ ያገለግላል። ለማንም አካል አይተላለፍም (መመሪያ v{version})።\n\n"
              "ለመቀጠል ይስማማሉ?",
    },
    "btn_consent_agree": {
        "en": "✅ I Agree",
        "am": "✅ እስማማለሁ",
    },
    "btn_cancel": {
        "en": "❌ Cancel",
        "am": "❌ ሰርዝ",
    },
    "btn_back": {
        "en": "⬅️ Back",
        "am": "⬅️ ወደኋላ",
    },
    "reg_step_photo": {
        "en": "📷 <b>Step 1 of 3: National ID Photo</b>\n\n"
              "Please upload a clear, legible photo of your Ethiopian National ID (Fayda, Kebele ID, Passport, or Student ID).\n\n"
              "💡 <i>Tip:</i> Ensure your full name and photo are clearly visible. Avoid glare or blurry images.",
        "am": "📷 <b>ደረጃ 1 ከ 3፦ የብሔራዊ መታወቂያ ፎቶ</b>\n\n"
              "እባክዎን ግልጽና የሚነበብ የብሔራዊ መታወቂያዎን (ፋይዳ፣ የቀበሌ መታወቂያ፣ ፓስፖርት ወይም የተማሪ መታወቂያ) ፎቶ ይላኩ።\n\n"
              "💡 <i>ምክር፦</i> ስምዎና ፎቶዎ በግልጽ እንዲታዩ ያድርጉ። የደበዘዘ ወይም ጨለማ ፎቶ አይላኩ።",
    },
    "reg_err_photo_required": {
        "en": "⚠️ Please send a <b>photo</b> of your National ID. Text messages or document files are not accepted. Try again or press Cancel.",
        "am": "⚠️ እባክዎን የመታወቂያዎን <b>ፎቶ</b> ይላኩ። የጽሑፍ መልዕክት ወይም ሰነድ ተቀባይነት የለውም። እንደገና ይሞክሩ ወይም ሰርዝ የሚለውን ይጫኑ።",
    },
    "reg_step_phone": {
        "en": "📱 <b>Step 2 of 3: Phone Number</b>\n\n"
              "Please share your phone number using the button below, or type it manually (e.g. <code>+251911223344</code> or <code>0911223344</code>).",
        "am": "📱 <b>ደረጃ 2 ከ 3፦ ስልክ ቁጥር</b>\n\n"
              "እባክዎን ከታች ያለውን ቁልፍ በመጫን ስልክ ቁጥርዎን ያጋሩ ወይም በእጅዎ ይተይቡ (ምሳሌ፦ <code>+251911223344</code> ወይም <code>0911223344</code>)።",
    },
    "btn_share_contact": {
        "en": "📱 Share Phone Number",
        "am": "📱 ስልክ ቁጥር ያጋሩ",
    },
    "reg_err_phone_invalid": {
        "en": "⚠️ Invalid phone number format. Please enter a valid number (e.g. <code>0911223344</code>, <code>0711223344</code>, or <code>+251911223344</code>) or use the button below.",
        "am": "⚠️ የተሳሳተ የስልክ ቁጥር ቅርጸት ነው። እባክዎን ትክክለኛ ቁጥር ያስገቡ (ምሳሌ፦ <code>0911223344</code> ወይም <code>+251911223344</code>) ወይም ከታች ያለውን ቁልፍ ይጠቀሙ።",
    },
    "reg_step_location": {
        "en": "📍 <b>Step 3 of 3: Residential Location</b>\n\n"
              "Please share your location using the button below, or type your readable residential address (e.g., <i>Addis Ababa, Bole Sub-City, Woreda 03, Near Edna Mall</i>).",
        "am": "📍 <b>ደረጃ 3 ከ 3፦ የመኖሪያ አድራሻ</b>\n\n"
              "እባክዎን ከታች ያለውን ቁልፍ በመጫን አድራሻዎን ያጋሩ ወይም የመኖሪያ አድራሻዎን በጽሑፍ ይላኩ (ምሳሌ፦ <i>አዲስ አበባ፣ ቦሌ ክ/ከተማ፣ ወረዳ 03፣ ኤድና ሞል አካባቢ</i>)።",
    },
    "btn_share_location": {
        "en": "📍 Share Location",
        "am": "📍 አድራሻ ያጋሩ",
    },
    "reg_err_location_required": {
        "en": "⚠️ Please share a valid location using the button or enter a detailed residential address (city, sub-city, neighborhood).",
        "am": "⚠️ እባክዎን አድራሻዎን በቁልፉ ያጋሩ ወይም ዝርዝር የመኖሪያ አድራሻዎን (ከተማ፣ ክ/ከተማ፣ ሰፈር) ይጻፉ።",
    },
    "reg_summary": {
        "en": "📋 <b>Registration Summary</b>\n\n"
              "Please review your verification details before submitting:\n"
              "• <b>Name:</b> {name}\n"
              "• <b>Phone:</b> {phone} ({source})\n"
              "• <b>Address:</b> {address}\n"
              "• <b>National ID:</b> Photo uploaded ✅\n\n"
              "Press <b>Confirm & Submit</b> to send your registration to the library owner for approval.",
        "am": "📋 <b>የምዝገባ ማጠቃለያ</b>\n\n"
              "እባክዎን ከማረጋገጥዎ በፊት መረጃዎን ይመርምሩ፦\n"
              "• <b>ስም፦</b> {name}\n"
              "• <b>ስልክ፦</b> {phone} ({source})\n"
              "• <b>አድራሻ፦</b> {address}\n"
              "• <b>ብሔራዊ መታወቂያ፦</b> ፎቶ ተያይዟል ✅\n\n"
              "ምዝገባዎን ለመጽሐፍ አስተዳዳሪው ለመላክ <b>አረጋግጥና ላክ</b> የሚለውን ይጫኑ።",
    },
    "btn_confirm_submit": {
        "en": "✅ Confirm & Submit",
        "am": "✅ አረጋግጥና ላክ",
    },
    "reg_submitted_success": {
        "en": "🎉 <b>Registration Submitted Successfully!</b>\n\n"
              "Your account is now <b>PENDING</b> review by the library administrator. "
              "You will receive a notification as soon as your account is reviewed.",
        "am": "🎉 <b>ምዝገባዎ በተሳካ ሁኔታ ተልኳል!</b>\n\n"
              "መለያዎ በአሁን ወቅት በመጽሐፍ አስተዳዳሪው <b>በመገምገም ላይ</b> ነው። "
              "መለያዎ እንደተገመገመ መልዕክት ይደርስዎታል።",
    },
    "reg_cancelled": {
        "en": "❌ Registration was cancelled. You can type /start or /register at any time to resume.",
        "am": "❌ ምዝገባው ተሰርዟል። በማንኛውም ጊዜ ለመቀጠል /start ወይም /register ብለው መላክ ይችላሉ።",
    },
    "btn_view_id_photo": {
        "en": "🆔 View ID Photo",
        "am": "🆔 የመታወቂያ ፎቶ እይ",
    },

    # --------------------------------------------------------------------------
    # Phase 8: Event Notification Templates
    # --------------------------------------------------------------------------
    "notify_reg_submitted_admin": {
        "en": "🔔 <b>New Customer Registration:</b> Customer #{id} (<b>{name}</b>) has submitted verification details for review.\n"
              "• Phone: {phone}\n"
              "• Address: {address}\n"
              "Use /pending to review registration and identity artifacts.",
        "am": "🔔 <b>አዲስ የደንበኛ ምዝገባ፦</b> ደንበኛ #{id} (<b>{name}</b>) የማረጋገጫ መረጃዎችን ለግምገማ ልኳል።\n"
              "• ስልክ፦ {phone}\n"
              "• አድራሻ፦ {address}\n"
              "መረጃዎችን ለመመርመርና ለማጽደቅ /pending ይጠቀሙ።",
    },
    "notify_customer_approved": {
        "en": "🎉 <b>Account Approved!</b> Welcome to BookRent, <b>{name}</b>! Your customer account is now active and approved for book borrowing. Send /books or /search to explore our catalogue.",
        "am": "🎉 <b>መለያዎ ጸድቋል!</b> እንኳን ወደ BookRent በደህና መጡ፣ <b>{name}</b>! መለያዎ ንቁ ሆኗል፣ መጻሕፍትን መዋስ ይችላሉ። ካታሎጉን ለማየት /books ወይም /search ብለው ይላኩ።",
    },
    "notify_customer_rejected": {
        "en": "⚠️ <b>Account Update:</b> Your BookRent registration was not approved.\n{reason_line}If you have questions, please contact the library owner.",
        "am": "⚠️ <b>የመለያ ማሳሰቢያ፦</b> የBookRent ምዝገባዎ ተቀባይነት አላገኘም።\n{reason_line}ጥያቄ ካለዎት እባክዎን የመጽሐፍ አስተዳዳሪውን ያነጋግሩ።",
    },
    "notify_book_added_admin": {
        "en": "📚 <b>Book Catalogued:</b> <i>{title}</i> by {author} (ISBN: <code>{isbn}</code>) has been added to the library catalogue.",
        "am": "📚 <b>መጽሐፍ ተመዝግቧል፦</b> <i>{title}</i> በ{author} (ISBN: <code>{isbn}</code>) ወደ ቤተ-መጽሐፍቱ ካታሎግ ገብቷል።",
    },
    "notify_stock_received_admin": {
        "en": "📦 <b>Stock Received:</b> Received {quantity} physical copies for ISBN <code>{isbn}</code>.",
        "am": "📦 <b>ቅጂዎች ተቀብለዋል፦</b> ለISBN <code>{isbn}</code> {quantity} ቅጂዎች ገብተዋል።",
    },
    "notify_new_book_broadcast": {
        "en": "📢 <b>New Arrival!</b> <i>{title}</i> by {author} is now available for rental at {price} ETB/day! Use /search {title} to view details.",
        "am": "📢 <b>አዲስ መጽሐፍ ደርሷል!</b> <i>{title}</i> በ{author} በ{price} ብር/ቀን ለመከራየት ይገኛል! ዝርዝሩን ለማየት /search {title} ይላኩ።",
    },
    "notify_req_submitted_admin": {
        "en": "📝 <b>New Rental Request #{id}:</b> Customer <b>{customer_name}</b> requested to rent <i>{book_title}</i>. Review with /requests.",
        "am": "📝 <b>አዲስ የኪራይ ጥያቄ #{id}፦</b> ደንበኛ <b>{customer_name}</b> <i>{book_title}</i> ለመዋስ ጠይቀዋል። በ/requests ይገምግሙ።",
    },
    "notify_req_approved_cust": {
        "en": "✅ <b>Rental Request Approved!</b> Your request for <i>{book_title}</i> (Copy #{copy_id}) has been approved and reserved. Please provide rental fee & collateral to complete handover.",
        "am": "✅ <b>የኪራይ ጥያቄዎ ጸድቋል!</b> ለ<i>{book_title}</i> (ቅጂ #{copy_id}) ያቀረቡት ጥያቄ ጸድቆ ተይዞልዎታል። ርክክቡን ለማጠናቀቅ የኪራይ ክፍያና ዋስትና ያቅርቡ።",
    },
    "notify_req_rejected_cust": {
        "en": "❌ <b>Rental Request Rejected:</b> Your rental request #{id} for <i>{book_title}</i> was not approved.\n{reason_line}",
        "am": "❌ <b>የኪራይ ጥያቄዎ ውድቅ ተደርጓል፦</b> ለ<i>{book_title}</i> የቀረበው የኪራይ ጥያቄ #{id} ተቀባይነት አላገኘም።\n{reason_line}",
    },
    "notify_payment_recorded_cust": {
        "en": "💳 <b>Payment Verified:</b> Received {amount} ETB for {payment_type} via {method} (Ref: {reference}).",
        "am": "💳 <b>ክፍያ ተረጋግጧል፦</b> ለ{payment_type} {amount} ብር በ{method} ደርሶ ተረጋግጧል (ማጣቀሻ፦ {reference})።",
    },
    "notify_payment_recorded_admin": {
        "en": "💳 <b>Payment Recorded:</b> Verified {amount} ETB for Request #{request_id} ({payment_type}) via {method}.",
        "am": "💳 <b>ክፍያ ተመዝግቧል፦</b> ለጥያቄ #{request_id} {amount} ብር በ{method} ተረጋግጧል ({payment_type})።",
    },
    "notify_guarantee_recorded_cust": {
        "en": "📄 <b>Guarantee Verified:</b> Non-cash collateral guarantee recorded: <i>{details}</i>.\n⚠️ <i>Note: This is a non-cash document guarantee, not a cash deposit.</i>",
        "am": "📄 <b>ዋስትና ተመዝግቧል፦</b> ጥሬ-ገንዘብ ያልሆነ ዋስትና ተመዝግቧል፦ <i>{details}</i>።\n⚠️ <i>ማሳሰቢያ፦ ይህ የሰነድ/መታወቂያ ዋስትና እንጂ ጥሬ ገንዘብ አይደለም።</i>",
    },
    "notify_checkout_cust": {
        "en": "📖 <b>Book Handover Confirmed!</b> You have borrowed <i>{book_title}</i> (Copy #{barcode}).\n📅 <b>Return Deadline:</b> {due_date}\n⚠️ Overdue fee of 5.00 ETB/day applies after this deadline.",
        "am": "📖 <b>መጽሐፍ ተረክበዋል!</b> <i>{book_title}</i> (ቅጂ #{barcode}) ተረክበዋል።\n📅 <b>የመመለሻ ቀን፦</b> {due_date}\n⚠️ ከዚህ ቀን ካለፈ በቀን 5.00 ብር ቅጣት ይታሰባል።",
    },
    "notify_ext_requested_admin": {
        "en": "⏳ <b>Extension Request #{id}:</b> Customer <b>{customer_name}</b> requested a 5-day extension for Rental #{rental_id}. Review with /extensions.",
        "am": "⏳ <b>የማራዘሚያ ጥያቄ #{id}፦</b> ደንበኛ <b>{customer_name}</b> ለኪራይ #{rental_id} የ5 ቀን ማራዘሚያ ጠይቀዋል። በ/extensions ይገምግሙ።",
    },
    "notify_ext_approved_cust": {
        "en": "🎉 <b>Rental Extension Approved!</b> Your 5-day extension for Rental #{rental_id} has been approved.\n📅 <b>New Return Deadline:</b> {due_date}",
        "am": "🎉 <b>የኪራይ ማራዘሚያ ጸድቋል!</b> ለኪራይ #{rental_id} የ5 ቀን ማራዘሚያዎ ጸድቋል።\n📅 <b>አዲሱ የመመለሻ ቀን፦</b> {due_date}",
    },
    "notify_ext_rejected_cust": {
        "en": "❌ <b>Extension Request Rejected:</b> Your extension request for Rental #{rental_id} was rejected. Due date remains {due_date}.\n{reason_line}",
        "am": "❌ <b>የማራዘሚያ ጥያቄ ውድቅ ተደርጓል፦</b> ለኪራይ #{rental_id} የቀረበው ጥያቄ ተቀባይነት አላገኘም። የመመለሻ ቀን {due_date} ነው።\n{reason_line}",
    },
    "notify_return_confirmed_cust": {
        "en": "📦 <b>Return Confirmed:</b> Rental #{rental_id} for <i>{book_title}</i> has been returned and inspected (Condition: {condition}). Thank you for renting with BookRent!",
        "am": "📦 <b>መመለስ ተረጋግጧል፦</b> ለ<i>{book_title}</i> ኪራይ #{rental_id} ተመልሶ ተመርምሯል (ሁኔታ፦ {condition})። ከBookRent ስለተዋሱ እናመሰግናለን!",
    },
    "notify_deduction_cust": {
        "en": "⚠️ <b>Collateral Deduction:</b> A deduction of {amount} ETB has been applied to Rental #{rental_id}.\nReason: <i>{reason}</i>",
        "am": "⚠️ <b>የዋስትና ተቀናሽ፦</b> ከኪራይ #{rental_id} ላይ የ{amount} ብር ተቀናሽ ተደርጓል።\nምክንያት፦ <i>{reason}</i>",
    },
    "notify_refund_cust": {
        "en": "💰 <b>Collateral Refund:</b> A collateral refund of {amount} ETB has been issued for Rental #{rental_id}.",
        "am": "💰 <b>የዋስትና ተመላሽ፦</b> ለኪራይ #{rental_id} የ{amount} ብር የዋስትና ተመላሽ ተደርጓል።",
    },
}


def t(key: str, lang: str = DEFAULT_LANGUAGE, **kwargs: Any) -> str:
    """Retrieve localized message string formatted with optional kwargs.

    Falls back to English if key is missing in Amharic, or key itself if missing.
    """
    if lang not in SUPPORTED_LANGUAGES:
        lang = DEFAULT_LANGUAGE

    entry = TRANSLATIONS.get(key)
    if not entry:
        return key

    text_template = entry.get(lang) or entry.get(DEFAULT_LANGUAGE, key)
    if kwargs:
        try:
            return text_template.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text_template
    return text_template


def get_language_inline_keyboard() -> InlineKeyboardMarkup:
    """Generate inline keyboard for language selection."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🇬🇧 English", callback_data="lang:en"),
                InlineKeyboardButton("🇪🇹 አማርኛ", callback_data="lang:am"),
            ]
        ]
    )


def get_customer_reply_keyboard(lang: str = DEFAULT_LANGUAGE) -> ReplyKeyboardMarkup:
    """Generate reply keyboard for customer navigation menu."""
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(t("btn_cust_search", lang)),
                KeyboardButton(t("btn_cust_browse", lang)),
            ],
            [
                KeyboardButton(t("btn_cust_rent", lang)),
                KeyboardButton(t("btn_cust_myrentals", lang)),
            ],
            [
                KeyboardButton(t("btn_cust_extensions", lang)),
                KeyboardButton(t("btn_change_language", lang)),
            ],
            [
                KeyboardButton(t("btn_cust_help", lang)),
            ],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def get_admin_reply_keyboard(lang: str = DEFAULT_LANGUAGE) -> ReplyKeyboardMarkup:
    """Generate reply keyboard for owner/admin navigation menu with guided buttons."""
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(t("btn_admin_add_book", lang)),
                KeyboardButton(t("btn_admin_pending", lang)),
            ],
            [
                KeyboardButton(t("btn_admin_requests", lang)),
                KeyboardButton(t("btn_admin_returns", lang)),
            ],
            [
                KeyboardButton(t("btn_admin_books", lang)),
                KeyboardButton(t("btn_admin_payments", lang)),
            ],
            [
                KeyboardButton(t("btn_admin_extensions", lang)),
                KeyboardButton(t("btn_admin_overdue", lang)),
            ],
            [
                KeyboardButton(t("btn_admin_inventory", lang)),
                KeyboardButton(t("btn_admin_rejected", lang)),
            ],
            [
                KeyboardButton(t("btn_change_language", lang)),
                KeyboardButton(t("btn_admin_help", lang)),
            ],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def get_consent_keyboard(lang: str = DEFAULT_LANGUAGE) -> ReplyKeyboardMarkup:
    """Generate reply keyboard for registration privacy consent step."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(t("btn_consent_agree", lang))],
            [KeyboardButton(t("btn_cancel", lang))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def get_photo_step_keyboard(lang: str = DEFAULT_LANGUAGE) -> ReplyKeyboardMarkup:
    """Generate reply keyboard for National ID photo upload step."""
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(t("btn_back", lang)),
                KeyboardButton(t("btn_cancel", lang)),
            ],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def get_phone_step_keyboard(lang: str = DEFAULT_LANGUAGE) -> ReplyKeyboardMarkup:
    """Generate reply keyboard with contact sharing for phone number step."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(t("btn_share_contact", lang), request_contact=True)],
            [
                KeyboardButton(t("btn_back", lang)),
                KeyboardButton(t("btn_cancel", lang)),
            ],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def get_location_step_keyboard(lang: str = DEFAULT_LANGUAGE) -> ReplyKeyboardMarkup:
    """Generate reply keyboard with location sharing for location/address step."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(t("btn_share_location", lang), request_location=True)],
            [
                KeyboardButton(t("btn_back", lang)),
                KeyboardButton(t("btn_cancel", lang)),
            ],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def get_confirm_registration_keyboard(lang: str = DEFAULT_LANGUAGE) -> ReplyKeyboardMarkup:
    """Generate reply keyboard for final registration confirmation step."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(t("btn_confirm_submit", lang))],
            [
                KeyboardButton(t("btn_back", lang)),
                KeyboardButton(t("btn_cancel", lang)),
            ],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def get_isbn_step_keyboard(lang: str = DEFAULT_LANGUAGE) -> ReplyKeyboardMarkup:
    """Generate reply keyboard for ISBN step with visible Skip and Cancel buttons."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(t("btn_skip", lang))],
            [KeyboardButton(t("btn_cancel", lang))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def get_cancel_keyboard(lang: str = DEFAULT_LANGUAGE) -> ReplyKeyboardMarkup:
    """Generate simple reply keyboard with cancel button."""
    return ReplyKeyboardMarkup(
        [[KeyboardButton(t("btn_cancel", lang))]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def get_step_nav_keyboard(lang: str = DEFAULT_LANGUAGE, allow_skip: bool = False) -> ReplyKeyboardMarkup:
    """Generate step navigation reply keyboard (Back, Cancel, and optional Skip)."""
    rows = []
    if allow_skip:
        rows.append([KeyboardButton(t("btn_skip", lang))])
    rows.append([
        KeyboardButton(t("btn_back", lang)),
        KeyboardButton(t("btn_cancel", lang)),
    ])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True)


def get_add_book_confirm_keyboard(lang: str = DEFAULT_LANGUAGE) -> ReplyKeyboardMarkup:
    """Generate reply keyboard for add book final confirmation."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(t("btn_confirm_save", lang))],
            [
                KeyboardButton(t("btn_back", lang)),
                KeyboardButton(t("btn_cancel", lang)),
            ],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def get_existing_book_action_keyboard(lang: str = DEFAULT_LANGUAGE) -> ReplyKeyboardMarkup:
    """Generate reply keyboard when an ISBN is already catalogued."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(t("btn_add_copies", lang))],
            [KeyboardButton(t("btn_cancel", lang))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def get_book_search_menu_keyboard(lang: str = DEFAULT_LANGUAGE) -> InlineKeyboardMarkup:
    """Generate interactive inline keyboard for customer book search modes."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(t("btn_search_title", lang), callback_data="search_mode:title"),
                InlineKeyboardButton(t("btn_search_author", lang), callback_data="search_mode:author"),
            ],
            [
                InlineKeyboardButton(t("btn_search_category", lang), callback_data="search_mode:category"),
                InlineKeyboardButton(t("btn_search_browse", lang), callback_data="search_mode:browse"),
            ],
        ]
    )


def get_rental_collateral_keyboard(lang: str = DEFAULT_LANGUAGE, book_id: int = 0) -> InlineKeyboardMarkup:
    """Generate inline keyboard for customer collateral selection."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(t("btn_cash_collat", lang), callback_data=f"req_collat:cash:{book_id}"),
                InlineKeyboardButton(t("btn_guarantee_collat", lang), callback_data=f"req_collat:guarantee:{book_id}"),
            ],
            [
                InlineKeyboardButton(t("btn_cancel", lang), callback_data="req_cancel"),
            ],
        ]
    )


def get_rental_confirm_keyboard(lang: str = DEFAULT_LANGUAGE, book_id: int = 0, collat_type: str = "cash") -> InlineKeyboardMarkup:
    """Generate inline keyboard for rental request final confirmation."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(t("btn_submit_request", lang), callback_data=f"req_submit:{collat_type}:{book_id}"),
            ],
            [
                InlineKeyboardButton(t("btn_cancel", lang), callback_data="req_cancel"),
            ],
        ]
    )


def get_owner_request_action_keyboard(
    lang: str,
    request_id: int,
    status: str,
    fee_paid: bool,
    collat_received: bool,
    can_checkout: bool,
) -> InlineKeyboardMarkup:
    """Generate inline action buttons for an owner reviewing a rental request."""
    buttons = []
    if status == "SUBMITTED":
        buttons.append([
            InlineKeyboardButton("✅ Approve Request" if lang == "en" else "✅ ጥያቄ አጽድቅ", callback_data=f"req_act:approve:{request_id}"),
            InlineKeyboardButton("❌ Reject" if lang == "en" else "❌ ውድቅ አድርግ", callback_data=f"req_act:reject:{request_id}"),
        ])
    elif status == "APPROVED":
        pay_row = []
        if not fee_paid:
            pay_row.append(InlineKeyboardButton("💵 Verify Fee (Cash)" if lang == "en" else "💵 የኪራይ ክፍያ (ጥሬ ገንዘብ)", callback_data=f"req_act:pay_cash:{request_id}"))
            pay_row.append(InlineKeyboardButton("🏦 Bank" if lang == "en" else "🏦 ባንክ", callback_data=f"req_act:pay_bank:{request_id}"))
        if pay_row:
            buttons.append(pay_row)

        collat_row = []
        if not collat_received:
            collat_row.append(InlineKeyboardButton("🪪 Record Guarantee" if lang == "en" else "🪪 ዋስትና መዝግብ", callback_data=f"req_act:guarantee:{request_id}"))
            collat_row.append(InlineKeyboardButton("💵 Cash Deposit" if lang == "en" else "💵 የጥሬ ተቀማጭ", callback_data=f"req_act:deposit_cash:{request_id}"))
        if collat_row:
            buttons.append(collat_row)

        action_row = []
        if can_checkout:
            action_row.append(InlineKeyboardButton("🚀 Confirm Handover" if lang == "en" else "🚀 መጽሐፉን አስረክብ", callback_data=f"req_act:handover:{request_id}"))
        action_row.append(InlineKeyboardButton("❌ Cancel" if lang == "en" else "❌ ሰርዝ", callback_data=f"req_act:reject:{request_id}"))
        buttons.append(action_row)

    return InlineKeyboardMarkup(buttons)


def get_owner_return_action_keyboard(lang: str, rental_id: int) -> InlineKeyboardMarkup:
    """Generate inline buttons for inspecting and confirming a book return."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Return (Good Condition)" if lang == "en" else "✅ መደበኛ መመለሻ (ጥሩ ሁኔታ)", callback_data=f"ret_act:good:{rental_id}"),
            ],
            [
                InlineKeyboardButton("⚠️ Return (Damaged)" if lang == "en" else "⚠️ የተጎዳ መመለሻ", callback_data=f"ret_act:damaged:{rental_id}"),
                InlineKeyboardButton("🚨 Return (Lost)" if lang == "en" else "🚨 የጠፋ መጽሐፍ", callback_data=f"ret_act:lost:{rental_id}"),
            ],
            [
                InlineKeyboardButton("📊 Financial Summary" if lang == "en" else "📊 የሂሳብ ማጠቃለያ", callback_data=f"ret_act:reconcile:{rental_id}"),
            ],
        ]
    )

