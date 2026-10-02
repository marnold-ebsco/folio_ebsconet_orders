# Loading your EBSCONET orders into FOLIO: what we need from you

## What this project does
EBSCONET holds your journal and database subscription orders. We use the order spreadsheet
from EBSCONET (the "SOP") to create matching **purchase orders** in your FOLIO system, so
that your subscriptions can be managed and renewed from FOLIO. Each subscription becomes one
purchase order with one order line, carrying the title, the ISSN where there is one, the
subscription dates, the price, the fund it is paid from, and your EBSCONET account number.

Two things to know up front:
- **Nothing is spent or committed.** We create the orders with the status **Pending** and
  leave them that way. They are not opened, and no money is encumbered against your funds,
  until you open them yourselves.
- **You decide where the money is charged.** Which fund, which expense class and which
  organization go on each order is your choice. You give us that information, line by line,
  in the spreadsheets we send you (step 4 below).

## The process, in order
| # | Who | What happens |
|---|---|---|
| 1 | You / EBSCONET | The EBSCONET order spreadsheet (SOP) is obtained from your EBSCONET representative. |
| 2 | You | **Before we start:** your FOLIO system is checked against the list in section 1 below, and the choices in section 3 are made. |
| 3 | EBSCO | We prepare your copy of the spreadsheet: we remove the lines that cost nothing, split the rest by format onto up to **three sheets** (electronic, physical, and print + electronic, "P/E") of **one workbook**, and add empty columns for you to fill in. A **Defaults** sheet comes first with a few setup questions. We send you the workbook. |
| 4 | **You** | **You fill in the highlighted columns on every line of each spreadsheet and send them all back** (section 2). |
| 5 | EBSCO | We check your codes against your FOLIO system. If anything is wrong (a mistyped code, a fund that does not exist) we send you the list, you correct it, and we check again. This repeats until the files are clean. |
| 6 | EBSCO | We load the orders into FOLIO as Pending orders. |
| 7 | You | You look over a sample of the orders in FOLIO and tell us they look right. |
| 8 | EBSCO | We convert to *ongoing* orders the ones you marked **Ongoing**, using the renewal interval you gave (section 4). |
| 9 | EBSCO / you | We give EBSCONET the list of FOLIO order numbers so that your renewals can be matched to them. |

## 1. What must be ready in your FOLIO system
Please have these in place before we start. Menu names can differ slightly between FOLIO
versions; your FOLIO administrator will know where to find them.

- **An organization record for EBSCONET** (set up as a vendor). We add your EBSCONET account
  numbers to it, so we need permission to edit that record, or your administrator can add the
  account numbers we send.
- **Funds** for these orders, each with an **active budget** for the fiscal year of the
  orders. The amount in the budget does not matter for loading (a budget of zero is fine), but
  the budget must exist and be active. If you use expense classes, the budget must list them.
- **Expense classes**, only if your library uses them.
- **Organizations** for the publishers or platforms you want shown as the access provider,
  if you want that (optional, see section 3), each marked as a vendor.
- For **physical (print) and P/E** subscriptions: the **locations** (for example your serials
  or periodicals location) and **material types** (for example "journal" or "serial") you
  will choose from on the spreadsheet.
- **An account for us** to work with, with permission to create Data Import profiles, run
  imports, create and edit orders, and read the finance and organization settings. (Or
  your administrator can work with us on a screen share.)

## 2. What you fill in
We send you **one workbook**. Its first sheet, **Defaults**, asks a few setup questions
(default fund, location, order type and so on); answer them in the yellow "Your answer"
column, using the drop-downs where offered. After it come up to three sheets, one for each
kind of subscription. If you have no subscriptions of a kind, that sheet is left out.

| Sheet | Contains | What you fill in |
|---|---|---|
| **Electronic** | Online-only titles, databases, e-books | Fund, expense class, organization, **order type and renewal interval** |
| **Physical** | Print-only titles | Fund, expense class, organization, **order type and renewal interval**, **location and material type** |
| **P/E** | Print + online titles | Everything above: fund, expense class, organization, order type and renewal interval, location and material type |

On each sheet the columns to fill in are **highlighted in light yellow**. On every line
please enter:

| Column | On which spreadsheet | What to enter | Where to find it |
|---|---|---|---|
| **FOLIO Fund** | all | The **code** of the fund that pays for this subscription | Finance app, list of funds |
| **FOLIO Expense Class** | all | The **code** of the expense class, *only if your library uses them* | Settings, Finance, expense classes |
| **FOLIO Org** | all | The **code** of the organization to show as the access provider (optional) | Organizations app |
| **FOLIO Order Type** | all three | Click the cell and **choose Ongoing or One-Time from the list** that pops up (we pre-fill it: Ongoing when the SOP shows a Term, One-Time when it does not; change it if we got it wrong). Nothing else is accepted. | (the list) |
| **FOLIO Renewal Interval (Days)** | all three | **Only if the order is Ongoing:** how often it renews, in days (for example 365 for a yearly subscription). Whole numbers only. Leave blank for One-Time. | Your subscription terms |
| **FOLIO Location** | physical, P/E | Where the print copy goes | Settings, Tenant, Locations (you may get a list to choose from) |
| **FOLIO Material Type** | physical, P/E | The kind of item, for example "journal" | Settings, Inventory, Material types (you may get a list to choose from) |

Please use the codes and names **exactly as they appear in FOLIO** (same spelling and capitals).
Some guidance:
- **Every order ends up with a fund.** Please fill it in on every line. A typical setup is one
  fund for online subscriptions and one for print, or funds by subject area. The choice is
  yours (section 3).
- **Ongoing or One-Time?** Choose **Ongoing** for subscriptions that renew (most journals and
  databases) and give the renewal interval in days. Choose **One-Time** for a one-off purchase
  that will not renew; no interval is needed. The choice is made **order by order**, so one
  file can mix both.
- **A blank cell is allowed**: it simply gets a default that we agree with you in advance.
  For order type the default is Ongoing; for the interval it is 365 days; for location and
  material type it is the ones agreed in section 3. If you leave cells blank we tell you how
  many, and you can fill them in if the default is not what you want.
- **Please do not add, delete or reorder the other columns**, and please send back
  **all** of the spreadsheets we sent you.
- If you are unsure how to charge a line, tell us and we will set it aside rather than guess.

## 3. Choices we need you to make
We set these once, at the start. Most have a sensible default, shown in brackets.

| Choice | Question for you |
|---|---|
| **Funds** | One fund for everything, separate funds for print and online, or funds by subject? (Default: one fund for online and one for print.) |
| **Expense classes** | Does your library use them? If so, which class for which kind of title or subject? (Default: not used unless you tell us.) |
| **Access provider** | Do you want the publisher or platform shown as the access provider on each order? It is optional; the vendor on every order is EBSCONET regardless. (Default: a single organization, or left blank.) |
| **Print and P/E subscriptions** | Which locations and material types can you choose from on the spreadsheet? Which is the default for any line you leave blank? Do you have any print subscriptions at all? |
| **Ongoing or One-Time** | Which default for a line you leave blank (Ongoing unless you say otherwise), and which default renewal interval (365 days)? |
| **Inventory** | Should loading also create inventory records (so the e-journals appear in discovery)? If yes, the system matches on ISSN and creates records where there is no match. (Default: no, orders only.) |
| **Receiving** | For print, should the order wait for receipt ("Pending")? For online, no receipt is expected. (Default as shown.) |
| **Currency** | The currency of the prices in the spreadsheet. (Default: USD.) |
| **Zero-dollar lines** | These are removed automatically (most are titles included free in a package). Tell us if you would rather keep any. |
| **"Usage Loading Service" lines** | These look like service fees rather than titles. We can load them or leave them out. Which do you prefer? |

## 4. Ongoing orders: what they are and how you choose them
Every order in FOLIO has two separate settings:
- **Status**: Pending, Open or Closed. *We leave every order Pending.*
- **Order type**: One-Time or Ongoing. *This is what you choose on the spreadsheets.*

The import creates every order as **One-Time**. Your subscriptions renew every year, and an
**Ongoing** order carries the renewal details that a One-Time order does not have: how often
it renews (the *renewal interval*), that it is a *subscription*, and the *renewal date*.
Converting them means FOLIO knows when each subscription comes up for renewal, and it is what
the EBSCONET renewal integration expects. The conversion does not open the orders and does not
touch your funds.

**You decide for each order, on every spreadsheet.** In the *FOLIO Order
Type* column pick **Ongoing** or **One-Time** from the pop-up list. For Ongoing orders, enter
the renewal interval in days in *FOLIO Renewal Interval (Days)*. After loading we convert
exactly the orders you marked Ongoing, using the interval you gave; One-Time orders stay
One-Time. The physical spreadsheet has the same two columns; the interval is rarely needed
there, but the choice is yours for print orders too.

**What we still need from you:**
1. **Are your subscriptions annual?** The default interval is **365 days**; you can give a
   different number of days on any line (a 15-month term, for example), so multi-year or
   non-annual subscriptions are handled line by line.
2. **Which date should drive the renewal?** We default to the **latest end date** on the
   order's lines, so an order never comes up for renewal before its last line has ended. The
   alternatives are the earliest end date, or no renewal date at all.
3. **Should renewals be manual or automatic in FOLIO?** (Default: not manual.)

## 5. What we do with lines that need special handling
| Situation | What we do |
|---|---|
| A line costs $0 (usually a title inside a package) | Removed before you fill in the spreadsheets, and listed for you. |
| A title has no ISSN | Loaded anyway, and listed for you. If it has no ISSN and no EBSCONET title number, it is given an identifier built from its EBSCONET order number so every order carries one. |
| A "Fee" line, or a format we do not recognize | Set aside (it is not on any of your spreadsheets) and listed for you. |
| The same order number appears on more than one line | The first becomes the order; the others are added to it as further order lines in a separate step. |
| A code you entered does not exist in FOLIO | We send you the list of corrections before anything is loaded. |

## 6. What you will see in FOLIO
- Each order's **PO number is your EBSCONET order number**, and its line number is the PO number
  followed by `-1` (for example `U1234567` and `U1234567-1`). This is what lets EBSCONET match
  renewals to the orders.
- Orders are **Pending**, with EBSCONET as the vendor, and show the fund, the price, the
  subscription dates, your account number, and (for online titles) the access provider and
  resource link.
- The order type shows **Ongoing** or **One-Time** as you chose on the spreadsheets; print orders show the location and material type you chose.

## 7. What we will ask you to check
After the load, please open a handful of orders (a mix of online and print, and a couple
with and without an ISSN) and confirm the fund, expense class, price and dates are what you
expect. If something is wrong, we can remove and reload the affected orders.

## 8. Quick checklist
**Before we start**
- [ ] EBSCONET organization exists in FOLIO; we can add account numbers to it
- [ ] Funds and active budgets exist (with expense classes, if used)
- [ ] Organizations for access providers exist, if wanted
- [ ] Locations and material types exist, if you have print or P/E subscriptions
- [ ] An account or screen-share time for us
- [ ] Choices in section 3 answered, and the ongoing questions in section 4 answered

**When we send the workbook (Defaults, electronic, physical, P/E sheets)**
- [ ] Answer the questions on the Defaults sheet
- [ ] Fill in FOLIO Fund on every line
- [ ] Fill in FOLIO Expense Class, if used
- [ ] Fill in FOLIO Org, if wanted
- [ ] Every sheet: choose Ongoing or One-Time from the list on every line; for Ongoing, enter the renewal interval in days
- [ ] Physical and P/E: fill in FOLIO Location and FOLIO Material Type
- [ ] Return **all** the spreadsheets, then correct anything on the list we send back

**After loading**
- [ ] Review a sample of orders in FOLIO
- [ ] Decide when you will open the orders

## Terms used in this guide
| Term | Meaning |
|---|---|
| **SOP** | The order spreadsheet from EBSCONET that lists your subscriptions |
| **PO** | Purchase order |
| **POL** | Purchase order line; each order here has one line, numbered PO number + `-1` |
| **Fund / budget** | Where the money is charged; the budget is the fund's allocation for a fiscal year |
| **Expense class** | An optional tag on the charge, such as "electronic" or "print" |
| **Pending** | An order that has not been opened; nothing is committed against the fund |
| **Ongoing order** | An order that renews on a schedule, with a renewal interval and date |
| **One-Time order** | An order for a single purchase that does not renew |
| **Renewal interval** | The number of days between renewals of an Ongoing order (365 for yearly) |
| **P/E** | Print + electronic: a subscription that includes both formats |
| **Location / material type** | Where a print copy is kept, and what kind of item it is |
| **Access provider** | The publisher or platform that supplies an online title |
