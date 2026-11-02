---
name: Exhibit Register
description: The KAVACH console. Cool ruled paper, white sheets, blue-black ink, one violet accent, and every state shown as a rubber stamp.
colors:
  paper: "#f4f5f2"
  sheet: "#ffffff"
  rail: "#e8eae5"
  hover: "#eceee9"
  rule: "#d8dbd3"
  rule-strong: "#b8bcb2"
  ink: "#1c2433"
  ink-2: "#414b5e"
  ink-3: "#5c6474"
  stamp: "#5b3fa8"
  stamp-deep: "#472f8a"
  stamp-wash: "#efebf8"
  seal: "#8e1b1b"
  strong: "#1f6b45"
  strong-wash: "#e8f2ec"
  possible: "#8a5a00"
  possible-wash: "#f7f0df"
  fail: "#b42318"
  fail-wash: "#fbeceb"
typography:
  display:
    fontFamily: "Noto Sans, system-ui, sans-serif"
    fontSize: "40px"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "Noto Sans, system-ui, sans-serif"
    fontSize: "30px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.015em"
  title:
    fontFamily: "Noto Sans, system-ui, sans-serif"
    fontSize: "21px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-0.01em"
  body:
    fontFamily: "Noto Sans, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.55
    fontFeature: "tnum"
  lede:
    fontFamily: "Noto Sans, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 400
    lineHeight: 1.625
  label:
    fontFamily: "IBM Plex Mono, ui-monospace, monospace"
    fontSize: "12px"
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: "0.12em"
  stamp:
    fontFamily: "Noto Sans, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0.07em"
    fontVariation: "'wdth' 72"
  mono:
    fontFamily: "IBM Plex Mono, ui-monospace, SFMono-Regular, monospace"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  stamp: "4px"
  sm: "6px"
  md: "8px"
  lg: "10px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  section: "32px"
  gutter-mobile: "20px"
  gutter-desktop: "40px"
  rail: "280px"
  topbar: "68px"
components:
  button-primary:
    backgroundColor: "{colors.stamp}"
    textColor: "{colors.sheet}"
    rounded: "{rounded.sm}"
    padding: "0 16px"
    height: "40px"
  button-primary-hover:
    backgroundColor: "{colors.stamp-deep}"
  button-secondary:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "0 16px"
    height: "40px"
  button-secondary-hover:
    backgroundColor: "{colors.hover}"
  button-quiet:
    textColor: "{colors.ink-2}"
    rounded: "{rounded.sm}"
    padding: "0 16px"
    height: "40px"
  button-danger:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.fail}"
    rounded: "{rounded.sm}"
    padding: "0 16px"
    height: "40px"
  input:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "0 14px"
    height: "48px"
  nav-item:
    textColor: "{colors.ink-2}"
    rounded: "{rounded.sm}"
    height: "48px"
  panel:
    backgroundColor: "{colors.sheet}"
    rounded: "{rounded.lg}"
    padding: "24px"
  list-card:
    backgroundColor: "{colors.sheet}"
    rounded: "{rounded.sm}"
    padding: "16px"
  chip:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "4px 8px"
  chip-selected:
    backgroundColor: "{colors.stamp-wash}"
    textColor: "{colors.stamp-deep}"
  stamp:
    typography: "{typography.stamp}"
    rounded: "{rounded.stamp}"
    padding: "4px 7px"
  stamp-large:
    fontSize: "19px"
    rounded: "{rounded.stamp}"
    padding: "7px 11px"
  empty-note:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.md}"
    padding: "16px 20px"
---

# Design System: Exhibit Register

> **Building with this file:** every screen of the KAVACH console follows it. The frontmatter holds the exact values, and the sections below say how to use them. The working code is `kavach/static/vx.css` (tokens and components), `kavach/static/app.js` (helpers such as `stamp()`, `field()`, `tip()`) and `kavach/static/index.html` (the shell and the icon sprite). Reuse those rather than rebuilding the look by eye. Product truth is in `PRODUCT.md`.
>
> The `vx-` prefix on tokens is only a name users never see.

## Overview

**Creative North Star: "The Exhibit Register"**

The interface reads like a well-kept register filled in under office light: cool ruled paper, white sheets, blue-black ink and a violet rubber stamp. Every record is an entry with labelled fields, and a stamp says what state it is in. It is built for long working sessions by people who need to find things and trust them, so it is roomy, plain and exact.

It refuses the usual look of a dark, glowing dashboard: no neon, no glass panels, no decorative gradients and no rows of big metric tiles competing for attention. The world is light only. Depth comes from ruled lines and a stack of three paper tones, and the single shadow is kept for things that float.

**Key Characteristics:**
- Register paper, white ruled sheets, blue-black ink; violet as the one accent.
- State is a named stamp whose border pattern carries the meaning, so it survives without colour.
- Absence is designed: a section stays in place and says why it is empty.
- One grouped rail, one top bar, one page frame on every screen.
- Small spaced mono capitals name values and groups; everything else is sentence case.

## Colors

A cool, near-neutral register with one violet accent, and verdict colours that appear only as state.

### Primary
- **Violet Stamp Ink** (stamp): the one accent. Primary buttons, selection, focus rings, the active navigation icon, links, unread badges, and anything in progress. **Deep Violet** (stamp-deep) is its hover and pressed ink. **Stamp Wash** (stamp-wash) is the selected fill and the text-selection colour.

### Secondary
- **Lac Seal Red** (seal): one meaning only, a locked or final record. It is the only solid-filled stamp. In KAVACH that is a receipt chain that has just been verified.

### Tertiary
Verdict and state only.
- **Verdict Green** (strong, strong-wash): confirmed, complete, success.
- **Caution Amber** (possible, possible-wash): needs review, partial, warning.
- **Error Vermilion** (fail, fail-wash): failures, errors, destructive actions.

### Neutral
- **Register Paper** (paper): the page canvas.
- **Ruled Sheet** (sheet): cards, tables, popovers, dialogs, inputs.
- **Rail Grey** (rail): the app rail, the top bar, image placeholders, the skeleton base.
- **Hover Wash** (hover): row and control hover.
- **Hairline Rule** (rule): dividers and card edges.
- **Strong Rule** (rule-strong): table header rules, secondary button and input borders.
- **Blue-Black Ink** (ink): primary text.
- **Ink 2** (ink-2): secondary text, 8.9:1 on white.
- **Ink 3** (ink-3): meta text and labels, 5.9:1 on white and 5.4:1 on paper. Do not go paler.

**The One Stamp Rule.** Violet is the only accent. It marks what you can act on, what is selected and what is in progress. Nothing decorative is violet.

**The Seal Rule.** Seal red means a locked record. It never marks an error, a warning or emphasis.

**The Verdict Rule.** Green, amber and vermilion are reserved for state. They are never used for categories, charts or decoration.

## Typography

**Body Font:** Noto Sans, the variable cut with the width axis (with system-ui as fallback)
**Label/Mono Font:** IBM Plex Mono at 400, 500 and 600

**Character:** One humanist sans for everything a person reads, plain enough to disappear. The mono gives the console its labels and makes values look like values. Both are self-hosted in `kavach/static/fonts/`, so the console runs with no internet.

### Hierarchy
- **Display** (700, 34px on phones and 40px on desktop, 1.1, -0.02em): every page title, under a short violet rule.
- **Lede** (400, 17px, 1.625, ink-2, at most 70ch): the one line under a page title that says what the page is for.
- **Headline** (700, 30px, 1.2): the main record inside a page.
- **Title** (600, 21px, -0.01em): section heads inside a page, with a count in ink-3 beside them.
- **Body** (400, 16px, 1.55, tabular numerals): all running text. Use 15 to 15.5px for dense rows and notes.
- **Label** (IBM Plex Mono 500, 12px, uppercase, 0.12em, ink-3): the label over a value, table headers and stat captions. Rail group labels are the same at 11px and 0.16em.
- **Stamp** (700, 13px, 72% width, 0.07em, uppercase): stamps only.
- **Large stamp** (700, 19px, 72% width, 0.07em, uppercase): the one verdict a decision card is about, so it reads from across a room.
- **Wordmark** (700, 21px, 0.04em): the product name in the rail, over a tagline in 11px mono capitals at 0.22em.

**The Caps Rule.** Uppercase belongs to stamps, the tagline, and the small mono labels that name a value or a group. Headings, buttons, links and section names are sentence case.

**The Mono Values Rule.** Anything a person will copy somewhere (IDs, hashes, phone numbers, emails) is set in mono with a copy button beside it.

## Layout

**The shell.** A sticky left rail (280px, full height) and a sticky top bar (68px) share Rail Grey and a hairline edge. The rail's brand block is also 68px, so the two meet in one line. The rail holds the mark, the wordmark and tagline, then navigation in labelled groups. The top bar holds the menu button, the breadcrumb at 20px, and on the far right the status stamps and the outlined 44px approvals button.

**Responsive.** Standard breakpoints at 768px, 1024px and 1280px. Below 1024px the rail becomes a drawer of 300px (at most 88% of the screen) over a dimmed page. At 1024px and up, the menu button folds the rail away and the choice is remembered.

**Page frame.** Gutters of 20px on phones and 40px from 768px, 32px then 40px above the content, and 112px below it. Reading and form pages stop at 1180px; list and data pages use the full width. Each page opens with a page head: a 48 × 3px violet rule, the title, the lede, and its actions on the right.

**Rhythm.** A 4px base. Section heads have 32px above and 12px below. Panels pad 20 to 24px, list cards 16px, table cells 14px by 16px. Card grids run 1, 2 then 3 columns (at 768px and 1280px) with 16px gaps.

**Tag fields.** Labelled values sit in a boxed grid of columns at least 220px wide with shared hairlines, the way a paper form is filled in.

**Layering.** Top bar 20, rail 30, popovers and dialogs 40 to 50. A sticky element forms its own stacking context, so the rail needs its z-index or the page paints over anything that opens from it.

**The One Frame Rule.** Every page sits in the same shell and page frame. A new page does not invent its own width.

## Elevation & Depth

Flat by default. Depth is tonal (paper under sheet, rail beside both) and ruled with 1px hairlines.

### Shadow Vocabulary
- **Lift** (`box-shadow: 0 1px 2px rgba(28,36,51,0.06), 0 6px 20px -8px rgba(28,36,51,0.18)`): tooltips, popovers, menus, the mobile drawer and dialogs.

**The Float-Only Rule.** Only things that float get Lift. Cards and sheets sitting on the page are bordered, never shadowed. The one exception is the first-step callout, which carries the faintest small shadow.

**Scrims.** Dialogs dim the page with Blue-Black Ink at 35%. The mobile drawer uses 28% with a slight blur, and that is the only blur in the system.

## Shapes

Soft corners, never pills on containers: stamps at 4px; buttons, chips, list cards and menu rows at 6px; form fields and notes at 8px; panels, popovers and dialogs at 10px. Full round only for count badges and filter pills.

Borders are 1px hairlines. Stamps use 1.5px, or 2px when failed and a 3px double when strong. A dashed border means "not there": the empty note and the unverified stamp.

## Components

Tactile but restrained, like office stationery. Controls press down 1px and change colour in 150ms; nothing bounces.

### Stamps
The signature of the system: a condensed uppercase label inside a border of its own colour. Pattern first, colour second, so state reads in greyscale.

| Tone | Pattern | Use it for |
|---|---|---|
| `info` | ink-2, solid | Neutral fact, standby |
| `done` | green, solid, tick icon | Complete, active, healthy |
| `strong` | green, 3px double | Confirmed, the strongest verdict |
| `possible` | amber, solid | Needs review, partial |
| `failed` | vermilion, 2px, alert icon | Error, failed |
| `running` | violet, an ink stripe travels through every 1.4s | In progress |
| `queued` | violet, dotted, dashed-circle icon | Waiting to start |
| `skipped` | ink-3, dotted | Not run, disabled |
| `rejected` | ink-3, struck through | Ruled out |
| `lead` | ink-2, dashed | Unverified, not yet proven |
| `private` | ink, solid, lock icon | Restricted to the viewer |
| `sealed` | white on seal red, solid fill, shield icon | Locked, final |

When a stage finishes while the user is watching, its stamp lands in one 160ms press (from 1.1× and -1.5° at 35% opacity to rest). Use it for state changes only.

### Buttons
- **Shape:** gently rounded (6px) with a 1px border, 40px tall at 16px text, or 36px at 15px for the small size. Weight 500. Icons are 16px.
- **Primary:** white on violet, deep violet on hover. One per view: it is the action.
- **Secondary:** ink on sheet with a strong rule, hover wash. This is the default.
- **Quiet:** borderless ink-2, hover wash.
- **Danger:** vermilion text on sheet, red wash on hover.
- **States:** 1px press-down when active, 50% opacity when disabled, a spinner in place of the icon when loading.
- **Focus:** a 2px violet outline with a 2px offset, on every focusable element.

### Inputs / Fields
- **Standard:** sheet with a strong-rule border, 8px corners, 48px tall, 17px text. The border turns violet on focus.
- **Labelled:** the label sits in the field's top border as an 11.5px mono capital. This is the usual form style.
- **Search:** a standard field with an 18px icon inset 16px from the left.
- **Placeholder:** ink-3 at 70%.

### Field and Tag
A Field is a mono capital label, a 16px value (15px if mono), and an `empty` word that says what absence means. A Tag is a sheet holding Fields in the boxed tag grid.

### Register table
Mono capital headers over a strong rule, sticky at the top of the scroll area. Cells sit on hairlines, the last row has no rule, and rows wash on hover. Wrap wide tables in a scrolling sheet (10px corners, hairline) so they never widen the page.

### Cards / Containers
- **Panel:** sheet, hairline, 10px corners, 20 to 24px padding, no shadow.
- **List card:** sheet, hairline, 6px corners, 16px padding, an 18px semibold title with a stamp on the right. The border turns violet on hover. 
- **First-step callout:** at most one per page, for the thing that must happen first. Stamp Wash with a 5px violet left edge, 10px corners, a 44px violet icon tile, a mono capital step label, a 17px semibold deep violet title, and a primary button on the right.
- **Stats strip:** one sheet holding three numbers at 36px bold, each over a 12.5px mono caption. A number takes colour only when it reports state. It is a single summary strip, not a row of tiles.

### Navigation
- **Rail item:** 48px rows, an 18px icon and a 15px label, with 18px left padding. Hover washes the row.
- **Active rail item:** semibold ink with a violet icon, a 3px violet bar on the left edge with a soft glow, and a violet wash fading to the right.
- **Rail count:** a pill on the right, Stamp Wash when there is something to count.
- **Highlighted rail item:** at most one in the app, for the feature nobody should miss. Stamp Wash with a violet ring and a slow 3.2s breathing glow.
- **Rail group:** a mono capital label with a rule that fades out after it.
- **Tabs:** underlined, 48px tall, 16px text. The active tab has a 2px violet underline and semibold ink. Counts sit in a small pill.
- **Filter pills:** 32px and fully round. The selected pill is solid ink with white text, others are sheet with a hairline that turns violet on hover.
- **Segmented switch:** a strong-rule box with 32px segments; the selected segment is solid ink with white text.

### Chips
A value that can be picked or dragged: paper with a hairline, violet border on hover, 6px corners. When selected it takes Stamp Wash, a violet border, deep violet text and a tick.

### Notices
- **Banner:** 8px corners, a hairline of the state's colour at 30%, its wash as the fill, and text in its colour. Green for done, vermilion for errors. Put it directly above what it refers to.
- **Empty note:** a 2px dashed box at 8px corners on a sheet (or the red or amber wash for failed and caution), with a semibold title, a sentence saying why it is empty, and an optional action.

### Dialogs
A sheet at 10px corners with Lift, at most 90% of the screen height and scrolling inside. Padding is 24px, or 28px from 768px. The title is 24px bold at -0.01em, with a 36px close button in the top right. Actions sit bottom right with 8px gaps. Escape closes it unless something is mid-save.

### Small parts
- **Tip:** an ⓘ that opens a Lift popover on hover or keyboard focus. Caveats live here, not in paragraphs. It is not rendered while closed, so it can never widen the page.
- **Copy value:** a mono value with a 24px copy button that shows a green tick for 1.4s.
- **External link:** violet text, a violet underline at 40% that firms up on hover, and a small external-link icon.
- **Skeleton:** a pale rail-to-hover shimmer over 1.6s. Never a spinner in the middle of content.
- **Icons:** Lucide throughout: 16px in buttons, 18px in the rail and menus, 22px in the top bar, 13px at stroke 2.25 in stamps.

### Motion
Colour changes take 150ms. Everything animated (the stamp press, the running stripe, the shimmer, the breathing glow) stops under `prefers-reduced-motion`.

## Do's and Don'ts

### Do:
- **Do** express every state as a named stamp with its border pattern; colour only reinforces it.
- **Do** keep every section in place and use an empty note to say why it is empty (not run, nothing found, failed, no access).
- **Do** use the page frame and page head on every page inside the shell.
- **Do** keep one primary button per view.
- **Do** keep tooltips, menus and dialogs as the only things with Lift.
- **Do** save the stamp press for a state change the user just watched happen.

### Don't:
- **Don't** use seal red for anything but a locked record.
- **Don't** use green, amber or vermilion outside state, including in charts or categories.
- **Don't** signal state with colour alone, a coloured dot or a tinted row.
- **Don't** let a section vanish because its data is empty.
- **Don't** add dark mode, glass, glow or gradients. The only gradients are the active rail wash, the fading rail rule, the skeleton and the running stripe.
- **Don't** put shadows on cards that sit on the page.
- **Don't** put a mono capital label above a page or section heading as a kicker; mono capitals name values and rail groups.
- **Don't** use uppercase for headings, buttons or links.

## KAVACH vocabulary

The words and stamps below are the same on every screen. The API's verdict names stay in the receipts and in a stamp's hover title.

| What | Stamp tone | Words on screen |
|---|---|---|
| ALLOW | `done` | Allowed |
| ALLOW_WITH_SAFEGUARD | `strong` | Allowed with undo |
| ESCALATE | `possible` | Needs a person |
| DENY | `failed` | Blocked |
| A step nobody checked | `lead` | Not checked |
| A broken tool call | `skipped` | Broken call |
| Agent still working | `running` | Working |
| Held, queued or parked | `queued` | Held, Queued, Parked |
| Went out | `done` | Went out |
| Taken back | `rejected` | Cancelled |
| Receipt chain just verified | `sealed` | Sealed |
| Receipt chain broken | `failed` | Broken |

Where a value came from: from the user is `done`, from company records or based on the user's words is `info`, from an email or web page is `possible`, written by the agent is `lead`.

The four questions answer with stamps too: Yes is `done`, No is `failed`, and anything in between is `possible`.

Charts and the risk meter use ink and violet only, never the verdict colours. Violet marks the system being talked about.
