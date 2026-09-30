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
  in a spreadsheet (step 3 below).

## The process, in order
| # | Who | What happens |
|---|---|---|
| 1 | You / EBSCONET | The EBSCONET order spreadsheet (SOP) is obtained from your EBSCONET representative. |
| 2 | You | **Before we start:** your FOLIO system is checked against the list in section 1 below, and the choices in section 3 are made. |
| 3 | EBSCO | We prepare your copy of the spreadsheet: we remove the lines that cost nothing and add three empty columns for you to fill in. We send it to you. |
| 4 | **You** | **You fill in the three columns on every line and send the file back** (section 2). |
| 5 | EBSCO | We check your codes against your FOLIO system. If anything is wrong (a mistyped code, a fund that does not exist) we send you the list, you correct it, and we check again. This repeats until the file is clean. |
| 6 | EBSCO | We load the orders into FOLIO as Pending orders. |
| 7 | You | You look over a sample of the orders in FOLIO and tell us they look right. |
| 8 | EBSCO | We convert the orders to *ongoing* orders, if you want that (section 4). |
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
- For **print** subscriptions only: a **location** (for example your serials or periodicals
  location) and a **material type** (for example "journal" or "serial").
- **An account for us** to work with, with permission to create Data Import profiles, run
  imports, create and edit orders, and read the finance and organization settings. (Or
  your administrator can work with us on a screen share.)

## 2. What you fill in: three columns, on every line
In the spreadsheet we send you, three columns are highlighted. On each line please enter:

| Column | What to enter | Where to find the code |
|---|---|---|
| **FOLIO Fund** | The **code** of the fund that pays for this subscription | Finance app, list of funds |
| **FOLIO Expense Class** | The **code** of the expense class, *only if your library uses them* | Settings, Finance, expense classes |
| **FOLIO Org** | The **code** of the organization to show as the access provider (optional) | Organizations app |

Please use the codes **exactly as they appear in FOLIO** (same spelling and capitals).
Some guidance:
- **Every order ends up with a fund.** Please fill it in on every line. A typical setup is one
  fund for online subscriptions and one for print, or funds by subject area. The choice is
  yours (section 3).
- **A blank cell is allowed**: it simply gets a default that we agree with you in advance.
  If you leave cells blank we tell you how many, and you can fill them in if the default is
  not what you want.
- **Please do not add, delete or reorder the other columns.**
- If you are unsure how to charge a line, tell us and we will set it aside rather than guess.

## 3. Choices we need you to make
We set these once, at the start. Most have a sensible default, shown in brackets.

| Choice | Question for you |
|---|---|
| **Funds** | One fund for everything, separate funds for print and online, or funds by subject? (Default: one fund for online and one for print.) |
| **Expense classes** | Does your library use them? If so, which class for which kind of title or subject? (Default: not used unless you tell us.) |
| **Access provider** | Do you want the publisher or platform shown as the access provider on each order? It is optional; the vendor on every order is EBSCONET regardless. (Default: a single organization, or left blank.) |
| **Print subscriptions** | Which location and material type? Do you have any print subscriptions at all? |
| **Inventory** | Should loading also create inventory records (so the e-journals appear in discovery)? If yes, the system matches on ISSN and creates records where there is no match. (Default: no, orders only.) |
| **Receiving** | For print, should the order wait for receipt ("Pending")? For online, no receipt is expected. (Default as shown.) |
| **Currency** | The currency of the prices in the spreadsheet. (Default: USD.) |
| **Zero-dollar lines** | These are removed automatically (most are titles included free in a package). Tell us if you would rather keep any. |
| **"Usage Loading Service" lines** | These look like service fees rather than titles. We can load them or leave them out. Which do you prefer? |

## 4. Ongoing orders: what they are and why you might want them
Every order in FOLIO has two separate settings:
- **Status**: Pending, Open or Closed. *We leave every order Pending.*
- **Order type**: One-Time or Ongoing. *This is what the conversion changes.*

The import creates every order as **One-Time**. Your subscriptions renew every year, and an
**Ongoing** order carries the renewal details that a One-Time order does not have: how often
it renews (the *renewal interval*), that it is a *subscription*, and the *renewal date*.
Converting them means FOLIO knows when each subscription comes up for renewal, and it is what
the EBSCONET renewal integration expects. The conversion does not open the orders and does not
touch your funds.

It is optional. If you do not want it, the orders simply stay One-Time.

**What we need from you to set it up:**
1. **Do you want the orders converted to Ongoing?** (Recommended if you will renew through
   EBSCONET or manage renewals in FOLIO.)
2. **Are your subscriptions annual?** We use a renewal interval of **365 days**. Some terms in
   a spreadsheet can be different (a 15-month term, for example). Tell us if you have
   multi-year or non-annual subscriptions, so we can handle them differently.
3. **Which date should drive the renewal?** We default to the **latest end date** on the
   order's lines, so an order never comes up for renewal before its last line has ended. The
   alternatives are the earliest end date, or no renewal date at all.
4. **Should renewals be manual or automatic in FOLIO?** (Default: not manual.)

## 5. What we do with lines that need special handling
| Situation | What we do |
|---|---|
| A line costs $0 (usually a title inside a package) | Removed before you fill in the spreadsheet, and listed for you. |
| A title has no ISSN | Loaded anyway, and listed for you. If it has no ISSN and no EBSCONET title number, it is given an identifier built from its EBSCONET order number so every order carries one. |
| A "Fee" line, or a format we do not recognize | Set aside and listed for you. |
| The same order number appears on more than one line | The first becomes the order; the others are added to it as further order lines in a separate step. |
| A code you entered does not exist in FOLIO | We send you the list of corrections before anything is loaded. |

## 6. What you will see in FOLIO
- Each order's **PO number is your EBSCONET order number**, and its line number is the PO number
  followed by `-1` (for example `U1234567` and `U1234567-1`). This is what lets EBSCONET match
  renewals to the orders.
- Orders are **Pending**, with EBSCONET as the vendor, and show the fund, the price, the
  subscription dates, your account number, and (for online titles) the access provider and
  resource link.
- If they were converted, the order type shows **Ongoing**.

## 7. What we will ask you to check
After the load, please open a handful of orders (a mix of online and print, and a couple
with and without an ISSN) and confirm the fund, expense class, price and dates are what you
expect. If something is wrong, we can remove and reload the affected orders.

## 8. Quick checklist
**Before we start**
- [ ] EBSCONET organization exists in FOLIO; we can add account numbers to it
- [ ] Funds and active budgets exist (with expense classes, if used)
- [ ] Organizations for access providers exist, if wanted
- [ ] Location and material type exist, if you have print subscriptions
- [ ] An account or screen-share time for us
- [ ] Choices in section 3 answered, and the ongoing questions in section 4 answered

**When we send the spreadsheet**
- [ ] Fill in FOLIO Fund on every line
- [ ] Fill in FOLIO Expense Class, if used
- [ ] Fill in FOLIO Org, if wanted
- [ ] Return the file, then correct anything on the list we send back

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
| **Access provider** | The publisher or platform that supplies an online title |
